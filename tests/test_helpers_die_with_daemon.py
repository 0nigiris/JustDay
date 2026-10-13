"""Каждый перезапуск демона оставлял двух сирот dbus-monitor: за сутки их набралось 97."""
import os
import signal
import subprocess
import sys
import time

PARENT = """
import asyncio, sys
from justday.aio import die_with_daemon

async def main():
    p = await asyncio.create_subprocess_exec("sleep", "60", preexec_fn=die_with_daemon)
    print(p.pid, flush=True)
    await asyncio.sleep(60)

asyncio.run(main())
"""


def _alive(pid: int) -> bool:
    try:
        with open(f"/proc/{pid}/stat") as f:
            return f.read().split(")")[-1].split()[0] != "Z"
    except FileNotFoundError:
        return False


def test_a_helper_dies_when_the_daemon_is_killed_without_cleanup():
    """SIGKILL — как падение: до кода, гасящего помощников, демон не доходит."""
    parent = subprocess.Popen([sys.executable, "-c", PARENT], stdout=subprocess.PIPE, text=True)
    child = int(parent.stdout.readline())
    try:
        assert _alive(child)
        parent.send_signal(signal.SIGKILL)
        parent.wait()
        for _ in range(50):
            if not _alive(child):
                break
            time.sleep(0.05)
        assert not _alive(child)
    finally:
        if _alive(child):
            os.kill(child, signal.SIGKILL)
