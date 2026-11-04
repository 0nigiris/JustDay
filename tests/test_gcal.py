"""Запись встреч: без слова человека в календарь ничего не уходит, а время без пояса не уезжает на другие часы."""
import datetime as dt

from justday import gcal


def test_start_without_zone_gets_local_zone():
    when = gcal.parse_start("2026-11-07 15:00")
    assert when.tzinfo is not None and when.hour == 15


def test_preview_has_end_and_does_not_touch_network():
    p = gcal.preview("  Встреча ", gcal.parse_start("2026-11-07T15:00"), 90)
    assert p["title"] == "Встреча"
    assert dt.datetime.fromisoformat(p["end"]) - dt.datetime.fromisoformat(p["start"]) == dt.timedelta(minutes=90)
