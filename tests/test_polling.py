"""Р-36: опросы без нужды. Демон держал лишнюю работу, пока никто не смотрел и ничего не менялось:
монитор нагрузки просыпался каждую секунду без зрителей, проверка почты каждые три минуты заново
скачивала пять уже виденных писем, а каждое Ctrl+C запускало новый Python (`justday clip store`)."""
from __future__ import annotations

import asyncio
from types import SimpleNamespace

from justday import clipboard, events, mail
from justday.daemon import Daemon

# ───────────────────────────── монитор нагрузки ─────────────────────────────


def test_load_monitor_sleeps_until_someone_watches() -> None:
    """Без зрителей цикл не снимает цифры и не просыпается; открыли монитор — снимает сразу."""
    taken: list[int] = []

    async def snapshot() -> dict:
        taken.append(1)
        return {}

    async def scenario() -> tuple[int, int]:
        d = Daemon.__new__(Daemon)
        d.load_watchers, d._load_wake = 0, asyncio.Event()
        d.load_snapshot, d.publish = snapshot, lambda **kw: None
        loop = asyncio.create_task(d._load_loop())
        await asyncio.sleep(0.15)
        idle = len(taken)
        await d._cmd_load_watch({"on": True}, None)
        await asyncio.sleep(0.15)
        loop.cancel()
        return idle, len(taken)

    idle, watched = asyncio.run(scenario())
    assert idle == 0 and watched >= 1


# ───────────────────────────── почта ─────────────────────────────


class _Box:
    """Почтовый ящик, который помнит, какие письма у него скачали."""
    def __init__(self) -> None:
        self.fetched: list[bytes] = []

    def select(self, *a, **k):
        return "OK", []

    def uid(self, command, uid, *rest):
        self.fetched.append(uid)
        raw = b"From: Anna <anna@example.com>\r\nSubject: Hi\r\n\r\nbody"
        return "OK", [(b"1 (BODY[])", raw), b")"]

    def logout(self):
        pass


def test_mail_check_downloads_only_letters_newer_than_seen(monkeypatch, state_dir) -> None:
    monkeypatch.setattr(events.config, "STATE_FILE", state_dir / "state.json")   # настоящее состояние не трогать
    box = _Box()
    monkeypatch.setattr(mail, "_imap", lambda: box)
    monkeypatch.setattr(mail, "_search", lambda *_: [b"%d" % n for n in range(1, 10)])
    monkeypatch.setattr(mail.config, "load", lambda: {"mail": {"query": "is:unread"}, "user": {}})
    events.save_state(mail_last_uid=7)
    me = SimpleNamespace(letters=[], active_until=0.0)
    said = mail.MailAssistant.check_new(me)
    assert box.fetched == [b"9", b"8"]          # 1–7 уже виденные: их не качаем
    assert "Anna" in said and events.load_state()["mail_last_uid"] == 9


def test_mail_check_with_nothing_new_downloads_nothing(monkeypatch, state_dir) -> None:
    monkeypatch.setattr(events.config, "STATE_FILE", state_dir / "state.json")
    box = _Box()
    monkeypatch.setattr(mail, "_imap", lambda: box)
    monkeypatch.setattr(mail, "_search", lambda *_: [b"1", b"2", b"3"])
    monkeypatch.setattr(mail.config, "load", lambda: {"mail": {"query": "is:unread"}, "user": {}})
    events.save_state(mail_last_uid=3)
    assert mail.MailAssistant.check_new(SimpleNamespace(letters=[], active_until=0.0)) == ""
    assert box.fetched == []


# ───────────────────────────── буфер обмена ─────────────────────────────


class _Pipe:
    def __init__(self, *chunks: bytes) -> None:
        self.chunks = list(chunks)

    async def read(self, _n: int) -> bytes:
        return self.chunks.pop(0) if self.chunks else b""


def _drain(pipe: _Pipe, **kw) -> list[bytes]:
    async def go() -> list[bytes]:
        return [r async for r in clipboard.records(pipe, **kw)]
    return asyncio.run(go())


def test_clipboard_copies_survive_being_split_across_reads() -> None:
    """Труба отдаёт куски как попало: копирование, разрезанное на два чтения, не должно стать двумя записями."""
    assert _drain(_Pipe(b"one\0tw", b"o\0thr", b"ee\0")) == [b"one", b"two", b"three"]


def test_an_oversized_copy_is_dropped_whole_not_kept_in_memory() -> None:
    got = _drain(_Pipe(b"x" * 50, b"x" * 50, b"\0ok\0"), limit=60)
    assert got == [b"ok"]


def test_secret_hint_from_a_password_manager_is_not_remembered(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(clipboard, "is_secret_hint", lambda: True)
    stored: list = []
    monkeypatch.setattr(clipboard, "store", lambda *a, **k: stored.append(a) or {"ok": True})
    assert clipboard.store_watched(b"hunter2")["ok"] is False and stored == []
    monkeypatch.setattr(clipboard, "is_secret_hint", lambda: False)
    clipboard.store_watched("привет".encode())
    assert stored == [("привет",)]
