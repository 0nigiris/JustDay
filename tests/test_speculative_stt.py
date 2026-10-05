"""Раннее распознавание: текст готов к концу паузы, но не годится, если человек успел заговорить снова."""
import asyncio

import numpy as np

from justday import audio

FRAME = audio.FRAME


class FakeMic:
    seq = 0

    def __init__(self, probs):
        self.probs = probs

    def subscribe(self, cb):
        for i in range(len(self.probs)):
            self.seq = i
            cb(np.full(FRAME, i + 1, dtype=np.int16))

    def unsubscribe(self, cb):
        pass


class FakeVad:
    def __init__(self, probs):
        self.probs = iter(probs)

    def reset_states(self):
        pass

    def predict(self, frame, frame_size=0):
        return next(self.probs)


def record(pattern, speculate_after=0.45):
    """pattern — строка из «s» (речь) и «.» (тишина), по кадру (80 мс) на знак."""
    probs = [0.9 if c == "s" else 0.0 for c in pattern]
    rec = audio.UtteranceRecorder(FakeMic(probs), 1.0, 7, 40, 2.2, 5.0, speculate_after)
    rec._vad = FakeVad(probs)
    sent = []

    async def run():
        cancel = asyncio.Event()
        # Запись, которую оборвали посреди речи, сама не кончится: тишины в конце нет, поэтому её останавливают кнопкой.
        asyncio.get_running_loop().call_later(0.3, cancel.set)
        return await rec.record(cancel, speculate=lambda p: sent.append(len(p)))

    return rec, asyncio.run(run()), sent


def test_recognition_starts_in_the_middle_of_the_wait_and_stays_valid():
    rec, pcm, sent = record("s" * 8 + "." * 15)
    assert len(sent) == 1
    assert rec.speculated is not None and len(rec.speculated) == sent[0] < len(pcm)


def test_he_spoke_again_so_the_early_text_is_thrown_away():
    """«включи музыку … пожалуйста»: пауза в полсекунды, продолжение — готовый текст неполный."""
    rec, _, sent = record("s" * 8 + "." * 8 + "s" * 8 + "." * 15)
    assert len(sent) == 2 and sent[0] < sent[1]
    assert len(rec.speculated) == sent[1]  # годится только второй, свежий


def test_he_spoke_again_after_the_last_speculation_leaves_nothing_valid():
    rec, _, sent = record("s" * 8 + "." * 8 + "s" * 5 + "." * 15)
    assert rec.speculated is not None and len(rec.speculated) == sent[-1]
    rec, _, sent = record("s" * 8 + "." * 8 + "s" * 3)   # запись оборвали на слове
    assert rec.speculated is None


def test_long_speech_is_never_recognised_early():
    """После пяти секунд речи пауза в середине фразы обычна: распознавать на каждой — тратить впустую."""
    rec, _, sent = record("s" * 70 + "." * 15)
    assert sent == [] and rec.speculated is None


def test_off_by_default_zero():
    rec, _, sent = record("s" * 8 + "." * 15, speculate_after=0)
    assert sent == [] and rec.speculated is None
