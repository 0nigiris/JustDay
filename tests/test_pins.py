"""Сказал «Temporarily — раз и навсегда», а включился Эминем: запись в памяти не перебивала поиск. Закреплённое слово применяется кодом до поиска."""
from justday import memory


def test_pinned_word_wins_before_search(tmp_path, monkeypatch):
    monkeypatch.setattr(memory, "PINS", tmp_path / "pins.json")
    memory.pin("  Temporarily ", "Eminem Temporarily wrong")
    memory.pin("Ёлка", "Моя Ёлка — точная")
    assert memory.resolve("temporarily") == "Eminem Temporarily wrong"
    assert memory.resolve("елка") == "Моя Ёлка — точная"
    assert memory.resolve("temporarily live") == "temporarily live"   # только целиком, не кусок фразы
    assert memory.unpin("TEMPORARILY") and memory.resolve("temporarily") == "temporarily"
