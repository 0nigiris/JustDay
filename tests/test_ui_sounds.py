"""Звуки интерфейса были писклявыми и играли вдвое: он потребовал мягкие, без высоких тонов."""
import wave
from pathlib import Path

import numpy as np

from justday import audio

SOUNDS = Path(__file__).resolve().parent.parent / "island" / "sounds"


def _high_share(y: np.ndarray, sr: int) -> float:
    spec = np.abs(np.fft.rfft(y)) ** 2
    return spec[np.fft.rfftfreq(len(y), 1 / sr) > 2000].sum() / spec.sum()


def test_island_sounds_have_no_shrill_highs():
    files = sorted(SOUNDS.glob("*.wav"))
    assert files
    for f in files:
        with wave.open(str(f)) as w:
            y = np.frombuffer(w.readframes(w.getnframes()), "<i2").astype(float)
            assert _high_share(y, w.getframerate()) < 0.01, f.name


def test_daemon_earcons_stay_low_and_soft():
    for kind in ("listen", "done", "error", "alarm"):
        y = audio.earcon(kind).astype(float)
        assert _high_share(y, 48000) < 0.02, kind
