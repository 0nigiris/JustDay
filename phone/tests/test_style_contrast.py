"""Подписи на телефоне читаются: палитра была взята у Apple как есть, и в светлой теме
вторичный текст давал 3,3:1, а подсказки («Поверните телефон — вернётся приложение»,
подсказки полей) — 1,8:1."""
import re
from pathlib import Path

CSS = (Path(__file__).resolve().parents[1]
       / "packages/remo32-controller/src/remo32_controller/web/style.css")
LIGHT = "@media (prefers-color-scheme: light)"


def _lin(c: float) -> float:
    c /= 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _contrast(a, b) -> float:
    la, lb = (0.2126 * _lin(x[0]) + 0.7152 * _lin(x[1]) + 0.0722 * _lin(x[2]) for x in (a, b))
    return (max(la, lb) + 0.05) / (min(la, lb) + 0.05)


def _on(block: str, name: str, bg) -> float:
    m = re.search(rf"--{name}: rgba\((\d+), (\d+), (\d+), ([\d.]+)\)", block)
    assert m, f"--{name} больше не rgba — поправь разбор"
    rgb, a = tuple(int(m.group(i)) for i in (1, 2, 3)), float(m.group(4))
    return _contrast(tuple(f * a + g * (1 - a) for f, g in zip(rgb, bg, strict=True)), bg)


def test_secondary_text_and_hints_are_readable_in_both_themes() -> None:
    css = CSS.read_text(encoding="utf-8")
    dark = [(0, 0, 0), (28, 28, 30), (44, 44, 46), (58, 58, 60)]
    light = [(255, 255, 255), (242, 242, 247), (229, 229, 234)]
    themes = {"тёмная": (css.split(LIGHT)[0], dark), "светлая": (css[css.index(LIGHT):], light)}
    for name, (block, surfaces) in themes.items():
        for bg in surfaces:
            assert _on(block, "text-dim", bg) >= 4.5, f"{name}: text-dim на {bg}"
            assert _on(block, "text-faint", bg) >= 3, f"{name}: text-faint на {bg}"


def test_hints_people_read_are_not_set_in_faint() -> None:
    css = CSS.read_text(encoding="utf-8")
    for rule in (".deck-hint {", ".field .hint {", ".toast .rid {", ".crumbs {", ".divider {"):
        assert "text-faint" not in css[css.index(rule):].split("}")[0], rule
