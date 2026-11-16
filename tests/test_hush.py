"""«Замолчи» на один ответ: голос молчит до конца этого хода, а не навсегда (16 нояб.)."""
import asyncio
from types import SimpleNamespace

from justday.commands import CommandsMixin
from justday.daemon import Daemon


def test_hush_silences_only_this_answer():
    d = SimpleNamespace(cfg={"tts": {"engine": "silero"}, "focus": {}}, stopped=0)
    d.stop_speaking = lambda: setattr(d, "stopped", d.stopped + 1)
    asyncio.run(CommandsMixin._cmd_hush(d, {}, None))
    assert d.stopped == 1
    assert Daemon.silent(d) == "hush"
    d._hushed = False   # так run_turn начинает следующий ход
    assert Daemon.silent(d) != "hush"
