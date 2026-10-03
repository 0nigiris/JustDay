"""Окно оболочки: чёрный терминал, одна строка состояния, одна строка ввода.

Почему textual. Нужно было то, что умеет любой терминальный клиент и чего нет у `input()`: ввод
внизу, бегущий ответ сверху, строка состояния, которая обновляется сама. Писать это на ANSI-кодах
значит полдня чинить перенос строк в чужом шрифте.

Что здесь нарочно скромно: ни одного своего инструмента, ни одной своей модели. Окно показывает
работу и отдаёт команды — думает `terminal.Work`, работают Claude Code и OpenCode.
"""
from __future__ import annotations

import asyncio
from typing import ClassVar

from textual.app import App, ComposeResult
from textual.containers import Vertical
from textual.widgets import Input, RichLog, Static

from . import config, terminal

HELP = """[b]Команды[/b]
  /model ИМЯ     сменить модель на этой ступени (opus, sonnet, haiku…)
  /effort УРОВЕНЬ  сколько думать: low, medium, high
  /queue         показать очередь задач; /drop [N] — убрать задачу N (по умолчанию последнюю)
  /compact       попросить сжать разговор
  /ladder        показать лестницу
  /up            вернуться на верхнюю ступень
  /new           начать разговор заново
  /night [ЧАСЫ]  уйти спать: экраны гаснут, музыка на паузу, машине не даю заснуть, кончились
                 все ступени — жду возвращения лимитов, опасное отклоняю (по умолчанию 8 часов)
  /day           вернуться к обычной работе: экраны, звук и подтверждения назад
  /help, /quit"""


YES = ("д", "да", "y", "yes", "ага", "ок")


class Shell(App):
    """Одно окно: задача сверху, ответ посередине, состояние и ввод снизу."""

    CSS = """
    Screen { background: #0b0b0d; }
    #log { background: #0b0b0d; color: #e7e7ea; padding: 1 2; }
    #status { background: #15151a; color: #8d8d99; padding: 0 2; height: 1; }
    Input { background: #15151a; color: #e7e7ea; border: none; padding: 0 2; }
    Input:focus { border: none; }
    """
    BINDINGS: ClassVar = [("ctrl+c", "quit", "Выход")]

    def __init__(self) -> None:
        super().__init__()
        self.cfg = config.load()
        self.work = terminal.Work(self.cfg)
        self.busy = False
        self.turn: asyncio.Task | None = None   # ход держим за руку: без ссылки его соберёт сборщик
        self.guard = 0                          # сторож, не дающий машине заснуть ночью
        self.dark = False                       # машина в режиме сервера: экраны и звук наши
        self.queue: list[str] = []              # задачи, написанные поверх идущей: ход один за раз
        self.question: asyncio.Future | None = None   # вопрос человеку: следующая строка ввода — ответ
        self.work.approve = self.approve

    def compose(self) -> ComposeResult:
        with Vertical():
            yield RichLog(id="log", markup=True, wrap=True, auto_scroll=True)
            yield Static("", id="status")
            yield Input(placeholder="задача…", id="ask")

    def on_mount(self) -> None:
        log = self.query_one("#log", RichLog)
        log.write("[b]JustDay[/b] — задачу подхватывает тот, кто сейчас может.")
        if self.work.skipped:
            log.write("[#8d8d99]Пропускаю ступени без входа: "
                      + ", ".join(r.label for r in self.work.skipped) + "[/]")
        log.write("[#8d8d99]/help — что умеет это окно[/]\n")
        self.refresh_status()
        self.query_one("#ask", Input).focus()

    def refresh_status(self, doing: str = "") -> None:
        bits = [self.work.now.label]
        if self.work.effort:
            bits.append(f"усилие {self.work.effort} ({self.work.why})")
        bits.append(f"ступень {self.work.step + 1} из {len(self.work.rungs)}")
        # Место в разговоре: он должен видеть, что до сжатия осталось немного, **до** того, как
        # работа упрётся в стену. 100% не показываем — это шум.
        if (free := self.work.free()) < 1.0:
            bits.append(f"место {int(free * 100)}%")
        if self.guard or self.dark:
            bits.append("ночь" + (" · тёмный экран" if self.dark else ""))
        if self.queue:
            bits.append(f"в очереди {len(self.queue)}")
        if self.work.spent:
            bits.append(f"${self.work.spent:.4f}")
        if doing:
            bits.insert(0, doing)
        self.query_one("#status", Static).update(" · ".join(bits))

    # ───────────── ввод ─────────────

    async def on_input_submitted(self, event: Input.Submitted) -> None:
        text = event.value.strip()
        event.input.value = ""
        if not text:
            return
        log = self.query_one("#log", RichLog)
        if self.question and not self.question.done():
            self.question.set_result(text.lower() in YES)
            log.write(f"[b #4c8dff]›[/] {text}\n")
            return
        if text.startswith("/") and not text.startswith("/compact"):
            self.command(text)
            return
        if self.busy:
            # Лестница и сессии держат один ход за раз, поэтому не отказываем, а ставим в очередь:
            # человек пишет три задачи и уходит.
            self.queue.append(text)
            log.write(f"[#8d8d99]В очереди №{len(self.queue)}: {text}[/]")
            self.refresh_status("думает")
            return
        self.start(text)

    def start(self, text: str) -> None:
        log = self.query_one("#log", RichLog)
        log.write(f"[b #4c8dff]›[/] {text}\n")
        self.busy = True
        self.refresh_status("думает")
        self.turn = asyncio.create_task(self.ask(text))

    async def approve(self, desc: str, reason: str) -> bool:
        """Спросить человека в окне, можно ли опасное. Ждём ответа сколько надо: молчание — не «да»."""
        log = self.query_one("#log", RichLog)
        log.write(f"\n[b #d4a72c]? Разрешить: {desc}[/]" + (f"\n[#8d8d99]{reason}[/]" if reason else "")
                  + "\n[#8d8d99]д — разрешить, любое другое — отклонить[/]")
        self.question = asyncio.get_running_loop().create_future()
        self.refresh_status("ждёт твоего ответа")
        try:
            return await self.question
        finally:
            self.question = None

    def command(self, line: str) -> None:
        log = self.query_one("#log", RichLog)
        word, _, rest = line[1:].partition(" ")
        rest = rest.strip()
        if word in ("quit", "exit", "q"):
            self.exit()
        elif word == "help":
            log.write(HELP + "\n")
        elif word == "queue":
            for i, t in enumerate(self.queue, 1):
                log.write(f"  {i}. {t}")
            log.write("" if self.queue else "[#8d8d99]Очередь пуста.[/]\n")
        elif word == "drop":
            try:
                n = int(rest) if rest else len(self.queue)
                gone = self.queue.pop(n - 1) if n >= 1 else self.queue.pop(len(self.queue))
            except (ValueError, IndexError):
                log.write("[#8d8d99]Нечего убирать: /queue покажет очередь.[/]\n")
                return
            log.write(f"Убрал из очереди: {gone}\n")
            self.refresh_status("думает" if self.busy else "")
        elif word == "ladder":
            for i, r in enumerate(self.work.rungs):
                mark = "[b #4c8dff]▸[/]" if i == self.work.step else " "
                log.write(f"{mark} {r.label}")
            for r in self.work.skipped:
                log.write(f"[#8d8d99]  {r.label} — нечем войти[/]")
            log.write("")
        elif word == "up":
            self.work.step = 0
            log.write(f"Вернулся на {self.work.now.label}.\n")
            self.refresh_status()
        elif word == "new":
            self.work.sessions.clear()
            log.write("Разговор начат заново.\n")
        elif word == "model":
            if not rest:
                log.write("[#8d8d99]Какую модель? Например: /model opus[/]\n")
                return
            self.work.now.model = rest
            log.write(f"Модель на этой ступени: {rest}.\n")
            self.refresh_status()
        elif word == "night":
            import time

            from . import server
            hours = 8.0
            try:
                hours = float(rest) if rest else 8.0
            except ValueError:
                log.write("[#8d8d99]Сколько часов? Например: /night 8[/]\n")
                return
            self.cfg.setdefault("terminal", {})["unattended"] = True
            self.work.cfg = self.cfg
            self.work.wait_until = time.monotonic() + hours * 3600
            # «Уйти спать» — это не только «не засыпай»: он сказал прямо, что хочет включить и
            # лечь. Поэтому заодно режим сервера: экраны, звук, музыка. Вернёт их `/day`, выход из
            # окна или сторож через час после срока.
            if (self.cfg.get("terminal") or {}).get("night_server", True):
                self.dark = bool(server.on("ночная работа в оболочке",
                                           hours=hours + 1).get("ok"))
            if not self.dark:
                self.guard = self.guard or server.awake("ночная работа в оболочке")
            log.write(f"Ночь на {hours:g} ч: "
                      + ("экраны погасил, звук заглушил, " if self.dark else "")
                      + "машине не дам заснуть, кончатся все ступени — буду ждать возвращения "
                        "лимитов. Опасное при этом отклоняется, а не разрешается: спросить тебя "
                        "некого.\n")
            self.refresh_status()
        elif word == "day":
            self.release()
            self.cfg.setdefault("terminal", {})["unattended"] = False
            self.work.cfg, self.work.wait_until = self.cfg, 0.0
            log.write("Обычная работа: жду тебя рядом.\n")
            self.refresh_status()
        elif word == "effort":
            if rest not in ("low", "medium", "high"):
                log.write("[#8d8d99]Усилие: low, medium или high.[/]\n")
                return
            self.cfg.setdefault("terminal", {})["effort"] = rest
            log.write(f"Усилие: {rest}.\n")
        else:
            log.write(f"[#8d8d99]Нет такой команды: /{word}. /help — список.[/]\n")

    async def ask(self, text: str) -> None:
        log = self.query_one("#log", RichLog)
        try:
            said = await self.work.send(
                text,
                on_text=lambda t: log.write(t, expand=True),
                on_tool=lambda name: log.write(f"[#8d8d99]· {name}[/]"),
                on_note=lambda note: log.write(f"\n[#d4a72c]— {note}[/]\n"),
                on_pick=lambda rung, effort, why: self.refresh_status(f"думает {rung.label}"),
            )
            if said.error and not said.text:
                log.write(f"[#ff6b6b]Беда: {said.error}[/]")
        except Exception as e:                       # окно не должно падать из-за чужой программы
            log.write(f"[#ff6b6b]{type(e).__name__}: {e}[/]")
        finally:
            log.write("")
            self.busy = False
            self.refresh_status()
            # Следующую берём из `finally`, а не из конца `try`: упавший ход не должен хоронить
            # остальную очередь.
            if self.queue:
                self.start(self.queue.pop(0))


    def release(self) -> None:
        """Вернуть человеку машину: экраны, звук, музыку и право засыпать.

        Забыть про это — значит оставить тёмный экран и вечно бодрую машину после закрытого окна.
        """
        import contextlib
        import os
        if self.dark:
            from . import server
            with contextlib.suppress(Exception):
                server.off()
            self.dark = False
        if self.guard:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.kill(self.guard, 15)
            self.guard = 0

    def on_unmount(self) -> None:
        self.release()


def main() -> int:
    Shell().run()
    return 0
