"""Джарвис замолкал до перезапуска: ожидания без срока в мозге, распознавании и воспроизведении."""
import asyncio
import time

import numpy as np
import pytest

from justday import audio, brain
from justday.aio import blocking


def test_silent_claude_code_ends_the_turn_instead_of_hanging_forever(monkeypatch):
    """Беда: Claude Code переставал отвечать, не умирая, и ход не кончался — каждая новая фраза
    падала в мёртвый ход. Теперь тишина дольше срока кончает ход ошибкой."""
    monkeypatch.setattr(brain, "STALL_POLL_S", 0.01)
    b = object.__new__(brain.Brain)
    b.cfg = {"brain": {"stall_seconds": 0.05}}
    b._turn_done = asyncio.Event()
    b._tool_since = None
    b._error = ""
    b._last_msg = time.monotonic()
    stopped = []

    async def stop():
        stopped.append(True)
    b.stop = stop
    asyncio.run(asyncio.wait_for(b._await_turn(), 2))
    assert stopped and b._error.startswith("нет ответа")


def test_stuck_thread_call_gives_up_instead_of_holding_the_state():
    """Беда: распознавание, повисшее на видеокарте, держало «transcribing» навсегда."""
    with pytest.raises(TimeoutError):
        asyncio.run(blocking(time.sleep, 1, timeout=0.05))


def test_hung_player_is_killed_and_speech_goes_on(monkeypatch):
    """Беда: pw-play, потерявший устройство после сна, не выходил, и очередь речи стояла."""
    monkeypatch.setattr(audio, "PLAY_SLACK_S", 0.2)
    p = audio.Player()
    p._cmd = lambda rate: ["sleep", "30"]
    t = time.monotonic()
    asyncio.run(p.play(np.zeros(160, dtype=np.int16), 16000))
    assert time.monotonic() - t < 5
