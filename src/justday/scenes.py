"""Сценарии: несколько привычных действий одной фразой.

«Я сел работать» — это каждый раз одно и то же: открыть редактор и мессенджер,
закрыть игру, приглушить музыку, попросить не отвлекать. Просить об этом модель
дорого и медленно: она каждый раз заново придумывает то, что человек и так
делает по шаблону.

Сценарии описываются в config.toml и выполняются мгновенным путём — без модели
и без сети. Команды в них — списки аргументов, а не строки для оболочки: файл
пишет хозяин машины, но и он не должен однажды получить `rm -rf` из-за кавычки
не на месте.
"""
from __future__ import annotations

import re
import subprocess
from typing import Any

from . import config, desktop
from .i18n import t


def _norm(text: str) -> str:
    text = re.sub(r"[^\w\s]", " ", str(text or "").lower().replace("ё", "е"))
    return re.sub(r"\s+", " ", text).strip()


def all_scenes() -> list[dict[str, Any]]:
    """Сценарии из настроек, в порядке описания."""
    raw = config.load().get("scenes") or []
    if isinstance(raw, dict):  # [scenes.работа] вместо [[scenes]] — тоже понятная запись
        raw = [{"id": key, **value} for key, value in raw.items()]
    out = []
    for i, item in enumerate(raw):
        if not isinstance(item, dict):
            continue
        name = str(item.get("name") or item.get("id") or f"Сценарий {i + 1}")
        out.append({
            "id": str(item.get("id") or _norm(name).replace(" ", "-") or f"scene-{i + 1}"),
            "name": name,
            "phrases": [str(p) for p in (item.get("phrases") or [])],
            "open": [str(a) for a in (item.get("open") or [])],
            "close": [str(a) for a in (item.get("close") or [])],
            "run": [list(map(str, cmd)) for cmd in (item.get("run") or []) if isinstance(cmd, list)],
            "music": str(item.get("music") or ""),
            "silent": item.get("silent"),
            "say": str(item.get("say") or ""),
            "icon": str(item.get("icon") or "lucide:zap"),
        })
    return out


def match(text: str) -> dict[str, Any] | None:
    """Сценарий, о котором просят этой фразой. Совпадение целиком: «включи
    рабочий режим и заодно скажи погоду» — это уже разговор, а не кнопка."""
    said = _norm(text)
    if not said:
        return None
    for scene in all_scenes():
        for phrase in [*scene["phrases"], scene["name"]]:
            if said == _norm(phrase):
                return scene
    return None


def by_id(scene_id: str) -> dict[str, Any] | None:
    return next((s for s in all_scenes() if s["id"] == scene_id), None)


def _app_id(name: str) -> str | None:
    """Приложение по тому, как его называет человек: сначала синонимы, потом поиск."""
    aliases = {k.lower(): v for k, v in config.load()["apps"]["aliases"].items()}
    key = name.strip().lower()
    if key in aliases:
        return aliases[key]
    found = desktop.find_apps(name, 1)
    return found[0]["id"] if found and found[0]["score"] >= 0.8 else None


def run(scene: dict[str, Any]) -> dict[str, Any]:
    """Выполнить сценарий. Возвращает, что удалось, — ассистент скажет это вслух."""
    opened: list[str] = []
    closed: list[str] = []
    failed: list[str] = []

    for name in scene["close"]:
        if desktop.windows("close", name):
            closed.append(name)
    for name in scene["open"]:
        app = _app_id(name)
        if app:
            desktop.launch_app_id(app)
            opened.append(name)
        else:
            failed.append(name)
    for argv in scene["run"]:
        try:
            done = subprocess.run(argv, capture_output=True, timeout=20)
            if done.returncode != 0:
                failed.append(" ".join(argv[:2]))
        except (OSError, subprocess.SubprocessError):
            failed.append(" ".join(argv[:2]))

    return {"ok": True, "scene": scene["name"], "opened": opened, "closed": closed, "failed": failed}


def save(scene: dict[str, Any]) -> dict[str, Any]:
    """Дописать сценарий в config.toml — так его заводит сам ассистент.

    Файл принадлежит человеку: остальное в нём не трогаем, новый сценарий
    дописывается в конец отдельной таблицей, как если бы его написали руками.
    Сценарий с тем же именем заменяется целиком.
    """
    name = " ".join(str(scene.get("name") or "").split())
    if not name:
        raise ValueError("у сценария должно быть имя")
    lines = []
    try:
        lines = config.CONFIG_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        pass
    lines = _drop(lines, name)
    block = ["", "[[scenes]]", f'name = "{name}"']
    for key in ("phrases", "open", "close"):
        values = [str(v) for v in (scene.get(key) or []) if str(v).strip()]
        if values:
            block.append(f"{key} = [" + ", ".join(f'"{v}"' for v in values) + "]")
    # Команд (`run`) здесь намеренно нет: их пишет человек руками, осознанно.
    for key in ("music", "say"):
        if scene.get(key):
            block.append(f'{key} = "{scene[key]}"')
    if scene.get("silent") is not None:
        block.append(f"silent = {'true' if scene['silent'] else 'false'}")
    config.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    config.CONFIG_FILE.write_text("\n".join([*lines, *block]).strip() + "\n", encoding="utf-8")
    return {"ok": True, "name": name, "file": str(config.CONFIG_FILE)}


def _drop(lines: list[str], name: str) -> list[str]:
    """Убрать прежний сценарий с таким именем — и только его."""
    out: list[str] = []
    i = 0
    same = re.compile(rf'\s*name\s*=\s*"{re.escape(name)}"\s*$')
    while i < len(lines):
        if lines[i].strip() != "[[scenes]]":
            out.append(lines[i])
            i += 1
            continue
        end = i + 1
        while end < len(lines) and not lines[end].lstrip().startswith("["):
            end += 1
        block = lines[i:end]
        if not any(same.match(b) for b in block):
            out += block
        i = end
    while out and not out[-1].strip():
        out.pop()
    return out


def forget(name: str) -> dict[str, Any]:
    """Убрать сценарий из config.toml."""
    try:
        lines = config.CONFIG_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return {"ok": False, "error": "нет файла настроек"}
    kept = _drop(lines, name)
    if len(kept) == len(lines):
        return {"ok": False, "error": f"сценария «{name}» нет"}
    config.CONFIG_FILE.write_text("\n".join(kept).strip() + "\n", encoding="utf-8")
    return {"ok": True, "name": name}


def summary(result: dict[str, Any]) -> str:
    """Одна фраза о том, что произошло: её и говорят вслух."""
    parts = []
    if result.get("opened"):
        parts.append(t("открыл {what}", what=", ".join(result["opened"])))
    if result.get("closed"):
        parts.append(t("закрыл {what}", what=", ".join(result["closed"])))
    said = result.get("scene", "")
    line = f"{said}: {', '.join(parts)}" if parts else said
    if result.get("failed"):
        line += t(" (не нашёл: {what})", what=", ".join(result["failed"]))
    return line
