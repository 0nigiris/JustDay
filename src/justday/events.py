"""Structured event log (JSONL) + small persistent state file."""
from __future__ import annotations

import contextlib
import fcntl
import json
import logging
import os
import tempfile
import time
from typing import Any

from . import config

log = logging.getLogger("justday")


_listeners: list = []
_tightened = False


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
    # `ts` — для глаз, с точностью до секунды; `t` — для замеров: от конца фразы до `heard` и до первого `say`
    # по журналу с секундами не посчитать (пункт 16 плана: «не измерено»).
    rec = {"ts": time.strftime("%Y-%m-%dT%H:%M:%S"), "t": round(time.time(), 3), "kind": kind, **data}
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    # В журнале всё сказанное вслух и начало аргументов инструментов (в том числе набранное `act type`): читать его
    # должен один человек. Создаём сразу с 0600, а уже лежащий открытый файл подтягиваем один раз за процесс.
    fd = os.open(config.EVENTS_FILE, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    global _tightened
    if not _tightened:
        _tightened = True
        with contextlib.suppress(OSError):
            os.fchmod(fd, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    short = {k: (v[:200] + "…" if isinstance(v, str) and len(v) > 200 else v) for k, v in data.items()}
    log.info("%s %s", kind, json.dumps(short, ensure_ascii=False))


def read(day: str = "") -> list[dict[str, Any]]:
    """События за один день (YYYY-MM-DD) или все, если день не назван.

    Журнал дописывается построчно и переживает падения, поэтому последняя
    строка бывает оборванной — на чтении это не должно сказываться.
    """
    out: list[dict[str, Any]] = []
    try:
        lines = config.EVENTS_FILE.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return out
    for line in lines:
        if not line.startswith("{"):
            continue
        try:
            record = json.loads(line)
        except ValueError:
            continue
        if not day or str(record.get("ts", "")).startswith(day):
            out.append(record)
    return out


def load_state() -> dict:
    try:
        return json.loads(config.STATE_FILE.read_text())
    except (FileNotFoundError, json.JSONDecodeError):
        return {}


def save_state(**updates: Any) -> dict:
    """Пишут сюда четверо — цикл событий, поток почты, executor и CLI. С общим `.tmp` и без замка
    один забирал файл из-под другого: `FileNotFoundError` на replace убивал `_housekeeping`, а
    чужие ключи терялись между чтением и записью (Р-14). Замок общий для процессов, tmp у каждого свой."""
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    with open(config.STATE_DIR / "state.lock", "w") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        state = load_state()
        state.update(updates)
        fd, tmp = tempfile.mkstemp(dir=config.STATE_DIR, prefix=".state.", suffix=".tmp")
        with os.fdopen(fd, "w") as f:
            f.write(json.dumps(state, ensure_ascii=False, indent=2))
        os.replace(tmp, config.STATE_FILE)
    return state
