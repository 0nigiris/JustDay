"""Fire-and-forget tasks that neither vanish nor fail silently.

The event loop keeps only a weak reference to a task: one nobody holds can be garbage-collected mid-way, and
its crash surfaces (if ever) as «Task exception was never retrieved» long after. spawn() holds it until it
ends and logs a crash at once, with the traceback.
"""
from __future__ import annotations

import asyncio
import logging
from collections.abc import Coroutine

log = logging.getLogger("justday")
_live: set[asyncio.Task] = set()


def spawn(coro: Coroutine, name: str | None = None) -> asyncio.Task:
    task = asyncio.create_task(coro, name=name)
    _live.add(task)
    task.add_done_callback(_done)
    return task


def _done(task: asyncio.Task) -> None:
    _live.discard(task)
    if not task.cancelled() and (exc := task.exception()):
        log.error("task %s failed", task.get_name(), exc_info=exc)


def die_with_daemon() -> None:
    """`preexec_fn` для долгих помощников демона (dbus-monitor, journalctl -f, wl-paste --watch).

    Служба живёт с `KillMode=process`, чтобы запущенные ассистентом программы пережили перезапуск, —
    поэтому systemd не трогает и помощников. Убивать их руками при остановке ненадёжно: про двух
    забыли, а при падении до этого кода не доходит вовсе, и за сутки набралось 97 сирот dbus-monitor.
    Ядро само пошлёт SIGTERM, когда умрёт поток демона, их запустивший (цикл asyncio — главный поток)."""
    import ctypes
    import signal

    ctypes.CDLL(None, use_errno=True).prctl(1, signal.SIGTERM)    # PR_SET_PDEATHSIG
