"""Кнопки «Обновить», «Установить голос», «Журнал» звали `kitty --hold …` прямо из QML: без kitty они молча не
делали ничего. Теперь терминал выбирает демон, а из сокета принимается только имя действия — не команда: сокетом
пользуется и мозг, и произвольный запуск обходил бы его запреты."""
from __future__ import annotations

import asyncio
import json

from justday import desktop
from justday.daemon import Daemon


def _only(monkeypatch, *present: str) -> None:
    monkeypatch.delenv("TERMINAL", raising=False)
    monkeypatch.setattr(desktop.shutil, "which", lambda n: f"/usr/bin/{n}" if n in present else None)


def test_without_kitty_the_next_known_terminal_is_used(monkeypatch) -> None:
    _only(monkeypatch, "konsole")
    cmd = desktop.terminal_command(["justday", "update"])
    assert cmd[:2] == ["/usr/bin/konsole", "-e"] and cmd[-2:] == ["justday", "update"]


def test_holding_waits_for_enter_so_the_output_can_be_read(monkeypatch) -> None:
    _only(monkeypatch, "kitty")
    assert any("read" in a for a in desktop.terminal_command(["justday", "update"]))
    assert desktop.terminal_command(["justday", "logs", "-f"], hold=False) == ["/usr/bin/kitty", "justday", "logs", "-f"]


def test_no_terminal_at_all_is_reported_not_crashed(monkeypatch) -> None:
    _only(monkeypatch)
    assert desktop.terminal_command(["justday", "update"]) is None


def _ask(request: dict, human: bool) -> dict:
    class Reader:
        async def readline(self):
            return json.dumps(request).encode()

    class Writer:
        data = b""

        def write(self, b):
            self.data += b

        async def drain(self):
            pass

        def close(self):
            pass

        def get_extra_info(self, _name):
            return None

    d = Daemon.__new__(Daemon)
    d._peer_is_ai = lambda _w: not human
    w = Writer()
    asyncio.run(d._client(Reader(), w))
    return json.loads(w.data)


def test_only_known_actions_open_a_terminal(monkeypatch) -> None:
    _only(monkeypatch, "kitty")
    started: list = []
    monkeypatch.setattr("justday.commands.subprocess.Popen", lambda argv, **kw: started.append(argv))
    got = _ask({"cmd": "terminal_run", "what": "rm -rf ~"}, human=True)
    assert got["ok"] is False and started == []
    assert _ask({"cmd": "terminal_run", "what": "update"}, human=True)["ok"] is True
    assert started and "update" in started[0]


def test_the_brain_cannot_open_a_terminal_through_the_socket(monkeypatch) -> None:
    _only(monkeypatch, "kitty")
    started: list = []
    monkeypatch.setattr("justday.commands.subprocess.Popen", lambda argv, **kw: started.append(argv))
    assert _ask({"cmd": "terminal_run", "what": "update"}, human=False)["ok"] is False and started == []
