"""Диспетчер сокета (Р-80): раньше `_client` был цепочкой `elif cmd == …`, теперь это таблица `{команда: метод}`.
Беда такой таблицы — команда, которую шлёт островок или `justday …`, но для которой в таблице нет метода:
кнопка молча получает «unknown command». Поэтому сверяем то, что реально шлют клиенты, с таблицей."""
from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path

from justday.daemon import Daemon

ROOT = Path(__file__).resolve().parent.parent


def _sent_by_clients() -> set[str]:
    sent: set[str] = set()
    for qml in (ROOT / "island").glob("*.qml"):
        sent |= set(re.findall(r'\bcmd: ?"([a-z_]+)"', qml.read_text()))
    for py in (ROOT / "src" / "justday").glob("*.py"):
        sent |= set(re.findall(r'\bcontrol\(\s*"([a-z_]+)"', py.read_text()))
    return sent


def test_every_command_the_clients_send_has_a_handler() -> None:
    missing = _sent_by_clients() - set(Daemon.COMMANDS) - {"subscribe"}
    assert not missing, f"островок или CLI шлют команды без обработчика: {sorted(missing)}"


def test_the_table_points_at_real_methods() -> None:
    assert len(Daemon.COMMANDS) > 80
    for cmd, name in Daemon.COMMANDS.items():
        assert name == f"_cmd_{cmd}" and callable(getattr(Daemon, name)), cmd


def _ask_socket(d: Daemon, request: dict) -> dict:
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
            return None  # собеседника не узнали → _peer_is_ai считает его ИИ

    w = Writer()
    asyncio.run(d._client(Reader(), w))
    return json.loads(w.data)


def test_unknown_command_is_an_error_not_a_crash() -> None:
    assert _ask_socket(Daemon.__new__(Daemon), {"cmd": "no_such"})["ok"] is False


def test_an_unrecognised_peer_cannot_approve() -> None:
    """Р-1: мозг не должен нажимать «разрешить» сам; не узнали собеседника — значит нельзя. Остаётся так же
    и после переезда команды в отдельный обработчик."""
    d = Daemon.__new__(Daemon)
    d._approval = asyncio.new_event_loop().create_future()
    for cmd in ("approve", "answer"):
        got = _ask_socket(d, {"cmd": cmd, "value": "x"})
        assert got["ok"] is False and "только человек" in got["error"]
    assert not d._approval.done()
