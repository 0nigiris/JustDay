"""Мгновенный путь про таймеры не должен перехватывать обычный разговор."""
from justday import reminders


def test_ordinary_request_with_remind_goes_to_the_brain():
    # «напомни… что осталось» — просьба рассказать, а не спросить список таймеров
    assert reminders.parse("Напомни мне, пожалуйста, что мне осталось сделать по технологии.") is None
    assert reminders.parse("Напомни-ка, а что мне там осталось сделать самому?") is None
    assert reminders.parse("напомни, сколько мне лет") is None
    assert reminders.parse("напомни что я хотел купить") is None


def test_list_needs_the_thing_named():
    for text in ("сколько осталось на таймере", "сколько там до будильника",
                 "какие у меня напоминания", "покажи мои таймеры"):
        assert reminders.parse(text) == {"action": "list"}, text


def test_setting_still_works():
    got = reminders.parse("напомни в 7 утра позвонить маме")
    assert got and got["action"] == "set" and got["kind"] == "reminder"
    assert reminders.parse("поставь таймер на 5 минут")["kind"] == "timer"
    assert reminders.parse("разбуди в 7:30")["kind"] == "alarm"


def test_cancel_still_works():
    got = reminders.parse("отмени будильник")
    assert got and got["action"] == "cancel"


def test_moscow_time_becomes_madrid_time(monkeypatch):
    """10 нояб.: «будильник на 20:30 по МСК» встал на 20:30 по Мадриду с названием «По МСК»."""
    import os
    import time as _t
    from datetime import datetime
    from zoneinfo import ZoneInfo
    monkeypatch.setenv("TZ", "Europe/Madrid")
    _t.tzset()
    try:
        got = reminders.parse("Поставь будильник на 20-30 по МСК.")
        local = datetime.fromtimestamp(got["at"], ZoneInfo("Europe/Madrid"))
        msk = datetime.fromtimestamp(got["at"], ZoneInfo("Europe/Moscow"))
        assert (msk.hour, msk.minute) == (20, 30)
        assert (local.hour, local.minute) in ((18, 30), (19, 30))   # зима / лето
        assert got["label"] == ""
        plain = reminders.parse("разбуди в 7:30")
        assert datetime.fromtimestamp(plain["at"]).hour == 7
    finally:
        monkeypatch.delenv("TZ")
        os.environ.pop("TZ", None)
        _t.tzset()
