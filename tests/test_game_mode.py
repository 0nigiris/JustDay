"""Оболочка работала поверх игры: человек удалял JustDay из-за потерянных кадров (Р2-46)."""
from pathlib import Path


def test_game_mode_switches_all_animation_off():
    """animOn гасит каждый Behavior и таймеры анимаций; игра на весь экран должна его гасить."""
    jd = Path(__file__).resolve().parent.parent / "island" / "JD.qml"
    src = jd.read_text(encoding="utf-8")
    assert "readonly property bool gameMode: game !== \"\" && fullscreen" in src
    assert 'animStyle !== "off" && !gameMode' in src
