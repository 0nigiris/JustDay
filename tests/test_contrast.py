"""Контраст подписей числом, а не на глаз: бледные подписи (text3) не дотягивали до 4,5:1 на полях окон,
хотя комментарий обещал 4,8 — его никто не пересчитывал."""
import re
from pathlib import Path


def _lin(c: float) -> float:
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _contrast(a: tuple, b: tuple) -> float:
    la, lb = (0.2126 * _lin(x[0]) + 0.7152 * _lin(x[1]) + 0.0722 * _lin(x[2]) for x in (a, b))
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def _over(fg: tuple, alpha: float, bg: tuple) -> tuple:
    return tuple(f * alpha + g * (1 - alpha) for f, g in zip(fg, bg, strict=True))


def test_captions_are_readable_on_every_window_surface() -> None:
    jd = Path("island/JD.qml").read_text(encoding="utf-8")
    m = re.search(r"property color text3: Qt\.rgba\((\d+) / 255, (\d+) / 255, (\d+) / 255, ([\d.]+)\)", jd)
    assert m, "text3 больше не задан через Qt.rgba — поправь разбор"
    rgb, alpha = tuple(int(m.group(i)) / 255 for i in (1, 2, 3)), float(m.group(4))
    surfaces = {"островок": (0, 0, 0), "карточка": (0x1c, 0x1c, 0x1e), "поле": (0x2c, 0x2c, 0x2e)}
    surfaces["карточка + fill1"] = _over((255, 255, 255), 0.08, surfaces["карточка"])
    for name, bg in surfaces.items():
        bg = tuple(c / 255 for c in bg)
        assert _contrast(_over(rgb, alpha, bg), bg) >= 4.5, name
