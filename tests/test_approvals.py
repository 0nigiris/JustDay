"""Подтверждать опасное может только человек (Р-1 ревизии)."""

import asyncio
import os
import subprocess
import sys
import time
from pathlib import Path

from justday import providers
from justday.daemon import Daemon


def test_the_brain_could_not_press_yes_from_a_background_job(tmp_path):
    """`justday job start x -- "sleep 3; justday approve"` подтверждал опасную команду сам себе:
    задача — потомок демона, и её «да» по сокету должно отклоняться."""
    sock = str(tmp_path / "s")
    seen: list[bool] = []

    async def main():
        async def client(reader, writer):
            seen.append(Daemon._peer_is_ai(writer))
            writer.close()

        server = await asyncio.start_unix_server(client, path=sock)
        child = await asyncio.create_subprocess_exec(
            sys.executable, "-c", f"import socket; s = socket.socket(socket.AF_UNIX); s.connect({sock!r}); s.recv(1)")
        await child.wait()
        server.close()

    asyncio.run(main())
    assert seen == [True]


def test_another_ai_on_the_machine_could_not_approve_either(tmp_path):
    """Нейросеть в оболочке (`claude -p` из justday terminal) — не потомок демона, но тоже не человек."""
    fake = tmp_path / "claude"
    fake.symlink_to("/bin/sh")
    shell = subprocess.Popen([str(fake), "-c", "sleep 3; true"])
    try:
        kids = Path(f"/proc/{shell.pid}/task/{shell.pid}/children")
        for _ in range(50):
            if kids.read_text().split():
                break
            time.sleep(0.02)
        assert providers.spawned_by_ai(int(kids.read_text().split()[0]), daemon=-1)
    finally:
        shell.kill()
        shell.wait()


def test_the_island_and_the_persons_terminal_can_still_approve(monkeypatch):
    """Кнопка островка и `justday approve` из терминала человека — не потомки демона и не нейросети."""
    monkeypatch.setattr(providers, "AI_PROCESSES", set())
    assert not providers.spawned_by_ai(os.getpid(), daemon=-1)
