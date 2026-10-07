"""«Громкость Discord 50, а музыку 20» одной фразой, мимо модели (Р-48).

Раньше такая фраза доходила до мозга, и тот делал инструменты по очереди, теряя вторую половину; быстрый путь
понимал только общую громкость. Здесь фраза режется на части, и если хоть одну из них нельзя выполнить
(программа не играет звук, непонятная цель) — не делается ничего, фраза уходит мозгу целиком: половина команды
хуже, чем никакая."""
from __future__ import annotations

import json
import re
import subprocess
from dataclasses import dataclass

from . import fastpath

SPLIT = re.compile(r"\s*(?:[,;]|\bи\b|\bа\b|\bпотом\b|\bзатем\b|\bплюс\b|\band\b|\bthen\b)\s*", re.I)
PART = re.compile(r"^(?:(?:сделай|поставь|установи|выставь|задай|set)\s+)?(?:(?:громкость|звук|volume)\s+)?"
                  r"(?P<t>.+?)\s+(?:(?:на|до|to|at)\s+)?(?P<n>\d{1,3})\s*(?:процент\w*|percent|%)?$")
MUSIC = re.compile(r"^(?:музык\w*|песн\w*|трек\w*|плеер\w*|music|player)$")
SYSTEM = re.compile(r"^(?:систем\w*|общ\w+|весь звук|всё|все|компьютер\w*|звук|system|master|overall)$")
NOT_A_TARGET = {"на", "до", "в", "во", "to", "at"}
MAX_LEVEL = 200  # выше ста — усиление; у программ потолок 150 (дальше PipeWire хрипит), у плеера 200 вместе с выравниванием


@dataclass
class Action:
    kind: str            # "music" | "system" | "stream"
    level: int
    label: str
    streams: tuple[int, ...] = ()


def _flat(s: str) -> str:
    return re.sub(r"[^a-z0-9а-я]+", "", str(s or "").lower().replace("ё", "е"))


def sink_inputs() -> list[dict]:
    """Потоки воспроизведения PipeWire: у каждой программы своя громкость."""
    try:
        out = subprocess.run(["pactl", "--format=json", "list", "sink-inputs"], capture_output=True, text=True,
                             timeout=3).stdout
        return json.loads(out or "[]")
    except (OSError, ValueError, subprocess.SubprocessError):
        return []


def streams_for(target: str, inputs: list[dict]) -> tuple[list[int], str]:
    """Индексы потоков, которые принадлежат названной программе, и её имя для ответа."""
    app = fastpath._app(target)
    names = {_flat(target), _flat(fastpath.RU_NAMES.get(target, "")), _flat(fastpath._translit(target))}
    label = target
    if app:
        names |= {_flat(app["name"]), _flat(app["id"].rsplit(".", 1)[-1])}
        label = app["name"]
    names = {n for n in names if len(n) > 2}
    hits = []
    for si in inputs:
        p = si.get("properties") or {}
        mine = [_flat(p.get(k)) for k in ("application.name", "application.process.binary", "node.name")]
        if any(m and any(m in n or n in m for n in names) for m in mine):
            hits.append(int(si["index"]))
    return hits, label


def plan(text: str, inputs: list[dict] | None = None) -> list[Action] | None:
    """Разобранная и проверенная фраза про громкость или None — «это не мне»."""
    low = text.lower().replace("ё", "е")
    if not re.search(r"\d", low):
        return None
    parts = [p for p in (fastpath._clean(x) for x in SPLIT.split(low)) if p]
    if not parts:
        return None
    actions: list[Action] = []
    pending: list[tuple[str, int]] = []
    for p in parts:
        m = PART.match(p)
        target = m.group("t").strip() if m else ""
        if m and target in NOT_A_TARGET:  # «звук на 60»: слово «звук» съелось как приставка — это и есть цель
            target = "звук"
        if not m or target in NOT_A_TARGET or not 0 <= int(m.group("n")) <= MAX_LEVEL:
            return None
        pending.append((target, int(m.group("n"))))
    # Одна часть про программу — только если сказано про громкость: «Discord на 50» без этого слова бывает лишь
    # в составной фразе, а «поставь будильник на 7» не должно дёргать звук.
    named = re.search(r"громк|звук|volume", low) or len(pending) > 1
    if not named and not all(MUSIC.match(t) or SYSTEM.match(t) for t, _ in pending):
        return None
    inputs = sink_inputs() if inputs is None and any(not (MUSIC.match(t) or SYSTEM.match(t)) for t, _ in pending) \
        else (inputs or [])
    for target, level in pending:
        if MUSIC.match(target):
            actions.append(Action("music", min(level, 200), "музыка"))
        elif SYSTEM.match(target):
            actions.append(Action("system", min(level, 100), "звук"))
        else:
            hits, _ = streams_for(target, inputs)
            if not hits:
                return None
            actions.append(Action("stream", min(level, 150), target, tuple(hits)))
    if len(actions) == 1 and actions[0].kind == "system":
        return None  # «громкость на 40» — старый быстрый путь, он молча делает то же самое
    return actions


def apply(action: Action) -> bool:
    """Всё, что делается командой; громкость плеера — дело демона."""
    if action.kind == "system":
        cmd = ["wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{action.level}%"]
        return subprocess.run(cmd, capture_output=True, timeout=5).returncode == 0
    ok = True
    for index in action.streams:
        r = subprocess.run(["pactl", "set-sink-input-volume", str(index), f"{action.level}%"], capture_output=True,
                           timeout=5)
        ok = ok and r.returncode == 0
    return ok


def phrase(actions: list[Action]) -> str:
    """Один ответ на всё: «Discord 50, музыка 20»."""
    return ", ".join(f"{a.label} {a.level}" for a in actions)
