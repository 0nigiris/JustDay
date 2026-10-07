"""Отдельный чат с ассистентом (Р2-42): история в файлах, ответы никогда не идут в голос.

Один чат — один файл `chats/<id>.jsonl`: первая строка — заголовок и id сессии мозга, дальше сообщения.
Файл, а не база: его видно глазами, и он переживает любое обновление."""
from __future__ import annotations

import json
import re
import secrets
import time
from pathlib import Path

from . import config

CHAT_NOTE = ("\n\n# Режим чата\nТы пишешь в текстовом чате, а не говоришь вслух: можно разметку, списки и код. "
             "Ничего не озвучивается. Если человек просит сказать что-то голосом, используй `justday say`.")


def chats_dir() -> Path:
    d = config.DATA_DIR / "chats"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _path(chat_id: str) -> Path:
    # id приходит от острова: без этой проверки «../../x» вышел бы из папки чатов
    if not re.fullmatch(r"[0-9a-f]{12}", chat_id):
        raise ValueError(f"bad chat id: {chat_id!r}")
    return chats_dir() / f"{chat_id}.jsonl"


def _read(p: Path) -> list[dict]:
    rows = []
    for line in p.read_text(encoding="utf-8").splitlines():
        try:
            rows.append(json.loads(line))
        except ValueError:
            continue  # оборванная запись при выключении: остальной чат не должен пропасть
    return rows


def exists(chat_id: str) -> bool:
    return _path(chat_id).exists()


def create(title: str = "") -> str:
    chat_id = secrets.token_hex(6)
    meta = {"meta": True, "title": title, "created": time.time(), "session": None}
    _path(chat_id).write_text(json.dumps(meta, ensure_ascii=False) + "\n", encoding="utf-8")
    return chat_id


def meta(chat_id: str) -> dict:
    rows = _read(_path(chat_id))
    return next((r for r in rows if r.get("meta")), {})


def set_meta(chat_id: str, **fields) -> None:
    p = _path(chat_id)
    rows = _read(p)
    for r in rows:
        if r.get("meta"):
            r.update(fields)
    p.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8")


def append(chat_id: str, role: str, text: str) -> dict:
    row = {"role": role, "text": text, "ts": time.time()}
    with _path(chat_id).open("a", encoding="utf-8") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    if role == "user" and not meta(chat_id).get("title"):
        set_meta(chat_id, title=re.sub(r"\s+", " ", text).strip()[:48])
    return row


def messages(chat_id: str) -> list[dict]:
    return [r for r in _read(_path(chat_id)) if not r.get("meta")]


def listing(query: str = "") -> list[dict]:
    out = []
    for p in chats_dir().glob("*.jsonl"):
        rows = _read(p)
        m = next((r for r in rows if r.get("meta")), {})
        msgs = [r for r in rows if not r.get("meta")]
        if query and query.lower() not in (m.get("title", "") + " ".join(r["text"] for r in msgs)).lower():
            continue
        out.append({"id": p.stem, "title": m.get("title") or "Новый чат",
                    "ts": msgs[-1]["ts"] if msgs else m.get("created", 0)})
    return sorted(out, key=lambda c: -c["ts"])


def delete(chat_id: str) -> bool:
    p = _path(chat_id)
    ok = p.exists()
    p.unlink(missing_ok=True)
    return ok


MODELS = ("", "haiku", "sonnet", "opus")


def cfg_with_model(cfg: dict, model: str) -> dict:
    """Конфиг мозга с моделью этого чата. Подписка у всех чатов одна, поэтому по умолчанию — модель голоса, а не сильнейшая."""
    if not model or model not in MODELS:
        return cfg
    return {**cfg, "brain": {**cfg["brain"], "model": model}}
