"""Маскоты островка: сменные персонажи, которых подставляет кто угодно.

Почему скины, а не один персонаж. Один нарисованный зверёк — это вкус того, кто его нарисовал, и
переспорить его нельзя: кому-то нужен кот, кому-то лиса, кому-то совсем другое. Поэтому здесь не
персонаж, а **формат**: папка с картинкой и описанием. Движок один, персонажи подставляются без
единой строчки кода, и «сделай мне своего» — это папка, а не задача программисту.

Из чего состоит скин. Тело — настоящий рисунок: его можно нарисовать руками, сгенерировать или
взять готовый, и выглядеть он будет ровно настолько хорошо, насколько нарисован. Глаза — наши,
рисуются кодом поверх тела по двум координатам из описания.

Это разделение и есть вся хитрость. Рисовать одиннадцать состояний и десяток анимаций безделья
картинками — это сотни кадров, которых никто никогда не нарисует. Глаза же кодом умеют всё: тринадцать
форм, взгляд за курсором, моргание, прищур, спираль, когда дурно. Поэтому тело даёт красоту, а глаза
— жизнь, и ни одно из двух не упирается в другое.

Кадровая анимация тоже поддержана: состоянию можно дать свой файл (анимированный WebP или GIF), и
тогда он просто играется вместо тела. Так скин может расти от «одна картинка» до «нарисовано всё».
"""
from __future__ import annotations

import tomllib

from . import config

DIRS = (config.HOME / ".local/share/justday/mascots",
        config.REPO_DIR / "data/mascots")

# Состояния, которые понимает островок. Скин может описать любое их подмножество: чего нет, то
# берётся от тела и глаз по умолчанию — персонаж без состояния «упёрся в лимит» не ломается, он
# просто не меняет при этом лица.
STATES = ("idle", "working", "thinking", "searching", "listening", "talking",
          "approval", "question", "error", "finished", "ratelimit", "sleeping", "dizzy")


def _skin_dirs() -> list:
    out = []
    for base in DIRS:
        try:
            for item in sorted(base.iterdir()):
                if item.is_dir() and (item / "skin.toml").exists():
                    out.append(item)
        except OSError:
            continue
    return out


def _clamp(value, low: float, high: float, fallback: float) -> float:
    try:
        return max(low, min(high, float(value)))
    except (TypeError, ValueError):
        return fallback


def read(folder) -> dict | None:
    """Прочитать один скин. Кривой скин — не беда: он просто не появится в списке.

    Проверяем здесь, а не в островке, нарочно: QML не умеет ни TOML, ни проверять, что файл на
    месте, а показывать персонажа, половина которого не нашлась, хуже, чем не показывать вовсе.
    """
    try:
        with open(folder / "skin.toml", "rb") as fh:
            raw = tomllib.load(fh)
    except (OSError, ValueError):
        return None

    body = str(raw.get("image") or "body.png")
    body_path = folder / body
    if not body_path.exists():
        return None

    eyes = raw.get("eyes") or {}
    at = eyes.get("at") or [0.5, 0.42]
    try:
        eye_x, eye_y = float(at[0]), float(at[1])
    except (TypeError, ValueError, IndexError):
        eye_x, eye_y = 0.5, 0.42

    # Кадровые состояния: файл на состояние. Чего нет — рисуется телом и глазами.
    frames = {}
    for state, name in (raw.get("states") or {}).items():
        if state not in STATES:
            continue
        path = folder / str(name)
        if path.exists():
            frames[state] = str(path)

    # Безделье: несколько файлов, из которых движок выбирает наугад. Это и есть «много анимаций»:
    # одна и та же, повторяясь, перестаёт быть жизнью и становится индикатором.
    idles = []
    for name in (raw.get("idle") or []):
        path = folder / str(name)
        if path.exists():
            idles.append(str(path))

    return {
        "id": folder.name,
        "name": str(raw.get("name") or folder.name),
        "author": str(raw.get("author") or ""),
        "license": str(raw.get("license") or ""),
        "body": str(body_path),
        "eyes": {
            "x": _clamp(eye_x, 0, 1, 0.5),
            "y": _clamp(eye_y, 0, 1, 0.42),
            "spacing": _clamp(eyes.get("spacing"), 0.02, 0.9, 0.2),
            "scale": _clamp(eyes.get("scale"), 0.1, 3, 1.0),
            "ink": str(eyes.get("ink") or "#1a1412"),
            "show": eyes.get("show") is not False,
        },
        "motion": {
            "breathe": _clamp((raw.get("motion") or {}).get("breathe"), 0, 3, 1.0),
            "bob": _clamp((raw.get("motion") or {}).get("bob"), 0, 3, 1.0),
            "squish": _clamp((raw.get("motion") or {}).get("squish"), 0, 3, 1.0),
            "tilt": _clamp((raw.get("motion") or {}).get("tilt"), 0, 3, 1.0),
        },
        "states": frames,
        "idle": idles,
    }


def catalog() -> dict:
    """Все скины, какие есть, и какой выбран. Пусто — островок рисует своего, кодом."""
    skins = [s for s in (read(d) for d in _skin_dirs()) if s]
    want = str((config.load().get("island") or {}).get("mascot") or "")
    picked = next((s for s in skins if s["id"] == want), None)
    return {"skins": skins, "picked": picked, "want": want}
