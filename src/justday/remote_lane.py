"""Просьбы издалека: надиктованное с телефона, телеграм, отложенные сообщения и доклад о них.

Вынесено из daemon.py (Р-80). Миксин: тела методов не менялись, `self` — демон."""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import subprocess

import numpy as np

from . import (
    audio,
    events,
    geo,
    inbox,
)
from .aio import spawn
from .i18n import t

log = logging.getLogger("justday.daemon")


class RemoteMixin:
    def transcribe_file(self, path: str) -> str:
        """Звук, записанный где-то ещё (телефон), — теми же ушами, что и микрофон на столе.

        Распознавание всё равно происходит здесь: с телефона приходит файл, а не текст,
        и дальше он идёт той же дорогой, что и сказанное вслух у компьютера."""
        if not path or not os.path.exists(path):
            raise FileNotFoundError(path)
        raw = subprocess.run(
            ["ffmpeg", "-nostdin", "-loglevel", "error", "-i", path,
             "-ac", "1", "-ar", str(audio.RATE), "-f", "s16le", "-"],
            capture_output=True, timeout=120).stdout
        if not raw:
            return ""
        return self.stt.transcribe(np.frombuffer(raw, dtype=np.int16))

    async def dictate(self, path: str, to_inbox: bool = False, created: float = 0.0) -> dict:
        """Надиктованное с телефона: распознать здесь и выполнить, как сказанное вслух.

        `to_inbox` — запись, наговоренная без связи: выполнять её сейчас поздно и опасно
        («выключи компьютер», сказанное час назад, к делу уже не относится). Такое ложится
        в список сообщений, и ассистент разберётся с ним, когда доложит хозяину."""
        loop = asyncio.get_running_loop()
        self.state = "transcribing"
        try:
            text = await loop.run_in_executor(None, self.transcribe_file, path)
        finally:
            self.state = "thinking" if self.brain.busy else "idle"
        if not text:
            events.emit("dictate_empty")
            return {"ok": False, "error": t("Не расслышал.")}
        if to_inbox:
            rec = inbox.add(text, "phone-voice", created)
            events.emit("inbox_add", source="phone-voice", text=text[:200])
            self._inbox_soon()
            return {"ok": True, "text": text, "id": rec["id"], "pending": len(inbox.pending())}
        events.emit("heard", text=text, source="phone")
        self.publish(kind="heard", detail=text)
        local = await self.handle_local(text, "phone")
        reply = local if local is not None else await self.chat_ask("phone", text)
        return {"ok": True, "text": text, "result": reply or t("сделано")}

    async def _telegram_loop(self) -> None:
        """Слушать телеграм длинным опросом и отвечать тем же Джарвисом, что и дома.

        Почему не вебхук: вебхук потребовал бы открытого наружу порта, а наше правило — только
        127.0.0.1. Длинный опрос ходит наружу сам и ничего не слушает.

        Чужие сообщения выбрасываются молча (`telegram.mine`): бот открыт всему интернету, и без
        этой проверки любой, кто найдёт его имя, писал бы прямо в мозг — с почтой, окнами и правом
        запускать программы.
        """
        from . import telegram as tg

        if not tg.ready():
            return
        self._tg_gate = tg.PinGate()
        loop = asyncio.get_running_loop()
        offset = 0
        quiet = 0.0
        while True:
            try:
                got = await loop.run_in_executor(None, tg.updates, offset)
                quiet = 0.0
            except Exception as e:                  # сеть рвётся; молчать об этом вечно нельзя
                quiet = min(60.0, quiet * 2 or 5.0)
                log.debug("телеграм: %s", e)
                await asyncio.sleep(quiet)
                continue
            for upd in got or []:
                offset = max(offset, int(upd.get("update_id", 0)) + 1)
                if upd.get("callback_query"):
                    # Кнопка «Разрешить» — это тоже команда: пока замок PIN закрыт, она недействительна.
                    if self._telegram_shell and self._tg_gate.is_open():
                        with contextlib.suppress(Exception):
                            await self._telegram_shell.callback(upd)
                    continue
                if (where := tg.location(upd)) is not None:
                    if self._tg_gate.is_open():     # чужая рука с угнанным аккаунтом не «перевозит» владельца
                        geo.remember(*where)        # координаты нужны наблюдателю; в мозг они не идут
                    continue
                if not tg.owned(upd):
                    continue
                verdict = self._tg_gate.check(tg.mine(upd))
                if verdict != "open":
                    msg = upd.get("message") or {}
                    with contextlib.suppress(Exception):
                        if verdict in ("unlocked", "denied"):   # PIN не должен оставаться в переписке
                            await loop.run_in_executor(None, tg.call, "deleteMessage",
                                                       {"chat_id": tg.chat(), "message_id": msg.get("message_id")})
                        await loop.run_in_executor(None, tg.send, tg.PIN_REPLY[verdict])
                    continue
                if self._telegram_shell is None:
                    from .telegram_shell import TelegramShell
                    self._telegram_shell = TelegramShell(self)
                try:
                    handled = await self._telegram_shell.message(upd)
                except Exception:
                    log.exception("телеграм-оболочка: команда не удалась")
                    continue
                if handled:
                    continue
                text = tg.mine(upd)
                if not text:
                    continue
                events.emit("heard", text=text, source="telegram")
                try:
                    local = await self.handle_local(text, "telegram")
                    reply = local if local is not None else await self.chat_ask("telegram", text)
                except Exception:
                    log.exception("телеграм: ход не удался")
                    reply = "Не получилось — посмотри журнал."
                with contextlib.suppress(Exception):
                    await loop.run_in_executor(None, tg.send, reply or "сделано")

    # ---------------- сообщения с телефона ----------------
    def _inbox_soon(self, delay: float = 4.0) -> None:
        """Доложить о накопившемся — но не мгновенно.

        Сообщения приходят пачкой: телефон, увидев компьютер в сети, отдаёт всё, что
        накопил в дороге. Небольшая пауза собирает их в один доклад вместо пяти."""
        if self._inbox_timer and not self._inbox_timer.done():
            self._inbox_timer.cancel()
        self._inbox_timer = spawn(self._inbox_report(delay))

    async def _inbox_report(self, delay: float) -> None:
        await asyncio.sleep(delay)
        items = inbox.pending()
        if not items:
            return
        # Ждём, пока ассистент освободится: перебивать им же начатую работу незачем,
        # сообщения и так пролежали дольше.
        while self.brain.busy or self.state != "idle":
            await asyncio.sleep(5)
            if not inbox.pending():
                return
        items = inbox.pending()
        inbox.mark_reported([i["id"] for i in items])
        self.publish(kind="tool", detail=t("Сообщения с телефона: {n}", n=len(items)))
        one = len(items) == 1
        self._event_queue.put_nowait(
            f"[Событие JustDay] Пока тебя не было, с телефона {'пришла просьба' if one else 'пришли просьбы'}:\n"
            f"{inbox.summary(items)}\n"
            "Доложи хозяину коротко, своими словами («вот что мне передали с телефона…»), и сам реши по смыслу: "
            "что-то сделай сразу, что-то занеси в планы (`justday plan add …`), о чём-то спроси. "
            "Если просьба уже неактуальна по времени — скажи об этом и не делай. "
            "Когда дело сделано (или отказано), запиши итог одной строкой: `justday inbox reply ID текст`, "
            "ID стоит в скобках у просьбы: тот, кто передал, прочтёт его в `justday inbox list`.")
