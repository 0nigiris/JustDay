"""«Успеете ли»: встреча в сорока минутах езды объявлялась за двадцать — выезжать было поздно (пункт 20, ступень 4)."""
import asyncio
import datetime as dt

from justday import geo, observer, telegram

NOW = dt.datetime(2026, 10, 5, 14, 0).astimezone()


def ev(minutes, title="Врач", location="Невский 1"):
    return {"title": title, "all_day": False, "location": location,
            "start": (NOW + dt.timedelta(minutes=minutes)).isoformat(), "end": "", "calendar": ""}


def run(items, tmp_path, travel, now=NOW, cfg=None):
    said: list[str] = []

    async def deliver(text):
        said.append(text)

    asyncio.run(observer.tick(lambda a, b: [e for e in items if a <= dt.datetime.fromisoformat(e["start"]) <= b],
                              deliver, cfg or {"user": {"address_as": "сэр"}}, now=now,
                              path=tmp_path / "o.json", travel=travel))
    return said


def test_a_far_meeting_is_announced_early_enough_to_leave(tmp_path) -> None:
    said = run([ev(50)], tmp_path, travel=lambda place: 40.0)
    assert said == ["сэр, «Врач» (Невский 1) в 14:50 — через 50 мин. Дорога займёт около 40 мин — пора выходить."]


def test_without_a_position_nothing_changes(tmp_path) -> None:
    assert run([ev(50)], tmp_path, travel=lambda place: None) == [], "без позиции раньше срока писать не о чем"
    assert len(run([ev(15)], tmp_path, travel=lambda place: None)) == 1


def test_it_says_plainly_when_he_will_not_make_it(tmp_path) -> None:
    said = run([ev(20)], tmp_path, travel=lambda place: 35.0)
    assert len(said) == 1 and "не успеваете" in said[0] and "перенесли" in said[0]


def test_a_meeting_without_a_place_gets_no_route_and_no_network(tmp_path) -> None:
    asked = []
    said = run([ev(15, location="")], tmp_path, travel=lambda place: asked.append(place))
    assert asked == [] and "Дорога" not in said[0]


def test_route_lookup_can_be_switched_off(tmp_path) -> None:
    asked = []
    said = run([ev(50)], tmp_path, travel=lambda p: asked.append(p) or 40.0, cfg={"observer": {"travel": False}})
    assert asked == [] and said == []


def test_a_stale_position_is_no_position(tmp_path) -> None:
    """Закрыл трансляцию в обед — вечером «вы в пути» по обеденной точке хуже молчания."""
    f = tmp_path / "loc.json"
    geo.remember(59.9, 30.3, now=1000.0, path=f)
    assert geo.here(now=1000.0 + 60, path=f) == (59.9, 30.3)
    assert geo.here(now=1000.0 + geo.FRESH_S + 1, path=f) is None
    assert oct(f.stat().st_mode & 0o777) == "0o600"


def test_a_strangers_location_never_moves_the_owner(monkeypatch) -> None:
    monkeypatch.setattr(telegram, "chat", lambda: "1370502385")
    mine = {"edited_message": {"chat": {"id": 1370502385}, "location": {"latitude": 59.9, "longitude": 30.3}}}
    other = {"message": {"chat": {"id": 999}, "location": {"latitude": 1.0, "longitude": 2.0}}}
    assert telegram.location(mine) == (59.9, 30.3), "живая геопозиция приходит правкой сообщения"
    assert telegram.location(other) is None and telegram.location({}) is None


def test_route_is_asked_once_in_five_minutes(monkeypatch) -> None:
    """Наблюдатель спрашивает раз в минуту, а публичный OSRM — общий: лишних запросов быть не должно."""
    calls = []
    geo._ROUTES.clear()
    monkeypatch.setattr(geo, "here", lambda now=None, path=None: (59.9, 30.3))
    monkeypatch.setattr(geo, "geocode", lambda place: (59.93, 30.36))
    monkeypatch.setattr(geo, "drive_minutes", lambda a, b: calls.append(1) or 25.0)
    assert geo.minutes_to("Невский 1", now=1000.0) == 25.0
    assert geo.minutes_to("Невский 1", now=1060.0) == 25.0 and len(calls) == 1
    assert geo.minutes_to("Невский 1", now=1400.0) == 25.0 and len(calls) == 2
    monkeypatch.setattr(geo, "here", lambda now=None, path=None: None)
    assert geo.minutes_to("Невский 1", now=1500.0) is None
