"""Background jobs: long commands that must not hold the assistant hostage.

«Обнови систему» takes minutes; «включи музыку» said in the meantime must not wait for it. So the
brain starts anything long as a job and ends its turn at once: the command runs here, in the daemon,
with its output in a log; the island shows it, and when it ends the brain gets an event and reports.

A job runs in its own process group, so «стоп» for it stops the whole command, sudo helpers included.
"""
from __future__ import annotations

import asyncio
import os
import signal
import time
import uuid
from collections.abc import Callable

from . import config

DIR = config.STATE_DIR / "jobs"


class Jobs:
    def __init__(self, on_change: Callable[[], None], on_done: Callable[[dict], None]):
        self.items: dict[str, dict] = {}
        self._procs: dict[str, asyncio.subprocess.Process] = {}
        self.on_change = on_change
        self.on_done = on_done

    def state(self) -> list[dict]:
        """For the island: what runs (and what ended in the last minute), newest first."""
        now = time.time()
        keep = [j for j in self.items.values() if j["state"] == "running" or now - j.get("ended", now) < 60]
        return [{k: j[k] for k in ("id", "title", "state", "started", "ended", "code") if k in j}
                for j in sorted(keep, key=lambda j: -j["started"])]

    async def start(self, title: str, command: str, cwd: str = "") -> dict:
        DIR.mkdir(parents=True, exist_ok=True)
        jid = uuid.uuid4().hex[:6]
        log_path = DIR / f"{jid}.log"
        log = open(log_path, "wb")  # noqa: SIM115 — handed to the child, closed when it ends
        proc = await asyncio.create_subprocess_exec(
            "bash", "-lc", command, cwd=cwd or os.path.expanduser("~"), stdin=asyncio.subprocess.DEVNULL,
            stdout=log, stderr=asyncio.subprocess.STDOUT, start_new_session=True)
        job = {"id": jid, "title": title.strip() or command[:60], "command": command, "cwd": cwd,
               "state": "running", "started": time.time(), "log": str(log_path), "pid": proc.pid}
        self.items[jid] = job
        self._procs[jid] = proc
        asyncio.create_task(self._watch(jid, proc, log))
        self.on_change()
        return job

    async def _watch(self, jid: str, proc: asyncio.subprocess.Process, log) -> None:
        code = await proc.wait()
        log.close()
        job = self.items[jid]
        if job["state"] == "running":
            job["state"] = "done" if code == 0 else "failed"
        job.update(code=code, ended=time.time())
        self._procs.pop(jid, None)
        self.on_change()
        self.on_done(job)

    def stop(self, jid: str) -> bool:
        proc = self._procs.get(jid)
        if not proc or proc.returncode is not None:
            return False
        self.items[jid]["state"] = "stopped"
        try:
            os.killpg(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            return False
        return True

    def tail(self, jid: str, lines: int = 15) -> str:
        job = self.items.get(jid)
        if not job:
            return ""
        try:
            text = open(job["log"], encoding="utf-8", errors="replace").read()
        except OSError:
            return ""
        # progress bars rewrite one line with \r: only the last state of each line is worth reading
        out = [ln.rsplit("\r", 1)[-1] for ln in text.splitlines()]
        return "\n".join([ln for ln in out if ln.strip()][-lines:])

    @property
    def running(self) -> list[dict]:
        return [j for j in self.items.values() if j["state"] == "running"]
