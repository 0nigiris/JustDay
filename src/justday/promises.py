"""Обещания: «я пообещал Илье скинуть ссылку до пятницы» (пункт 20, ступень 5 — та половина, где слушать некого).

Это отдельный список, не планы в Obsidian: план — то, что человек хочет сделать сам, обещание — то, что он
должен кому-то. Вопрос «что я обещал?» отвечается из него, без поиска по всей памяти. Только то, что ему
сказали голосом или написали в письме: встречи никто не слушает, и без его отдельного «да» слушать нельзя."""
from __future__ import annotations

import json
import time
from datetime import datetime

from . import config

FILE = config.DATA_DIR / "promises.jsonl"


def _all() -> list[dict]:
    try:
        lines = FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue  # битая строка не должна уносить весь список
    return out


def _save(items: list[dict]) -> None:
    FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = FILE.with_suffix(".tmp")
    tmp.write_text("".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items), encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(FILE)


def add(text: str, to: str = "", due: str = "", source: str = "voice") -> dict:
    text = text.strip()
    if not text:
        return {"ok": False, "error": "что именно обещано?"}
    items = _all()
    item = {"id": max((i["id"] for i in items), default=0) + 1, "text": text, "to": to.strip(), "due": due.strip(),
            "source": source, "made": datetime.now().isoformat(timespec="minutes"), "done": None}
    _save([*items, item])
    return {"ok": True, **item}


def open_items(who: str = "") -> list[dict]:
    who = who.lower().strip()
    return [i for i in _all() if not i["done"] and (not who or who in i.get("to", "").lower())]


def find(query: str) -> list[dict]:
    """По словам запроса — в тексте, у кого и на какой срок; выполненные тоже (их спрашивают: «я же это сделал?»)."""
    words = [w for w in query.lower().split() if len(w) > 2]
    return [i for i in _all()
            if any(w in f"{i['text']} {i.get('to', '')} {i.get('due', '')}".lower() for w in words)]


def done(ref: str) -> dict:
    """По номеру или по словам; если подходит несколько открытых — не угадывает."""
    items = _all()
    if ref.strip().isdigit():
        hits = [i for i in items if i["id"] == int(ref) and not i["done"]]
    else:
        words = [w for w in ref.lower().split() if len(w) > 2]
        hits = [i for i in items if not i["done"] and words and all(w in f"{i['text']} {i.get('to', '')}".lower() for w in words)]
    if len(hits) != 1:
        return {"ok": False, "error": "не нашёл" if not hits else "подходит несколько — назови номер",
                "candidates": [{"id": i["id"], "text": i["text"]} for i in hits]}
    hits[0]["done"] = time.strftime("%Y-%m-%dT%H:%M")
    _save(items)
    return {"ok": True, "id": hits[0]["id"], "text": hits[0]["text"]}
