"""Мат был один на всех: «можно» или «нельзя». Уровень выбирает густоту, но на человека не злится ни на одном."""
from justday import persona


def _cfg(level, on=True):
    return {"user": {"language": "ru"}, "persona": {"character": "jarvis", "swearing": on, "swearing_level": level}}


def test_level_picks_the_text_and_clean_ignores_it():
    low, high = persona.character(_cfg(0)), persona.character(_cfg(100))
    assert low != high and "редкий" in low and "сапожник" in high
    assert "Никогда всерьёз" in low and "Никогда всерьёз" in high
    assert persona.character(_cfg(100, on=False)).endswith("Без мата.")
