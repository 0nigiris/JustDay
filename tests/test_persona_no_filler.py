"""Джарвис спрашивал «я не знаю, поискать?» вместо того, чтобы искать: человек слушал воду и тратил токены.

Правило живёт в тексте характера; проверяем, что оно есть в обоих языках и не потерялось при правках."""
from pathlib import Path

BRAIN = Path(__file__).resolve().parents[1] / "src/justday/brain"


def test_search_without_asking_is_in_both_personas():
    for name, needle in (("PERSONA.md", "ищи сразу"), ("PERSONA.en.md", "search at once")):
        text = (BRAIN / name).read_text(encoding="utf-8")
        assert needle in text and "WebSearch" in text
