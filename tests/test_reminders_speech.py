"""Будильник «как у колонки»: живые формулировки ставятся сразу, без нейросети и без мусора в названии."""
from datetime import datetime

import pytest

from justday import reminders


@pytest.mark.parametrize("phrase,hm", [
    ("включи-ка будильник на 18:30", "18:30"),
    ("поставь будильник на восемнадцать тридцать", "18:30"),
    ("включи будильник на 18 30", "18:30"),
    ("будильник на половину седьмого вечера", "18:30"),
    ("разбуди меня в полседьмого", "06:30"),
    ("будильник на без пятнадцати семь", "06:45"),
    ("будильник на 7", "07:00"),
])
def test_alarm_phrases_set_instantly(phrase, hm):
    r = reminders.parse(phrase)
    assert r and r["kind"] == "alarm"
    assert datetime.fromtimestamp(r["at"]).strftime("%H:%M") == hm
    assert r["label"] == ""      # «Ка будильник» и «30» раньше попадали в название


def test_timer_minutes_not_taken_for_clock():
    r = reminders.parse("поставь таймер на 5 минут")
    assert r and r["kind"] == "timer" and r["span"] == 300
