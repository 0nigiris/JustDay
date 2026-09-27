"""Страница дня: факты из журнала, а не пересказ модели."""

from __future__ import annotations

import json
import time

import pytest


@pytest.fixture
def день(state_dir, vault, monkeypatch):  # type: ignore[no-untyped-def]
    from justday import config, events, notes, usage

    monkeypatch.setattr(config, "load", lambda: {
        "notes": {"vault": str(vault), "plans": "Планы.md", "diary": "Дневник", "diary_hour": 23},
    })
    monkeypatch.setattr(usage, "report", lambda days=7: {"days": [], "total": {}, "start_context": 0})
    сегодня = time.strftime("%Y-%m-%d")
    (state_dir / "events.jsonl").write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in [
        {"ts": f"{сегодня}T10:00:00", "kind": "request", "source": "voice", "text": "включи музыку"},
        {"ts": f"{сегодня}T10:05:00", "kind": "fast", "text": "пауза"},
        {"ts": f"{сегодня}T10:06:00", "kind": "scene", "name": "Работа"},
        {"ts": f"{сегодня}T10:07:00", "kind": "turn_done", "turns": 2},
        {"ts": f"{сегодня}T11:00:00", "kind": "request", "source": "event",
         "text": "[Событие JustDay] Фоновая задача закончилась"},
        {"ts": "2020-01-01T10:00:00", "kind": "request", "source": "voice", "text": "позапрошлогоднее"},
    ]), encoding="utf-8")
    monkeypatch.setattr(events.config, "EVENTS_FILE", state_dir / "events.jsonl")
    return notes


def test_страница_собирается_из_фактов(день, vault) -> None:  # type: ignore[no-untyped-def]
    got = день.diary()
    text = (vault / "Дневник" / f"{time.strftime('%Y-%m-%d')}.md").read_text(encoding="utf-8")
    assert "включи музыку" in text
    assert "Работа" in text
    assert got["asked"] == 1  # события самого JustDay просьбами не считаются
    assert "мгновенных команд: 1" in text


def test_чужие_дни_не_попадают(день, vault) -> None:  # type: ignore[no-untyped-def]
    день.diary()
    text = (vault / "Дневник" / f"{time.strftime('%Y-%m-%d')}.md").read_text(encoding="utf-8")
    assert "позапрошлогоднее" not in text


def test_свои_слова_дописываются(день, vault) -> None:  # type: ignore[no-untyped-def]
    день.diary(extra="День прошёл спокойно.")
    text = (vault / "Дневник" / f"{time.strftime('%Y-%m-%d')}.md").read_text(encoding="utf-8")
    assert "День прошёл спокойно." in text


def test_дневник_не_уходит_за_пределы_хранилища(день, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    from justday import config

    monkeypatch.setattr(config, "load", lambda: {
        "notes": {"vault": "", "plans": "Планы.md", "diary": "../../побег"},
    })
    with pytest.raises(RuntimeError):
        день.diary()
