"""«Который час» не должен стоить хода модели (Р-26 ревизии)."""

import asyncio
from datetime import datetime

import pytest

from justday import config, daemon, events, fastpath, numerals

NOON = datetime(2026, 10, 3, 14, 5)


@pytest.mark.parametrize("said, answer", [
    ("Который час?", "Сейчас четырнадцать ноль пять."),
    ("Джарвис, сколько времени", "Сейчас четырнадцать ноль пять."),
    ("какое сегодня число", "Сегодня суббота, третье октября."),
    ("Спасибо!", "Да не за что."),
])
def test_the_clock_question_went_to_the_cloud(said, answer):
    assert fastpath.small_talk(said, NOON) == answer


@pytest.mark.parametrize("said", ["который час в Токио", "сколько времени ехать до Мадрида", "открой дискорд",
                                  "спасибо, а теперь открой почту"])
def test_real_questions_still_reach_the_brain(said):
    assert fastpath.small_talk(said, NOON) is None


def test_the_third_was_spoken_as_tretye_with_a_double_soft_sign():
    """«3 октября» читалось «третьье октября»."""
    assert [numerals.ordinal(3, e) for e in ("ое", "ая", "ую")] == ["третье", "третья", "третью"]


def test_the_brain_was_not_asked_what_time_it_is(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    monkeypatch.setattr(events, "emit", lambda *a, **k: None)
    d = daemon.Daemon()
    said = []

    async def say(text, **k):
        said.append(text)

    async def brain_ask(*a, **k):
        raise AssertionError("мозг не должен был понадобиться")

    monkeypatch.setattr(d, "say", say)
    monkeypatch.setattr(d.brain, "ask", brain_ask)
    got = asyncio.run(d.handle_local("который час"))
    assert got and got.startswith("Сейчас") and said == [got]


def test_open_mixer_by_voice_did_not_go_to_the_brain(tmp_path, monkeypatch):
    """Сказал «открой микшер» — слова без слэша не знал никто, и вопрос уходил мозгу (Р2-48)."""
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    monkeypatch.setattr(events, "emit", lambda *a, **k: None)
    d = daemon.Daemon()
    shown = []
    monkeypatch.setattr(d, "publish", lambda **k: shown.append(k))
    assert asyncio.run(d.handle_local("Открой микшер.")) == ""
    assert {"panel": "mixer"} in shown


def test_background_polls_slow_down_in_a_game(tmp_path, monkeypatch):
    """Опросы сессий и процессора шли с той же частотой в игре, отнимая у неё кадры (Р2-46)."""
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    d = daemon.Daemon()
    assert d._game_slowdown() == 1.0
    d._game_seen = "Dota 2"
    assert d._game_slowdown() == 10.0


def test_play_from_clipboard_takes_only_a_youtube_link(tmp_path, monkeypatch):
    """«Включи из буфера» при чужом тексте в буфере (пароль, заметка) не должно искать его на YouTube (Р2-33)."""
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    monkeypatch.setattr(events, "emit", lambda *a, **k: None)
    d = daemon.Daemon()
    clip = {"v": "hunter2"}

    class R:
        returncode = 0

        @property
        def stdout(self):
            return clip["v"]

    monkeypatch.setattr(daemon.subprocess, "run", lambda *a, **k: R())
    played = []

    async def play(q, **k):
        played.append(q)

    monkeypatch.setattr(d, "play_music", play)

    async def go():
        a = await d.handle_local("включи из буфера")
        clip["v"] = "https://youtu.be/dQw4w9WgXcQ"
        b = await d.handle_local("включи из буфера")
        await asyncio.sleep(0.05)
        return a, b

    a, b = asyncio.run(go())
    assert "нет ссылки" in a and b == "" and played == ["https://youtu.be/dQw4w9WgXcQ"]
