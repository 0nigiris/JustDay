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
