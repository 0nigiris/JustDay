"""Удалённая оболочка terminal поверх уже защищённого Telegram long polling."""
from __future__ import annotations

import asyncio
import json
import os
import time
import uuid

from . import config, telegram, terminal


class TelegramShell:
    """Очередь оболочки в приватном чате: задачи, лестница, подтверждения и журнал."""

    def __init__(self, daemon) -> None:
        self.daemon = daemon
        self.work = terminal.Work(config.load())
        # `opencode run` в нашей лестнице не отдаёт запросы разрешений вызывающей оболочке.
        # Его обычный режим может выполнять инструменты без вопроса, поэтому на телефоне оставляем
        # только Claude Code SDK, где опасный шаг действительно ждёт нажатия Telegram-кнопки.
        blocked = [r for r in self.work.rungs if r.engine != terminal.CLAUDE]
        self.work.rungs = [r for r in self.work.rungs if r.engine == terminal.CLAUDE]
        self.work.skipped.extend(blocked)
        self.work.step = 0
        self.work.approve = self.approve
        self.queue: list[str] = []
        self.worker: asyncio.Task | None = None
        self.current: asyncio.Task | None = None
        self.pending: dict[str, asyncio.Future[bool]] = {}
        self.journal = config.STATE_DIR / "terminal-telegram.md"

    def _log(self, text: str) -> None:
        self.journal.parent.mkdir(parents=True, exist_ok=True)
        fd = os.open(self.journal, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        with os.fdopen(fd, "a", encoding="utf-8") as out:
            out.write(f"\n## {time.strftime('%Y-%m-%d %H:%M:%S')}\n{text.rstrip()}\n")

    async def message(self, update: dict) -> bool:
        """Обработать входящее сообщение оболочки. False означает обычную реплику Джарвису."""
        msg = (update or {}).get("message") or {}
        text = str(msg.get("text") or "").strip()
        command, _, arg = text.partition(" ")
        command = command.split("@", 1)[0].lower()
        if command in ("/задача", "/task"):
            if not arg.strip():
                await self.reply("Напиши задачу после /задача.")
            else:
                self.queue.append(arg.strip())
                self._log(f"Задача добавлена: {arg.strip()}")
                if self.worker is None or self.worker.done():
                    self.worker = asyncio.create_task(self._drain())
                await self.reply(f"В очереди: {len(self.queue)}. Задача принята.")
            return True
        if command in ("/очередь", "/queue"):
            rows = ([f"Сейчас: {self.current.get_name()}" if self.current and not self.current.done()
                     else "Сейчас ничего не выполняется"]
                    + [f"{i}. {item}" for i, item in enumerate(self.queue, 1)])
            await self.reply("\n".join(rows))
            return True
        if command in ("/модель", "/model"):
            if not self.work.rungs:
                await self.reply("В удалённой оболочке нет доступной ступени Claude Code.")
                return True
            if arg.strip():
                self.work.now.model = arg.strip()
                await self.reply(f"Модель текущей ступени: {self.work.now.label}")
            else:
                await self.reply(f"Текущая модель: {self.work.now.label}. Чтобы сменить: /модель ИМЯ")
            return True
        if command in ("/лестница", "/ladder"):
            rows = [f"{'▶' if i == self.work.step else '·'} {r.label}"
                    for i, r in enumerate(self.work.rungs)]
            rows.extend(f"— {r.label}: нет входа" for r in self.work.skipped)
            await self.reply("\n".join(rows))
            return True
        if command in ("/стоп", "/stop"):
            count = len(self.queue)
            self.queue.clear()
            if self.current and not self.current.done():
                self.current.cancel()
                try:
                    await self.current
                except asyncio.CancelledError:
                    pass
            await self.reply(f"Остановлено; убрано из очереди: {count}.")
            return True
        if command in ("/журнал", "/journal"):
            text = self.journal.read_text(encoding="utf-8")[-12000:] if self.journal.exists() else "Журнал пока пуст."
            await telegram.send_shell(text)
            return True
        if msg.get("voice"):
            await self.voice(msg["voice"])
            return True
        return False

    async def voice(self, voice: dict) -> None:
        path = None
        loop = asyncio.get_running_loop()
        try:
            path = await loop.run_in_executor(None, telegram.download_voice, str(voice.get("file_id") or ""))
            text = await loop.run_in_executor(None, self.daemon.transcribe_file, str(path))
            if not text.strip():
                await self.reply("Не расслышал голосовое.")
                return
            self.queue.append(text.strip())
            self._log(f"Голосовая задача распознана: {text.strip()}")
            if self.worker is None or self.worker.done():
                self.worker = asyncio.create_task(self._drain())
            await self.reply(f"Распознал: {text.strip()}\nЗадача в очереди: {len(self.queue)}.")
        except Exception as e:
            await self.reply(f"Не удалось принять голосовое: {e}")
        finally:
            if path:
                path.unlink(missing_ok=True)

    async def callback(self, update: dict) -> bool:
        query = telegram.mine_callback(update)
        if query is None:
            return False
        data = str(query.get("data") or "").split(":")
        future = self.pending.pop(data[1], None) if len(data) == 3 and data[0] == "approve" else None
        if future and not future.done():
            future.set_result(data[2] == "yes")
        await asyncio.get_running_loop().run_in_executor(
            None, telegram.call, "answerCallbackQuery", {"callback_query_id": query.get("id"),
                                                            "text": "Решение принято" if future else "Запрос устарел"})
        return True

    async def approve(self, desc: str, reason: str) -> bool:
        ident = uuid.uuid4().hex[:20]
        future = asyncio.get_running_loop().create_future()
        self.pending[ident] = future
        markup = {"inline_keyboard": [[
            {"text": "Разрешить", "callback_data": f"approve:{ident}:yes"},
            {"text": "Отклонить", "callback_data": f"approve:{ident}:no"},
        ]]}
        prompt = f"Разрешить действие оболочки?\n{desc}" + (f"\n{reason}" if reason else "")
        try:
            await asyncio.get_running_loop().run_in_executor(
                None, telegram.call, "sendMessage", {"chat_id": telegram.chat(), "text": prompt,
                                                       "reply_markup": json.dumps(markup, ensure_ascii=False)})
            return await asyncio.wait_for(future, timeout=600)
        except asyncio.CancelledError:
            raise
        except Exception:
            return False
        finally:
            self.pending.pop(ident, None)

    async def _drain(self) -> None:
        while self.queue:
            task = self.queue.pop(0)
            if not self.work.rungs:
                await self.reply("Задача осталась без запуска: для удалённых разрешений нужна доступная ступень Claude Code.")
                continue
            self.current = asyncio.create_task(self.work.send(task), name=task[:70])
            self._log(f"Начато: {task}")
            try:
                said = await self.current
                answer = said.text or ("Не получилось: " + said.error if said.error else "Готово.")
                self._log(f"Ответ: {answer}")
                await telegram.send_shell(answer)
            except asyncio.CancelledError:
                self._log(f"Остановлено: {task}")
                raise
            except Exception as e:
                self._log(f"Ошибка: {e}")
                await self.reply(f"Задача завершилась ошибкой: {e}")
            finally:
                self.current = None

    async def reply(self, text: str) -> None:
        await asyncio.get_running_loop().run_in_executor(None, telegram.send, text)
