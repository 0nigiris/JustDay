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
  /compact       попросить сжать разговор
  /ladder        показать лестницу
  /up            вернуться на верхнюю ступень
  /new           начать разговор заново
  /help, /quit"""


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
        bits = [self.work.now.label, f"ступень {self.work.step + 1} из {len(self.work.rungs)}"]
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
        if text.startswith("/") and not text.startswith("/compact"):
            self.command(text)
            return
        if self.busy:
            log.write("[#8d8d99]Подожди: предыдущая задача ещё идёт.[/]")
            return
        log.write(f"[b #4c8dff]›[/] {text}\n")
        self.busy = True
        self.refresh_status("думает")
        self.turn = asyncio.create_task(self.ask(text))

    def command(self, line: str) -> None:
        log = self.query_one("#log", RichLog)
        word, _, rest = line[1:].partition(" ")
        rest = rest.strip()
        if word in ("quit", "exit", "q"):
            self.exit()
        elif word == "help":
            log.write(HELP + "\n")
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
            )
            if said.error and not said.text:
                log.write(f"[#ff6b6b]Беда: {said.error}[/]")
        except Exception as e:                       # окно не должно падать из-за чужой программы
            log.write(f"[#ff6b6b]{type(e).__name__}: {e}[/]")
        finally:
            log.write("")
            self.busy = False
            self.refresh_status()


def main() -> int:
    Shell().run()
    return 0
