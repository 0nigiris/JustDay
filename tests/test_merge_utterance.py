"""Говорил «найди идеи для Майнкрафта», пока мозг думал, добавил «и ещё постройки» — раньше вторая
фраза уходила отдельным сообщением к недодуманному ответу. Теперь это одна просьба."""
import asyncio
from types import SimpleNamespace

from justday import daemon


class Brain:
    def __init__(self, mergeable):
        self.busy, self.mergeable, self.interrupted, self.injected = True, mergeable, False, []

    def can_merge(self):
        return self.mergeable

    async def interrupt(self):
        self.interrupted = True

    async def inject(self, text, source):
        self.injected.append(text)

    def waiting_on_tool(self):
        return 0


def _daemon(mergeable):
    ran = []

    async def run_turn(text, source):
        ran.append(text)

    async def local(text, source):
        return None

    d = SimpleNamespace(_approval=None, _cancel_gen=0, _turn_text="идеи для Майнкрафта", brain=Brain(mergeable),
                        handle_local=local, run_turn=run_turn, music=SimpleNamespace(playing=False))
    return d, ran


def _say(d, text):
    async def go():
        await daemon.Daemon.handle_utterance(d, text)
        await asyncio.sleep(0)
    asyncio.run(go())


def test_молчащий_мозг_получает_обе_фразы_одной_просьбой():
    d, ran = _daemon(True)
    _say(d, "и ещё постройки")
    assert ran == ["идеи для Майнкрафта и ещё постройки"]
    assert d.brain.interrupted and d._cancel_gen == 1 and not d.brain.injected


def test_мозг_уже_работает_руками_фраза_не_склеивается():
    d, ran = _daemon(False)
    _say(d, "и ещё постройки")
    assert ran == [] and d.brain.injected == ["и ещё постройки"] and not d.brain.interrupted
