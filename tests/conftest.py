"""Общее для тестов ядра.

Ни один тест не должен трогать настоящие данные: планы, сообщения и журнал
событий живут в домашнем каталоге, и «проверка» там означала бы испорченный
список дел у человека. Поэтому каждый тест получает свой временный каталог.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


@pytest.fixture
def state_dir(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    """Состояние JustDay — во временной папке."""
    from justday import config

    monkeypatch.setattr(config, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(config, "EVENTS_FILE", tmp_path / "state" / "events.jsonl")
    (tmp_path / "state").mkdir()
    return tmp_path / "state"


@pytest.fixture
def vault(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    """Хранилище Obsidian — тоже временное, со своим файлом планов."""
    from justday import config, notes

    root = tmp_path / "vault"
    root.mkdir()
    monkeypatch.setattr(notes, "vault", lambda: root)
    monkeypatch.setattr(config, "load", lambda: {"notes": {"vault": str(root), "plans": "Планы.md"}})
    return root
