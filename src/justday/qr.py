"""QR-код ссылкой или Wi-Fi: показать на экране, чтобы снять телефоном (пункт 30 плана).

Кодирует segno (чистый Python, без зависимостей). Пароль сети здесь только проходит насквозь: он не пишется
ни в журнал, ни в историю — ответ демона уходит островку и больше нигде не лежит."""
from __future__ import annotations

import segno

BAD = "\\;,:\""   # символы, которые в записи WIFI: надо экранировать


def wifi_payload(ssid: str, password: str = "", security: str = "WPA", hidden: bool = False) -> str:
    """Строка `WIFI:…` в формате, который понимают камеры Android и iOS.

    Спецсимволы `\\ ; , : "` экранируются: сеть с `;` в имени иначе обрывала бы запись на полуслове, и телефон
    подключался к сети с другим именем или не подключался вовсе."""
    def esc(s: str) -> str:
        return "".join("\\" + c if c in BAD else c for c in s)

    kind = "nopass" if not password else ("WEP" if security.upper() == "WEP" else "WPA")
    return f"WIFI:T:{kind};S:{esc(ssid)};P:{esc(password)};{'H:true;' if hidden else ''};"


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
