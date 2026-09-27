"""Сообщения, оставленные с телефона, пока компьютера не было рядом.

Человек открывает пульт в дороге, говорит «поставь на утро сборку» — и уходит.
Компьютер выключен, отвечать некому, поэтому просьба ложится сюда: сначала в
телефон, а при первой же связи — в этот файл. Когда JustDay просыпается, он
читает накопившееся и сам решает, что делать сейчас, а что отложить.

Файл — обычный JSONL в состоянии JustDay: одна строка на сообщение. Ничего
не уходит в облако само по себе; в модель текст попадает тогда же, когда попал
бы голос — когда ассистент докладывает о нём хозяину.
"""
from __future__ import annotations

import json
import time
import uuid
from typing import Any

from . import config

FILE = config.STATE_DIR / "inbox.jsonl"
MAX_TEXT = 4000


def _read() -> list[dict[str, Any]]:
    try:
        lines = FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _write(items: list[dict[str, Any]]) -> None:
    FILE.parent.mkdir(parents=True, exist_ok=True)
    FILE.write_text("".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items), encoding="utf-8")


def add(text: str, source: str = "phone", created: float = 0.0) -> dict[str, Any]:
    """Записать сообщение. `created` — когда его набрали на телефоне (а не когда оно дошло)."""
    text = str(text or "").strip()[:MAX_TEXT]
    if not text:
        raise ValueError("пустое сообщение")
    item = {"id": uuid.uuid4().hex[:12], "text": text, "source": source,
            "created": float(created or time.time()), "received": time.time(), "state": "new"}
    items = _read()
    items.append(item)
    _write(items[-200:])
    return item


def pending() -> list[dict[str, Any]]:
    """Что ещё не доложено хозяину."""
    return [i for i in _read() if i.get("state") == "new"]


def mark_reported(ids: list[str]) -> int:
    """Доложено: сообщение остаётся в истории, но больше не всплывает."""
    wanted = set(ids)
    items = _read()
    hit = 0
    for item in items:
        if item.get("id") in wanted and item.get("state") == "new":
            item["state"] = "reported"
            item["reported"] = time.time()
            hit += 1
    if hit:
        _write(items)
    return hit


def recent(limit: int = 20) -> list[dict[str, Any]]:
    return _read()[-limit:]


def clear() -> int:
    items = _read()
    _write([])
    return len(items)


def summary(items: list[dict[str, Any]]) -> str:
    """Как это выглядит в реплике для модели: время и текст, по одному на строку."""
    lines = []
    for item in items:
        when = time.strftime("%d.%m %H:%M", time.localtime(item.get("created") or item.get("received", 0)))
        lines.append(f"— {when}: {item['text']}")
    return "\n".join(lines)
