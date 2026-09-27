"""Планы и заметки — в Obsidian, а не в своей базе.

У человека уже есть хранилище, в котором он пишет: своё держать рядом значило бы
разделить записи надвое. JustDay пишет в тот же каталог обычным markdown — файл
открывается в Obsidian, правится руками, и ассистент видит правки сразу.

Хранилище находится само: Obsidian хранит список открытых vault'ов в своём
конфиге. Его можно задать и руками — ``[notes] vault`` в config.toml.
"""
from __future__ import annotations

import json
import re
import time
from pathlib import Path

from . import config

DONE = re.compile(r"^\s*[-*]\s*\[( |x|X)\]\s*(.+?)\s*$")
DAY = re.compile(r"^##\s*(\d{4}-\d{2}-\d{2})")


def _obsidian_config() -> Path:
    home = Path.home()
    return home / ".var/app/md.obsidian.Obsidian/config/obsidian/obsidian.json"


def vault() -> Path | None:
    """Каталог хранилища: из настроек JustDay, иначе — открытый в Obsidian."""
    told = str(config.load()["notes"].get("vault") or "").strip()
    if told:
        path = Path(told).expanduser()
        return path if path.is_dir() else None
    for where in (_obsidian_config(), Path.home() / ".config/obsidian/obsidian.json"):
        try:
            vaults = json.loads(where.read_text(encoding="utf-8")).get("vaults") or {}
        except (OSError, ValueError):
            continue
        # открытый сейчас — первый кандидат, иначе самый свежий по времени
        ordered = sorted(vaults.values(), key=lambda v: (bool(v.get("open")), v.get("ts", 0)), reverse=True)
        for item in ordered:
            path = Path(str(item.get("path", "")))
            if path.is_dir():
                return path
    return None


def plans_path() -> Path:
    """Файл с планами внутри хранилища (создаётся при первой записи)."""
    root = vault()
    if root is None:
        raise RuntimeError("хранилище Obsidian не найдено: укажите [notes] vault в config.toml")
    name = str(config.load()["notes"].get("plans") or "Планы.md")
    path = (root / name).resolve()
    if root.resolve() not in path.parents and path != root.resolve():
        raise RuntimeError("файл планов должен лежать внутри хранилища")
    return path


def _read() -> list[str]:
    try:
        return plans_path().read_text(encoding="utf-8").splitlines()
    except OSError:
        return []


def _write(lines: list[str]) -> None:
    path = plans_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(lines).rstrip() + "\n", encoding="utf-8")


def add(text: str, note: str = "") -> dict:
    """Новый пункт под сегодняшним числом. `note` — откуда он взялся («с телефона»)."""
    text = " ".join(str(text or "").split())
    if not text:
        raise ValueError("пустой план")
    today = time.strftime("%Y-%m-%d")
    lines = _read() or ["# Планы", "", "Список ведёт JustDay; правьте руками как обычный markdown.", ""]
    mark = f"- [ ] {text}" + (f"  *({note})*" if note else "")
    try:  # под сегодняшний заголовок, если он уже есть
        at = lines.index(f"## {today}")
        end = at + 1
        while end < len(lines) and not lines[end].startswith("## "):
            end += 1
        while end > at + 1 and not lines[end - 1].strip():
            end -= 1
        lines.insert(end, mark)
    except ValueError:
        if lines and lines[-1].strip():
            lines.append("")
        lines += [f"## {today}", mark, ""]
    _write(lines)
    return {"ok": True, "text": text, "file": str(plans_path())}


def items(only_open: bool = False) -> list[dict]:
    """Пункты списка по порядку: номер, текст, выполнен ли, под каким числом."""
    out: list[dict] = []
    day = ""
    for line in _read():
        got = DAY.match(line)
        if got:
            day = got.group(1)
            continue
        hit = DONE.match(line)
        if hit:
            done = hit.group(1).lower() == "x"
            if only_open and done:
                continue
            text, _, note = hit.group(2).partition("*(")
            out.append({"n": len(out) + 1, "text": text.strip(), "done": done, "day": day,
                        "note": note.rstrip(")*").strip()})
    return out


def mark_done(which: str) -> dict:
    """Отметить выполненным: по номеру из списка или по части текста."""
    lines = _read()
    wanted = str(which or "").strip().lower()
    numbers = 0
    target = int(wanted) if wanted.isdigit() else 0
    for i, line in enumerate(lines):
        hit = DONE.match(line)
        if not hit or hit.group(1).lower() == "x":
            continue
        numbers += 1
        if (target and numbers == target) or (not target and wanted and wanted in hit.group(2).lower()):
            lines[i] = line.replace("[ ]", "[x]", 1)
            _write(lines)
            return {"ok": True, "text": hit.group(2)}
    return {"ok": False, "error": "такого пункта нет"}


def note(title: str, text: str, folder: str = "") -> dict:
    """Отдельная заметка в хранилище — для того, что в список пунктов не помещается."""
    root = vault()
    if root is None:
        raise RuntimeError("хранилище Obsidian не найдено")
    safe = re.sub(r"[\\/:*?\"<>|#^\[\]]", " ", str(title or "").strip()) or time.strftime("Заметка %Y-%m-%d %H%M")
    path = (root / folder / f"{safe.strip()[:80]}.md").resolve()
    if root.resolve() not in path.parents:
        raise RuntimeError("заметка должна лежать внутри хранилища")
    path.parent.mkdir(parents=True, exist_ok=True)
    head = "" if path.exists() else f"# {safe.strip()}\n\n"
    with path.open("a", encoding="utf-8") as fh:
        fh.write(head + str(text or "").strip() + "\n")
    return {"ok": True, "file": str(path)}


def open_in_obsidian(file: str = "") -> str:
    """Ссылка obsidian://, открывающая хранилище (и нужный файл) в приложении."""
    from urllib.parse import quote

    root = vault()
    if root is None:
        return ""
    name = quote(root.name)
    if not file:
        return f"obsidian://open?vault={name}"
    rel = Path(file).resolve().relative_to(root.resolve())
    return f"obsidian://open?vault={name}&file={quote(str(rel.with_suffix('')))}"
