import datetime as dt

from justday import initiative


def test_initiative_silent_by_default_and_at_night():
    """Пустые реплики его злят: на нуле молчит всегда, и ночью молчит на любом уровне."""
    day = dt.datetime(2026, 11, 12, 15, 0)
    assert not initiative.due(0, 10_000, day)
    assert not initiative.due(3, 10_000, dt.datetime(2026, 11, 12, 2, 0))
    assert not initiative.due(1, 60, day)           # раз в три часа — не через час
    assert initiative.due(1, 181, day)
    assert initiative.due(3, 21, day)
