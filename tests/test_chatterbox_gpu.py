"""Chatterbox лагал, когда видеокарту делила игра: он должен уступать Silero.

Его просьба 7 октября: «если видеокарта сильно используется — пусть переключается на Silero,
чтобы не лагало». Проверяем решение «занята ли карта» и то, что Silero в запасе не пропал.
"""

from __future__ import annotations

import subprocess
from types import SimpleNamespace

from justday.tts import TTS


def голос(**cfg: object) -> TTS:
    tts = TTS.__new__(TTS)
    tts.cfg = {"engine": "chatterbox", **cfg}
    tts._gpu_seen = (0.0, 0)
    return tts


def _smi(monkeypatch, out: str | None) -> None:
    def run(*a, **k):
        if out is None:
            raise FileNotFoundError("nvidia-smi")
        return SimpleNamespace(stdout=out)
    monkeypatch.setattr(subprocess, "run", run)


def test_игра_грузит_карту_говорит_silero(monkeypatch) -> None:
    _smi(monkeypatch, "87, 6000\n")
    assert голос().gpu_busy()


def test_карта_свободна_говорит_chatterbox(monkeypatch) -> None:
    _smi(monkeypatch, "4, 6000\n")
    assert not голос().gpu_busy()


def test_порог_настраивается(monkeypatch) -> None:
    _smi(monkeypatch, "40, 6000\n")
    assert голос(gpu_busy_percent=30).gpu_busy()


def test_видеопамять_кончилась_говорит_silero(monkeypatch) -> None:
    """7 октября: карта простаивала, но 11,9 из 12 ГБ было занято — Chatterbox упал по памяти."""
    _smi(monkeypatch, "3, 36\n")
    assert голос().gpu_busy()


def test_без_nvidia_не_мешаем(monkeypatch) -> None:
    _smi(monkeypatch, None)
    assert not голос().gpu_busy()


def test_silero_слушает_свою_службу_а_голос_свою() -> None:
    tts = голос()
    assert tts.neural_socket() == TTS.CHATTERBOX_SOCKET
    tts.cfg["engine"] = "qwen"
    assert tts.neural_socket() == TTS.SOCKET


def test_кончились_кредиты_elevenlabs_говорит_silero_а_не_грузит_qwen(monkeypatch) -> None:
    """Запасным у ElevenLabs был Qwen: полминуты холодного старта и 3,4 ГБ видеопамяти на каждый
    отказ (бесплатный тариф, кончились кредиты). Должен говорить Silero."""
    import asyncio

    from justday.daemon import Daemon

    d = Daemon.__new__(Daemon)
    tried, played = [], []

    async def stream(sentence, gen, engine):
        tried.append(engine)
        return False

    async def play(pcm, rate):
        played.append(len(pcm))

    import numpy as np

    d.tts = SimpleNamespace(cfg={"engine": "elevenlabs"}, rate=48000, synth=lambda s: np.ones(10, dtype=np.int16))
    d._speak_stream, d._neural_cold_until, d._speech_gen, d._synth_ahead = stream, 0.0, 0, {}
    d.player = SimpleNamespace(play=play)
    d.brain = SimpleNamespace(busy=False)
    d._state = "idle"
    monkeypatch.setattr(Daemon, "state", property(lambda s: s._state, lambda s, v: setattr(s, "_state", v)))

    async def run():
        d._speech_q = asyncio.Queue()
        d._speech_q.put_nowait("Привет.")
        task = asyncio.create_task(d._speech_worker())
        while not played:
            await asyncio.sleep(0.01)
        task.cancel()

    asyncio.run(asyncio.wait_for(run(), 5))
    assert tried == ["elevenlabs"] and played == [10]
