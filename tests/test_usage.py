"""Счётчики расхода: токены по дням и кто будит ассистента."""

from __future__ import annotations

import json
import time

import pytest

from justday import usage


class TestЦены:
    def test_по_имени_модели(self) -> None:
        # Чтение из кэша — главная статья расхода, и она у моделей разная.
        миллион = {"cache_read_input_tokens": 1_000_000}
        assert usage._cost("claude-opus-5", миллион) == pytest.approx(1.5)
        assert usage._cost("claude-sonnet-5", миллион) == pytest.approx(0.3)
        assert usage._cost("claude-haiku-4-5", миллион) == pytest.approx(0.1)

    def test_незнакомая_модель_считается_по_средней(self) -> None:
        assert usage._cost("что-то-новое", {"output_tokens": 1_000_000}) == pytest.approx(15.0)


class TestОтчётПоТокенам:
    def сессия(self, tmp_path, monkeypatch, записи: list[dict]):  # type: ignore[no-untyped-def]
        каталог = tmp_path / "sessions"
        каталог.mkdir()
        (каталог / "s.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in записи), encoding="utf-8")
        monkeypatch.setattr(usage, "sessions_dir", lambda: каталог)

    def запись(self, день: str, контекст: int, out: int = 10, rid: str = "r1") -> dict:
        return {"timestamp": f"{день}T12:00:00Z", "requestId": rid,
                "message": {"model": "claude-sonnet-5",
                            "usage": {"cache_read_input_tokens": контекст, "output_tokens": out}}}

    def test_считает_контекст_на_шаг(self, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        сегодня = time.strftime("%Y-%m-%d")
        self.сессия(tmp_path, monkeypatch, [
            self.запись(сегодня, 30_000, rid="a"),
            self.запись(сегодня, 50_000, rid="b"),
        ])
        got = usage.report(7)
        assert got["total"]["steps"] == 2
        assert got["total"]["per_step"] == 40_000
        # Стартовый контекст — первый запрос сессии, по нему видно цену «холостого хода».
        assert got["start_context"] == 30_000

    def test_повторы_одного_запроса_не_считаются_дважды(self, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        сегодня = time.strftime("%Y-%m-%d")
        self.сессия(tmp_path, monkeypatch, [self.запись(сегодня, 10_000, rid="один")] * 3)
        assert usage.report(7)["total"]["steps"] == 1

    def test_пустой_каталог_не_падает(self, tmp_path, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        monkeypatch.setattr(usage, "sessions_dir", lambda: tmp_path / "нет")
        got = usage.report(7)
        assert got["total"]["steps"] == 0 and got["start_context"] == 0


class TestКтоБудит:
    def события(self, state_dir, записи: list[dict]) -> None:  # type: ignore[no-untyped-def]
        (state_dir / "events.jsonl").write_text(
            "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in записи), encoding="utf-8")

    def test_пустые_пробуждения_видны_по_источникам(self, state_dir, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        from justday import config

        monkeypatch.setattr(config, "EVENTS_FILE", state_dir / "events.jsonl")
        сейчас = time.strftime("%Y-%m-%dT%H:%M:%S")
        self.события(state_dir, [
            {"ts": сейчас, "kind": "listen_start", "source": "wake"},
            {"ts": сейчас, "kind": "listen_empty"},
            {"ts": сейчас, "kind": "listen_start", "source": "wake"},
            {"ts": сейчас, "kind": "heard", "text": "привет"},
            {"ts": сейчас, "kind": "listen_start", "source": "button"},
            {"ts": сейчас, "kind": "heard", "text": "включи музыку"},
        ])
        got = usage.wake_report(1)
        assert got["sources"]["wake"] == {"woke": 2, "empty": 1}
        assert got["sources"]["button"] == {"woke": 1, "empty": 0}
        assert got["total"] == {"woke": 3, "empty": 1}

    def test_ответы_на_вопрос_не_считаются_пробуждением(self, state_dir, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        from justday import config

        monkeypatch.setattr(config, "EVENTS_FILE", state_dir / "events.jsonl")
        сейчас = time.strftime("%Y-%m-%dT%H:%M:%S")
        self.события(state_dir, [
            {"ts": сейчас, "kind": "listen_start", "followup": True, "source": "wake"},
        ])
        assert usage.wake_report(1)["total"]["woke"] == 0
