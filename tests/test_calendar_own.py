"""Свой календарь: Джарвис записывает встречу без аккаунтов, читает её обратно и не плодит дубли."""
import datetime as dt

from justday import calendar_lane


def test_add_then_read_back_without_duplicates(tmp_path, monkeypatch):
    monkeypatch.setattr(calendar_lane, "LOCAL", tmp_path / "calendar.ics")
    monkeypatch.setattr(calendar_lane, "urls", lambda: [])
    start = calendar_lane.parse_start("2026-11-07 15:00")
    assert calendar_lane.add("Встреча с Игорем", start)["ok"]
    assert calendar_lane.add("Встреча с Игорем", start)["duplicate"]
    found = calendar_lane.between(start - dt.timedelta(hours=1), start + dt.timedelta(hours=2))
    assert [e["title"] for e in found] == ["Встреча с Игорем"]
    assert calendar_lane.active()


def test_forget_does_not_touch_own_calendar(tmp_path, monkeypatch):
    """Забыть чужие ленты можно, а встречи, записанные самим человеком, терять нельзя."""
    monkeypatch.setattr(calendar_lane, "LOCAL", tmp_path / "calendar.ics")
    monkeypatch.setattr(calendar_lane.subprocess, "run", lambda *a, **k: None)
    calendar_lane.add("Встреча", calendar_lane.parse_start("2026-11-07 15:00"))
    calendar_lane.forget()
    assert calendar_lane.LOCAL.exists()
