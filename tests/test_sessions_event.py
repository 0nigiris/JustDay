"""Р-45: страница «Сессии» каждые две секунды заставляла демон запускать `claude agents --json` и читать хвосты
всех стенограмм, даже когда ничего не менялось. Теперь список собирается, только пока страницу смотрят и только
когда стенограммы изменились (или прошла контрольная пауза — ушедшая сессия стенограмму не трогает)."""
from __future__ import annotations

import asyncio
import time

from justday import sessions
from justday.daemon import Daemon


def test_fingerprint_changes_when_a_session_writes_or_appears(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(sessions, "HOME", tmp_path)
    proj = tmp_path / ".claude" / "projects" / "p"
    proj.mkdir(parents=True)
    assert sessions.fingerprint() == (0, 0)
    (proj / "a.jsonl").write_text("{}\n")
    first = sessions.fingerprint()
    time.sleep(0.01)
    (proj / "a.jsonl").write_text("{}\n{}\n")
    assert sessions.fingerprint() != first                      # сессия что-то сделала
    (proj / "b.jsonl").write_text("{}\n")
    assert sessions.fingerprint()[0] == 2                       # появилась новая


def _daemon(monkeypatch, fingerprints: list, published: list) -> Daemon:
    d = Daemon.__new__(Daemon)
    d.cfg = {"brain": {}}
    d._sessions_until, d._sessions_wake = 0.0, asyncio.Event()
    d.SESSIONS_TICK, d.SESSIONS_HEARTBEAT = 0.01, 1000.0
    d.publish = lambda **kw: published.append(kw)
    monkeypatch.setattr(sessions, "fingerprint", lambda: fingerprints[0])
    monkeypatch.setattr(sessions, "live", lambda *_: [{"id": "s1"}])
    return d


def test_the_list_is_built_only_for_a_viewer_and_only_on_change(monkeypatch) -> None:
    published: list = []
    fingerprints = [(1, 1)]
    d = _daemon(monkeypatch, fingerprints, published)

    async def scenario() -> tuple[int, ...]:
        task = asyncio.create_task(d._sessions_loop())
        await asyncio.sleep(0.1)
        nobody = len(published)                                  # страницу никто не смотрит
        d._sessions_until = time.monotonic() + 45
        d._sessions_wake.set()
        await asyncio.sleep(0.1)
        first = len(published)                                   # открыли — список пришёл сразу
        await asyncio.sleep(0.1)
        quiet = len(published)                                   # ничего не менялось — тишина
        fingerprints[0] = (1, 2)
        await asyncio.sleep(0.1)
        task.cancel()
        return nobody, first, quiet, len(published)

    nobody, first, quiet, changed = asyncio.run(scenario())
    assert (nobody, first, quiet, changed) == (0, 1, 1, 2)
