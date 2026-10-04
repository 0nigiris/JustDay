"""Демон переживает то, что раньше убивало его части до рестарта (Р-13, Р-14, Р-15, Р-16)."""

import asyncio
import os
import stat
import threading
import time

import numpy as np
import pytest

from justday import audio, calendar_lane, config, daemon, desktop, events, island
from justday.stt import STT


def test_the_microphone_came_back_after_pipewire_restarted(tmp_path, monkeypatch):
    """pw-record умер (перезапуск PipeWire, выдернули гарнитуру) — и микрофон молчал до кнопки."""
    once = tmp_path / "once"
    tool = tmp_path / "pw-record"
    tool.write_text(f'#!/bin/sh\nif [ ! -f {once} ]; then touch {once}; head -c 64000 /dev/zero; exit 1; fi\n'
                    'exec cat /dev/zero\n')
    tool.chmod(tool.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{tmp_path}:{os.environ['PATH']}")
    monkeypatch.setattr(audio.Microphone, "RESTART_DELAY", 0.05)
    mic = audio.Microphone()
    frames = []
    mic.subscribe(lambda f: frames.append(1))
    mic.start()
    try:
        for _ in range(100):
            if once.exists() and len(frames) > 200:
                break
            time.sleep(0.05)
        assert once.exists() and len(frames) > 200
    finally:
        mic.stop()


def test_hearing_came_back_after_the_machine_slept():
    """После сна Whisper падал cudaErrorInvalidDevice на каждой фразе до рестарта: мёртвая модель
    держалась в памяти. Теперь она отпускается и грузится заново."""
    class Seg:
        text, no_speech_prob, words = "привет", 0.0, []

    class Dead:
        def transcribe(self, *a, **k):
            def gen():
                raise RuntimeError("CUDA failed with error invalid device ordinal")
                yield
            return gen(), None

    class Alive:
        def transcribe(self, *a, **k):
            return iter([Seg()]), None

    stt = STT({"language": "ru", "model": "x"})
    loads = iter([Dead(), Alive()])
    stt._load = lambda: next(loads)
    assert stt.transcribe(np.ones(16000, dtype=np.int16)) == "привет"


@pytest.fixture
def live(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    monkeypatch.setattr(events, "emit", lambda *a, **k: None)
    d = daemon.Daemon()

    async def nothing(*a, **k):
        return None

    monkeypatch.setattr(d, "earcon", nothing)
    monkeypatch.setattr(d.mic, "start", lambda: None)
    return d


def test_a_failed_transcription_did_not_leave_the_assistant_deaf(live, monkeypatch):
    """Ошибка распознавания оставляла «transcribing» навсегда, и по имени он больше не просыпался."""
    async def record(cancel, prefill=None):
        return np.ones(audio.RATE, dtype=np.int16)

    def broken(pcm):
        raise RuntimeError("CUDA error: out of memory")

    monkeypatch.setattr(live.recorder, "record", record)
    monkeypatch.setattr(live.stt, "transcribe", broken)
    asyncio.run(live._listen_once(False))
    assert live.state == "idle"


def test_one_bad_round_did_not_stop_housekeeping_and_the_ping_went_on(live, monkeypatch):
    """Одно исключение убивало почту, воркеров и очередь событий навсегда; а пинг островку ждал
    сетевые дела круга и опаздывал — островок считал демон мёртвым."""
    rounds, pings = [], []
    monkeypatch.setattr(live, "HOUSEKEEPING_EVERY", 0.01)
    monkeypatch.setattr(calendar_lane, "urls", lambda: [])
    monkeypatch.setattr(desktop, "running_game", lambda: None)

    async def reboot_maybe():
        rounds.append(1)
        if len(rounds) == 1:
            raise FileNotFoundError("state.tmp")
        if len(rounds) == 3:
            await asyncio.sleep(10)   # долгий сетевой круг

    monkeypatch.setattr(live, "_reboot_maybe", reboot_maybe)
    monkeypatch.setattr(island, "vocabulary", lambda cfg: "")
    real_publish = live.publish
    monkeypatch.setattr(live, "publish", lambda **k: pings.append(1) if "ping" in k else real_publish(**k))
    monkeypatch.setattr(live, "HEARTBEAT_EVERY", 0.05)

    async def go():
        hk, hb = asyncio.ensure_future(live._housekeeping()), asyncio.ensure_future(live._heartbeat())
        await asyncio.sleep(0.5)
        hk.cancel()
        hb.cancel()

    asyncio.run(go())
    assert len(rounds) >= 3 and len(pings) >= 3


def test_state_writers_did_not_trip_over_each_other(tmp_path, monkeypatch):
    """Четыре писателя state.json с общим .tmp: FileNotFoundError и потерянные ключи."""
    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    monkeypatch.setattr(config, "STATE_FILE", tmp_path / "state.json")
    errors = []

    def writer(n):
        try:
            for i in range(20):
                events.save_state(**{f"k{n}_{i}": i})
        except Exception as e:
            errors.append(e)

    threads = [threading.Thread(target=writer, args=(n,)) for n in range(4)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    assert not errors
    assert len(events.load_state()) == 80
