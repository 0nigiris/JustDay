"""Наблюдатель пишет первым — и только по делу (пункт 20 плана)."""
import asyncio
import datetime as dt

from justday import observer

NOW = dt.datetime(2026, 10, 5, 14, 0).astimezone()


def ev(minutes: int, title="Встреча с Ильёй", all_day=False, location=""):
    return {"title": title, "all_day": all_day, "location": location,
            "start": (NOW + dt.timedelta(minutes=minutes)).isoformat(), "end": "", "calendar": ""}


def run(items, tmp_path, cfg=None, now=NOW):
    said: list[str] = []

    async def deliver(text):
        said.append(text)

    got = asyncio.run(observer.tick(lambda a, b: items, deliver, cfg or {"user": {"address_as": "сэр"}}, now=now,
                                    path=tmp_path / "observer.json"))
    return said, got


def test_he_was_told_about_the_meeting_twenty_minutes_ahead_and_only_once(tmp_path) -> None:
    """«Сэр, у вас встреча через 20 минут» — главный пример из его задания; но не раз в минуту до самой встречи."""
    said, _ = run([ev(18, location="кафе")], tmp_path)
    assert said == ["сэр, «Встреча с Ильёй» (кафе) в 14:18 — через 18 мин."]
    again, _ = run([ev(18, location="кафе")], tmp_path, now=NOW + dt.timedelta(minutes=1))
    assert again == [], "то же напоминание повторено через минуту"


def test_the_observer_kept_silent_when_there_was_nothing_to_say(tmp_path) -> None:
    """По умолчанию молчит почти всегда: далёкое, уже начавшееся и событие на весь день — не повод."""
    items = [ev(90, "позже"), ev(-5, "уже идёт"), ev(0, "прямо сейчас"), ev(10, "праздник", all_day=True)]
    assert run(items, tmp_path)[0] == []


def test_a_restart_did_not_repeat_what_was_already_said(tmp_path) -> None:
    run([ev(15)], tmp_path)
    assert run([ev(15)], tmp_path, now=NOW + dt.timedelta(minutes=1))[0] == [], "после перезапуска демона напоминание ушло второй раз"


def test_three_meetings_in_a_row_were_not_three_messages_a_minute(tmp_path) -> None:
    items = [ev(5, "а"), ev(8, "б"), ev(11, "в"), ev(14, "г")]
    assert len(run(items, tmp_path)[0]) == observer.MAX_PER_TICK


def test_the_observer_can_be_switched_off(tmp_path) -> None:
    assert run([ev(10)], tmp_path, cfg={"observer": {"enabled": False}})[0] == []
