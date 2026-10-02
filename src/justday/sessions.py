"""Живые сессии Claude Code: что каждая из них делает прямо сейчас.

Зачем. Сейчас островок говорит «Клод работает ×3» — и это всё, что человек знает о трёх сессиях,
которые в этот момент правят его файлы. Три работают, одна, может быть, застряла, другая делает не
то, — не видно ничего. «Работает» — это не сведения, это только обещание, что что-то происходит.

Поэтому здесь берётся то, что и так лежит на диске: Claude Code ведёт стенограмму каждой сессии
построчно, и в ней видно каждый вызов инструмента. Хвоста в несколько сотен строк хватает, чтобы
сказать, что сессия читает, что правит и что запускает.

Два решения, которые стоит объяснить.

Читаем **хвост**, а не файл: стенограмма растёт до десятков мегабайт, и читать её целиком ради
последней строки — это десятая доля секунды на каждую сессию и ничего взамен.

Показываем **глаголами**, а не именами инструментов. «Read» и «Edit» — слова для того, кто писал
агента; человеку нужно «читает» и «правит», и он должен понимать их, ни разу не открыв документацию.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from pathlib import Path

HOME = Path.home()
TAIL_BYTES = 256 * 1024      # хвост стенограммы: сотни строк, доли миллисекунды
MAX_STEPS = 12

# Инструмент → что он значит по-человечески. Чего нет в таблице, показывается своим именем: соврать
# тут хуже, чем признаться, что мы такого не знаем.
VERBS = {
    "Read": ("читает", "file_path"),
    "Edit": ("правит", "file_path"),
    "Write": ("пишет", "file_path"),
    "NotebookEdit": ("правит", "notebook_path"),
    "Bash": ("запускает", "command"),
    "Grep": ("ищет", "pattern"),
    "Glob": ("ищет файлы", "pattern"),
    "WebFetch": ("смотрит", "url"),
    "WebSearch": ("ищет в сети", "query"),
    "Task": ("поручает", "description"),
    "TodoWrite": ("планирует", ""),
    "AskUserQuestion": ("спрашивает", ""),
}


def _short(value: str, limit: int = 70) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1] + "…"


def _pretty(name: str, args: dict) -> dict:
    verb, key = VERBS.get(name, (name.lower(), ""))
    what = args.get(key, "") if key else ""
    if key and key.endswith("path"):
        # Путь целиком в строку не влезает и не нужен: человек узнаёт свой файл по имени.
        what = os.path.basename(str(what)) or str(what)
    return {"verb": verb, "what": _short(what), "tool": name}


def _tail(path: Path) -> list[str]:
    try:
        size = path.stat().st_size
        with open(path, "rb") as fh:
            if size > TAIL_BYTES:
                fh.seek(size - TAIL_BYTES)
                fh.readline()          # первая строка после прыжка почти наверняка обрезана
            return fh.read().decode("utf-8", "replace").splitlines()
    except OSError:
        return []


def steps_of(session_id: str) -> list[dict]:
    """Последние шаги сессии, от старых к новым."""
    hits = list((HOME / ".claude" / "projects").glob(f"*/{session_id}.jsonl"))
    if not hits:
        return []
    out: list[dict] = []
    for line in _tail(max(hits, key=lambda p: p.stat().st_mtime)):
        if '"tool_use"' not in line:
            continue
        try:
            msg = (json.loads(line).get("message") or {}).get("content")
        except ValueError:
            continue
        if not isinstance(msg, list):
            continue
        for c in msg:
            if isinstance(c, dict) and c.get("type") == "tool_use":
                out.append(_pretty(str(c.get("name", "")), c.get("input") or {}))
    return out[-MAX_STEPS:]


def live(claude: str = "claude") -> list[dict]:
    """Все сессии Claude Code на этой машине и чем каждая занята.

    Своя сессия мозга тоже здесь: она такая же сессия, и прятать её значило бы врать о том, что
    происходит на машине.
    """
    try:
        # Без --all: нас занимает то, что работает сейчас. Законченные сессии остаются в
        # стенограммах и в `justday claude result`, а в живом списке им место ровно до тех пор,
        # пока они живы, — иначе через неделю там будут сотни строк из позапрошлого вторника.
        raw = subprocess.run([claude, "agents", "--json"],
                             capture_output=True, text=True, timeout=15).stdout
        agents = json.loads(raw or "[]")
    except (OSError, subprocess.SubprocessError, ValueError):
        return []

    now = time.time()
    out = []
    for a in agents:
        sid = str(a.get("sessionId") or "")
        if not sid:
            continue
        steps = steps_of(sid)
        started = float(a.get("startedAt") or 0) / 1000
        out.append({
            "id": sid,
            "short": sid[:8],
            "name": a.get("name") or "",
            "cwd": str(a.get("cwd") or ""),
            "where": os.path.basename(str(a.get("cwd") or "")) or "/",
            "status": a.get("status") or "",
            "busy": a.get("status") == "busy",
            "pid": a.get("pid"),
            "minutes": round((now - started) / 60, 1) if started else 0,
            "now": steps[-1] if steps else None,
            "steps": steps,
        })
    # Занятые первыми: про них и спрашивают. Внутри — кто дольше работает, тот выше.
    out.sort(key=lambda s: (not s["busy"], -s["minutes"]))
    return out
