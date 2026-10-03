"""История разговоров: что человек сказал, что ответили и когда.

Сказанное и без того пишется в журнал событий, но человеку журнал не виден: он наговорил длинную
задачу и не нашёл её нигде. Здесь тот же журнал читается как переписка, с поиском по словам.

Чего здесь нет нарочно: писем и паролей. Ответ, прочитанный вслух из письма, — это содержимое чужого
письма, а не наш разговор, поэтому реплики хода, где трогали почту, пропускаются целиком. Реплики,
где есть слово, похожее на ключ или пароль, тоже (`clipboard.looks_secret`).
"""
from __future__ import annotations

import re

from . import clipboard, events

MAIL = re.compile(r"mail|inbox|почт|письм", re.I)


def items(query: str = "", limit: int = 80) -> list[dict]:
    """Реплики от новых к старым: {ts, who: "you" | "jarvis", text}. `query` — слова через пробел, все."""
    words = query.lower().split()
    out: list[dict] = []
    mailish = False                      # в этом ходе трогали почту: его ответы — чужие письма
    for ev in events.read():
        kind = ev.get("kind")
        if kind == "heard":
            mailish = False
        elif kind == "tool" and MAIL.search(f"{ev.get('name', '')} {ev.get('desc', '')} {ev.get('input', '')}"):
            mailish = True
        if kind not in ("heard", "say") or (mailish and kind == "say"):
            continue
        text = str(ev.get("text") or "").strip()
        if not text or any(clipboard.looks_secret(w) for w in (text, *text.split())) or any(w not in text.lower() for w in words):
            continue
        out.append({"ts": ev.get("ts", ""), "who": "you" if kind == "heard" else "jarvis", "text": text})
    return out[::-1][:limit]
