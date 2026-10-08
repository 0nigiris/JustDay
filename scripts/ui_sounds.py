#!/usr/bin/env python3
"""Собирает звуки интерфейса JustDay в `island/sounds/*.wav`.

Звуки не рисует нейросеть, а считает формула. Причина: «приятно, как у Apple» держится не на
красивом тембре, а на единстве — одна нота-основа, одинаковая мягкость атаки, никаких хвостов
реверберации, одна громкость. Нейросеть каждый раз даёт новый характер, и сборник звучит как
случайный набор. Здесь всё берётся из одной гаммы (ми-бемоль мажорная пентатоника), поэтому
любые два звука подряд не диссонируют. Правится число — пересобирается весь набор:

    .venv/bin/python scripts/ui_sounds.py
"""
from __future__ import annotations

import wave
from pathlib import Path

import numpy as np

SR = 44100
OUT = Path(__file__).resolve().parent.parent / "island" / "sounds"

# Eb-мажорная пентатоника: Eb F G Bb C. Любая комбинация консонантна.
_SEMI = {"Eb": 0, "F": 2, "G": 4, "Bb": 7, "C": 9}


def hz(note: str, octave: int) -> float:
    return 311.13 * 2 ** (_SEMI[note] / 12) * 2 ** (octave - 4)


def t_axis(sec: float) -> np.ndarray:
    return np.arange(int(SR * sec)) / SR


def env(n: int, attack: float, decay: float) -> np.ndarray:
    """Быстрая линейная атака (без щелчка) и экспоненциальный спад."""
    t = np.arange(n) / SR
    a = np.minimum(1.0, t / max(attack, 1e-4))
    return a * np.exp(-t / decay)


def tone(freq: float, sec: float, decay: float, attack: float = 0.004, glass: float = 0.35) -> np.ndarray:
    """Стеклянный тон: основа плюс две негармонические обертоны с более быстрым спадом."""
    t = t_axis(sec)
    n = len(t)
    y = np.sin(2 * np.pi * freq * t) * env(n, attack, decay)
    y += glass * 0.5 * np.sin(2 * np.pi * freq * 2.76 * t) * env(n, attack, decay * 0.35)
    y += glass * 0.25 * np.sin(2 * np.pi * freq * 5.4 * t) * env(n, attack, decay * 0.15)
    return y


def tick(sec: float = 0.03, centre: float = 3200.0) -> np.ndarray:
    """Короткий шумовой щелчок, срезанный по частоте: даёт ощущение касания, а не писк."""
    rng = np.random.default_rng(7)
    n = int(SR * sec)
    x = rng.standard_normal(n) * env(n, 0.0005, sec / 4)
    # полосовой фильтр через разность двух скользящих средних — без scipy
    k1, k2 = max(1, int(SR / (centre * 2))), max(2, int(SR / (centre / 3)))
    lo = np.convolve(x, np.ones(k2) / k2, mode="same")
    hi = np.convolve(x, np.ones(k1) / k1, mode="same")
    return hi - lo


def sweep(f0: float, f1: float, sec: float, decay: float) -> np.ndarray:
    t = t_axis(sec)
    f = f0 * (f1 / f0) ** (t / sec)
    phase = 2 * np.pi * np.cumsum(f) / SR
    return np.sin(phase) * env(len(t), 0.01, decay)


def place(parts: list[tuple[float, np.ndarray]], tail: float = 0.05) -> np.ndarray:
    end = max(s + len(x) / SR for s, x in parts) + tail
    y = np.zeros(int(SR * end))
    for start, x in parts:
        i = int(SR * start)
        y[i:i + len(x)] += x
    return y


def finish(y: np.ndarray, peak_db: float) -> np.ndarray:
    """Нормировка по пику и короткое затухание в конце, чтобы не было щелчка на обрыве."""
    y = y / (np.max(np.abs(y)) or 1.0) * 10 ** (peak_db / 20)
    fade = min(len(y), int(SR * 0.01))
    y[-fade:] *= np.linspace(1, 0, fade)
    return y


SOUNDS = {
    # (функция, пик в dBFS) — тише всего то, что звучит чаще всего
    "hover":       (lambda: place([(0, tone(hz("C", 6), 0.05, 0.012, 0.15))]), -26),
    "click":       (lambda: place([(0, tick(0.025) * 0.9), (0, tone(hz("G", 5), 0.07, 0.016))]), -16),
    "select":      (lambda: place([(0, tick(0.02, 2600) * 0.6), (0, tone(hz("Bb", 5), 0.11, 0.03))]), -17),
    "toggle_on":   (lambda: place([(0, tone(hz("G", 5), 0.09, 0.02)), (0.05, tone(hz("C", 6), 0.13, 0.035))]), -17),
    "toggle_off":  (lambda: place([(0, tone(hz("C", 6), 0.08, 0.02)), (0.05, tone(hz("G", 5), 0.12, 0.03))]), -19),
    "drag_start":  (lambda: place([(0, sweep(hz("Bb", 4), hz("Bb", 5), 0.09, 0.05) * 0.7), (0, tick(0.015, 2000) * 0.5)]), -20),
    "drop":        (lambda: place([(0, tone(hz("Eb", 4), 0.14, 0.04, 0.1)), (0, tick(0.02, 1500) * 0.8)]), -15),
    "open":        (lambda: place([(0, sweep(hz("Eb", 5), hz("Bb", 5), 0.16, 0.07) * 0.6), (0.02, tone(hz("Bb", 5), 0.12, 0.04, glass=0.2) * 0.5)]), -19),
    "close":       (lambda: place([(0, sweep(hz("Bb", 5), hz("Eb", 5), 0.14, 0.05) * 0.6)]), -21),
    "notify":      (lambda: place([(0, tone(hz("G", 5), 0.3, 0.09)), (0.11, tone(hz("Bb", 5), 0.4, 0.13))]), -16),
    "success":     (lambda: place([(0, tone(hz("Eb", 5), 0.2, 0.05)), (0.07, tone(hz("G", 5), 0.2, 0.06)), (0.14, tone(hz("Bb", 5), 0.34, 0.12))]), -15),
    "error":       (lambda: place([(0, tone(hz("Bb", 4), 0.14, 0.05, glass=0.1)), (0.09, tone(hz("F", 4), 0.22, 0.09, glass=0.1))]), -15),
    "listen":      (lambda: place([(0, tone(hz("G", 5), 0.1, 0.03)), (0.06, tone(hz("Bb", 5), 0.16, 0.05))]), -17),
    "listen_end":  (lambda: place([(0, tone(hz("Bb", 5), 0.09, 0.025)), (0.06, tone(hz("G", 5), 0.14, 0.04))]), -20),
    "faceid_scan": (lambda: place([(i * 0.11, tone(hz("Eb", 6), 0.05, 0.012, glass=0.1) * (0.5 + 0.1 * i)) for i in range(4)]), -24),
    "faceid_ok":   (lambda: place([(0, tone(hz("G", 5), 0.2, 0.05)), (0.08, tone(hz("C", 6), 0.5, 0.2, glass=0.5))]), -15),
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (make, peak) in SOUNDS.items():
        pcm = (finish(make(), peak) * 32767).astype("<i2")
        with wave.open(str(OUT / f"{name}.wav"), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(SR)
            w.writeframes(pcm.tobytes())
        print(f"{name:12s} {len(pcm) / SR * 1000:5.0f} мс  пик {peak} дБ")


if __name__ == "__main__":
    main()
