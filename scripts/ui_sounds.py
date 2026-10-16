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
LOWPASS_HZ = 1800.0
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


def tone(freq: float, sec: float, decay: float, attack: float = 0.012, glass: float = 0.35) -> np.ndarray:
    """Тёплый тон: основа и две гармоники (2f, 3f) с более быстрым спадом, как у marimba/деревянного
    колокола. Стеклянные негармонические обертоны (2.76f, 5.4f) звенели и кололи слух — убраны.
    `glass` теперь — сила первой гармоники."""
    t = t_axis(sec)
    n = len(t)
    y = np.sin(2 * np.pi * freq * t) * env(n, attack, decay)
    y += glass * 0.4 * np.sin(2 * np.pi * freq * 2 * t) * env(n, attack, decay * 0.5)
    y += glass * 0.12 * np.sin(2 * np.pi * freq * 3 * t) * env(n, attack, decay * 0.3)
    return y


def tick(sec: float = 0.03, centre: float = 700.0) -> np.ndarray:
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
    # Потолок частот: всё выше ~2 кГц гасится плавно, чтобы ни один звук не мог выйти писклявым,
    # что бы ни написали в таблице ниже. Так «высокие тона запрещены» держится кодом, а не вниманием.
    spec = np.fft.rfft(y)
    f = np.fft.rfftfreq(len(y), 1 / SR)
    y = np.fft.irfft(spec / np.sqrt(1 + (f / LOWPASS_HZ) ** 8), len(y))
    y = y / (np.max(np.abs(y)) or 1.0) * 10 ** (peak_db / 20)
    fade = min(len(y), int(SR * 0.01))
    y[-fade:] *= np.linspace(1, 0, fade)
    return y


# Основы — в октавах 3–5 (155–620 Гц): низ и середина. Выше пятой октавы не берём.
SOUNDS = {
    # (функция, пик в dBFS) — тише всего то, что звучит чаще всего
    "hover":       (lambda: place([(0, tone(hz("C", 4), 0.06, 0.016, 0.2))]), -28),
    "click":       (lambda: place([(0, tick(0.03, 600) * 0.8), (0, tone(hz("G", 4), 0.09, 0.025))]), -17),
    "select":      (lambda: place([(0, tick(0.025, 500) * 0.5), (0, tone(hz("Bb", 4), 0.13, 0.04))]), -18),
    "toggle_on":   (lambda: place([(0, tone(hz("G", 4), 0.11, 0.03)), (0.06, tone(hz("C", 5), 0.16, 0.05))]), -18),
    "toggle_off":  (lambda: place([(0, tone(hz("C", 5), 0.1, 0.03)), (0.06, tone(hz("G", 4), 0.15, 0.045))]), -20),
    "drag_start":  (lambda: place([(0, sweep(hz("Bb", 3), hz("Bb", 4), 0.1, 0.06) * 0.7), (0, tick(0.02, 500) * 0.4)]), -21),
    "drop":        (lambda: place([(0, tone(hz("Eb", 3), 0.16, 0.05, 0.15)), (0, tick(0.025, 400) * 0.9)]), -16),
    "open":        (lambda: place([(0, sweep(hz("Eb", 3), hz("Bb", 3), 0.18, 0.08) * 0.6), (0.03, tone(hz("Bb", 3), 0.15, 0.05, glass=0.2) * 0.5)]), -19),
    "close":       (lambda: place([(0, sweep(hz("Bb", 3), hz("Eb", 3), 0.16, 0.06) * 0.6)]), -21),
    "notify":      (lambda: place([(0, tone(hz("G", 4), 0.35, 0.11)), (0.13, tone(hz("Bb", 4), 0.45, 0.16))]), -17),
    "success":     (lambda: place([(0, tone(hz("Eb", 4), 0.22, 0.06)), (0.08, tone(hz("G", 4), 0.22, 0.07)), (0.16, tone(hz("Bb", 4), 0.4, 0.14))]), -16),
    "error":       (lambda: place([(0, tone(hz("Bb", 2), 0.16, 0.06, glass=0.1)), (0.1, tone(hz("F", 2), 0.26, 0.1, glass=0.1))]), -16),
    "listen":      (lambda: place([(0, tone(hz("G", 4), 0.12, 0.035)), (0.07, tone(hz("Bb", 4), 0.18, 0.06))]), -18),
    "listen_end":  (lambda: place([(0, tone(hz("Bb", 4), 0.1, 0.03)), (0.07, tone(hz("G", 4), 0.16, 0.05))]), -21),
    "faceid_scan": (lambda: place([(i * 0.12, tone(hz("Eb", 4), 0.06, 0.015, glass=0.1) * (0.5 + 0.1 * i)) for i in range(4)]), -26),
    "faceid_ok":   (lambda: place([(0, tone(hz("G", 4), 0.22, 0.06)), (0.09, tone(hz("C", 5), 0.55, 0.22, glass=0.5))]), -16),
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
