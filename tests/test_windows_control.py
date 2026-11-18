"""На Windows демон слушает TCP-порт на 127.0.0.1, а его видят все процессы машины.

Без токена любая программа на компьютере могла бы велеть Джарвису что угодно; токен лежит в
профиле человека, и демон обрывает тех, кто его не прислал первой строкой."""
import asyncio
import json
import socket
from types import SimpleNamespace

from justday import config
from justday.daemon import Daemon


def test_a_stranger_without_the_token_cannot_command_jarvis(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "TOKEN_FILE", tmp_path / "control.token")
    monkeypatch.setattr(config, "CONTROL_PORT", 0)
    heard = []

    async def client(reader, writer):
        heard.append(json.loads(await reader.readline()))
        writer.write(b'{"ok": true}\n')
        await writer.drain()
        writer.close()

    async def main():
        server = await Daemon._serve_tcp(SimpleNamespace(_client=client))
        port = server.sockets[0].getsockname()[1]
        assert server.sockets[0].getsockname()[0] == "127.0.0.1"
        loop = asyncio.get_running_loop()

        def stranger():
            with socket.create_connection(("127.0.0.1", port), timeout=5) as s:
                s.sendall(b'{"cmd": "say"}\n')
                return s.recv(100)

        def owner():
            monkeypatch.setattr(config, "WINDOWS", True)
            monkeypatch.setattr(config, "CONTROL_PORT", port)
            with config.control_socket(5) as s:
                s.sendall(b'{"cmd": "status"}\n')
                return s.recv(100)

        assert await loop.run_in_executor(None, stranger) == b""
        assert await loop.run_in_executor(None, owner) == b'{"ok": true}\n'
        server.close()

    asyncio.run(main())
    assert heard == [{"cmd": "status"}]
