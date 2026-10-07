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
