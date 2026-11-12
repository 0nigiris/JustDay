"""П20: зависший островок или демон висел до ручного перезапуска, а флеш потом говорил безликое «после сбоя»."""
import socket

from justday import crashlog, daemon


def test_frozen_island_is_noticed_but_sleep_is_not_a_hang():
    now = 10_000.0
    assert daemon.ui_hung(now - 200, now, slept=False, after=120)      # замёрз
    assert not daemon.ui_hung(now - 60, now, slept=False, after=120)   # просто таймер ещё не тикнул
    assert not daemon.ui_hung(now - 600, now, slept=True, after=120)   # машина спала — стояли все
    assert not daemon.ui_hung(0, now, slept=False, after=120)          # островка в этом сеансе нет


def test_flash_names_who_hung(tmp_path, monkeypatch):
    monkeypatch.setattr(crashlog, "DIR", tmp_path)
    assert crashlog.latest() == {}
    crashlog.save("justday.service", "watchdog")
    assert crashlog.latest() == {"who": "daemon", "hung": True}
    (tmp_path / "99999999-999999-qs-x.log").write_text("служба: quickshell (упал и поднялся сам)\n")
    assert crashlog.latest() == {"who": "ui", "hung": False}


def test_watchdog_ping_reaches_systemd(tmp_path, monkeypatch):
    path = tmp_path / "notify"
    with socket.socket(socket.AF_UNIX, socket.SOCK_DGRAM) as s:
        s.bind(str(path))
        monkeypatch.setenv("NOTIFY_SOCKET", str(path))
        daemon.sd_notify("WATCHDOG=1")
        assert s.recv(64) == b"WATCHDOG=1"
