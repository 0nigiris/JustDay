"""Звонящий будильник пропадал с экрана от чужой карточки или «Отменить всё» — а звенеть продолжал."""
import asyncio
import types

from justday import daemon as daemon_mod
from justday.reminder_lane import ReminderMixin


async def _nothing(*a, **k):
    return None


def _fake(published):
    d = types.SimpleNamespace(
        _ringing="r1", _cancel_gen=0, _listen_cancel=None, _preapproved_until=0.0, _approval=None,
        _event_queue=asyncio.Queue(), brain=types.SimpleNamespace(interrupt=_nothing), side=None, state="",
        music=types.SimpleNamespace(duck=_nothing), stop_speaking=lambda: None, earcon=_nothing,
        publish=lambda **k: published.append(k), _reminders_state=lambda: [])
    d.dismiss_alarm = lambda rec_id="": ReminderMixin.dismiss_alarm(d, rec_id)
    return d


def test_cancel_everything_also_silences_the_alarm():
    published = []

    async def go():
        d = _fake(published)
        await daemon_mod.Daemon.cancel_all(d)
        await asyncio.sleep(0)
        return d

    d = asyncio.run(go())
    assert d._ringing == ""
    assert {"kind": "alarm_close"} in published


def test_dismissing_the_alarm_does_not_close_other_cards():
    """`card_close` закрыл бы и карточку разрешения, открытую в ту же минуту."""
    published = []

    async def go():
        _fake(published).dismiss_alarm("r1")
        await asyncio.sleep(0)

    asyncio.run(go())
    kinds = [p.get("kind") for p in published]
    assert "alarm_close" in kinds and "card_close" not in kinds
