"""The address book JustDay learns: who "мама" or "Илья из Польши" is and how to reach them.

A local JSON file (~/.local/share/justday/contacts.json). The brain reads and updates it through
`justday contacts …`; the private mail lane resolves e-mail addresses from it without the cloud.
"""
from __future__ import annotations

import difflib
import json
import re
import time

from . import config

PATH = config.DATA_DIR / "contacts.json"
FIELDS = ("name", "aliases", "relation", "note", "email", "discord", "telegram", "whatsapp", "phone", "preferred")


def _norm(s: str) -> str:
    return re.sub(r"[^\wа-яё@.]+", " ", s.lower().replace("ё", "е")).strip()


def load() -> list[dict]:
    try:
        return json.loads(PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []


def save(items: list[dict]) -> None:
    PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = PATH.with_suffix(".tmp")
    tmp.write_text(json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(PATH)


def _keys(c: dict) -> list[str]:
    return [_norm(c.get("name", ""))] + [_norm(a) for a in c.get("aliases", [])]


def find(query: str) -> list[dict]:
    """All contacts that could be meant, best first. Several results = ask the user which one."""
    q = _norm(query)
    if not q:
        return []
    scored = []
    for c in load():
        best = 0.0
        for k in _keys(c):
            if not k:
                continue
            if q == k:
                best = max(best, 1.0)
            elif q in k.split() or k in q.split() or q in k or k in q:
                best = max(best, 0.8)
            else:
                best = max(best, difflib.SequenceMatcher(None, q, k).ratio() * 0.9)
        hay = _norm(" ".join(str(c.get(f, "")) for f in ("note", "relation", "discord", "email")))
        if q in hay:
            best = max(best, 0.7)
        if best >= 0.72:
            scored.append((best, c))
    scored.sort(key=lambda x: -x[0])
    return [c for _, c in scored]


def upsert(name: str, **fields) -> dict:
    """Create or update a contact by exact name (aliases are merged, other fields overwrite)."""
    items = load()
    target = next((c for c in items if _norm(c.get("name", "")) == _norm(name)), None)
    if target is None:
        target = {"name": name, "aliases": [], "created": time.strftime("%Y-%m-%d")}
        items.append(target)
    for k, v in fields.items():
        if k not in FIELDS or v in (None, ""):
            continue
        if k == "aliases":
            new = [a.strip() for a in (v if isinstance(v, list) else str(v).split(",")) if a.strip()]
            target["aliases"] = sorted(set(target.get("aliases", [])) | set(new))
        else:
            target[k] = v
    target["updated"] = time.strftime("%Y-%m-%d")
    save(items)
    return target


def forget(name: str) -> bool:
    items = load()
    keep = [c for c in items if _norm(c.get("name", "")) != _norm(name)]
    save(keep)
    return len(keep) != len(items)


def email_for(query: str) -> tuple[str, str]:
    """(address, display name) for the mail lane, or ("", "") when unknown or ambiguous."""
    matches = [c for c in find(query) if c.get("email")]
    if len(matches) == 1 or (matches and _norm(query) in _keys(matches[0])):
        return matches[0]["email"], matches[0]["name"]
    return "", ""
