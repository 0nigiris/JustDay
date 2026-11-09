"""QR для сопряжения телефона (`justday phone pair`).

Вкладку «QR» в инструментах он попросил убрать 9 нояб.: ею не пользовался. Кодирует segno (чистый Python)."""
from __future__ import annotations

import segno


def matrix(text: str) -> list[str]:
    """Строки из «0» и «1» без белой рамки; рамку рисует тот, кто показывает. Пустой текст — ValueError."""
    if not text:
        raise ValueError("нечего кодировать")
    code = segno.make(text, error="m", micro=False)  # Micro QR читают не все камеры
    return ["".join("1" if cell else "0" for cell in row) for row in code.matrix]


def ascii_art(rows: list[str]) -> str:
    """Для терминала: два пикселя в знак (▀▄█), чтобы код был квадратным. Рамка в четыре модуля — по стандарту."""
    n = len(rows)
    pad = "0" * (n + 8)
    grid = [pad] * 4 + ["0000" + r + "0000" for r in rows] + [pad] * 4
    if len(grid) % 2:
        grid.append(pad)
    out = []
    for top, bottom in zip(grid[::2], grid[1::2]):
        out.append("".join(" ▀▄█"[(a == "1") * 1 + (b == "1") * 2] for a, b in zip(top, bottom)))
    return "\n".join(out)
