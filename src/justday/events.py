"""Structured event log (JSONL) + small persistent state file."""
from __future__ import annotations

import json
import logging
import time
from typing import Any

from . import config

log = logging.getLogger("justday")


_listeners: list = []


def subscribe(fn) -> None:
    """fn(kind, data) is called for every event in the emitting thread (the daemon forwards them to the island)."""
    _listeners.append(fn)


def emit(kind: str, **data: Any) -> None:
    """Append one event. Everything JustDay hears, says and does goes through here."""
    for fn in _listeners:
        try:
            fn(kind, data)
        except Exception:
            log.exception("event listener failed")
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "kind": kind, **data}
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    with config.EVENTS_FILE.open("a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    short = {k: (v[:200] + "…" if isinstance(v, str) and len(v) > 200 else v) for k, v in data.items()}
    log.info("%s %s", kind, json.dumps(short, ensure_ascii=False))


def load_state() -> dict:
    try:
        return json.loads(config.STATE_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(**updates: Any) -> dict:
    state = load_state()
    state.update(updates)
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = config.STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2))
    tmp.replace(config.STATE_FILE)
    return state
