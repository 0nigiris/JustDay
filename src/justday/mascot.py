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

# Состояния, которые понимает островок. Скину их описывать не надо: он задаёт, как зверь выглядит,
# а как он при этом себя ведёт — дело движка, одинаковое для всех.
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

    def part(name: str) -> dict:
        got = raw.get(name)
        return dict(got) if isinstance(got, dict) else {}

    eyes = part("eyes")
    out = {
        "id": folder.name,
        "name": str(raw.get("name") or folder.name),
        "author": str(raw.get("author") or ""),
        "license": str(raw.get("license") or ""),
        "body": part("body"),
        "ears": part("ears"),
        "tail": part("tail"),
        "face": part("face"),
        "whiskers": part("whiskers"),
        "eyes": {
            "x": _clamp(eyes.get("x"), 0, 1, 0.5),
            "y": _clamp(eyes.get("y"), 0, 1, 0.44),
            "spacing": _clamp(eyes.get("spacing"), 0.02, 0.9, 0.3),
            "scale": _clamp(eyes.get("scale"), 0.05, 3, 0.5),
            "ink": str(eyes.get("ink") or "#2b1d14"),
        },
    }
    return out


def catalog() -> dict:
    """Все скины, какие есть, и какой выбран. Пусто — островок рисует своего, кодом."""
    skins = [s for s in (read(d) for d in _skin_dirs()) if s]
    want = str((config.load().get("island") or {}).get("mascot") or "")
    picked = next((s for s in skins if s["id"] == want), None)
    return {"skins": skins, "picked": picked, "want": want}
