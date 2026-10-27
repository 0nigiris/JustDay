"""Модули JustDay, которые можно перезапустить по одному, и обновление без терминала.

Беда. Любая правка кончалась `systemctl restart justday justday-ui`: на несколько секунд пропадал
док, а он должен быть всегда. Перезапускать надо ровно то, что сломалось: голос — голос, демон —
демон. Остров по умолчанию не перезапускается совсем: Quickshell сам перечитывает QML, когда файл
меняется, поэтому «перерисовать остров» — это `touch`, а не смерть процесса.
"""
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

from . import config

# id → (название, юнит или None, можно ли тронуть, не уронив док)
MODULES: dict[str, tuple[str, str | None]] = {
    "daemon": ("Мозг и команды", "justday.service"),
    "island": ("Остров, док и лоток (перерисовать)", None),
    "voice": ("Распознавание речи", "justday-voice.service"),
    "tts": ("Голос нейросети", "justday-chatterbox.service"),
    "ollama": ("Местная модель", "justday-ollama.service"),
}
UPDATE_UNIT = "justday-update"


def _systemctl(*args: str) -> subprocess.CompletedProcess:
    return subprocess.run(["systemctl", "--user", *args], capture_output=True, text=True, timeout=30)


def _installed(unit: str) -> bool:
    return (Path.home() / ".config/systemd/user" / unit).exists()


def listing() -> list[dict]:
    out = []
    for mid, (title, unit) in MODULES.items():
        if unit and not _installed(unit):
            continue
        state = _systemctl("is-active", unit).stdout.strip() if unit else "active"
        out.append({"id": mid, "title": title, "state": state, "active": state == "active"})
    return out


def restart(mid: str) -> dict:
    """Перезапустить один модуль. Остров только перерисовывается: док остаётся на экране."""
    if mid not in MODULES:
        return {"ok": False, "error": f"нет такого модуля: {mid}"}
    unit = MODULES[mid][1]
    if unit is None:
        shell = config.REPO_DIR / "island" / "shell.qml"
        try:
            os.utime(shell)   # Quickshell следит за файлами и перечитывает сам
        except OSError as e:
            return {"ok": False, "error": str(e)}
        return {"ok": True, "how": "reload"}
    done = _systemctl("restart", unit)
    return {"ok": done.returncode == 0, "how": "restart", "error": done.stderr.strip()[:200]}


def update_in_background() -> dict:
    """`justday update` отдельной службой systemd: она переживает рестарт демона, который сама и вызывает,
    и ничего не открывает на экране. Остров не перезапускается (`JUSTDAY_KEEP_UI`), QML подхватится сам.
    По окончании приходит обычное уведомление."""
    cli = shutil.which("justday")
    if not cli or not shutil.which("systemd-run"):
        return {"ok": False, "error": "нет justday или systemd-run"}
    if _systemctl("is-active", f"{UPDATE_UNIT}.service").stdout.strip() == "active":
        return {"ok": True, "already": True}
    notify = ("notify-send -a JustDay -i software-update-available JustDay "
              "\"$( [ $rc = 0 ] && echo 'Обновление готово' || echo 'Обновление не удалось: justday update' )\"")
    script = f'{cli} update >"{config.STATE_DIR}/update.log" 2>&1; rc=$?; {notify}'
    done = subprocess.run(
        ["systemd-run", "--user", "--collect", f"--unit={UPDATE_UNIT}", "--setenv=JUSTDAY_KEEP_UI=1",
         "--description=JustDay: обновление", "bash", "-c", script],
        capture_output=True, text=True, timeout=15)
    return {"ok": done.returncode == 0, "error": done.stderr.strip()[:200]}


def parts_in_background(names: list[str]) -> dict:
    """Доставить необязательные части (речь, голос, CUDA) службой systemd: этап 2 установки идёт в фоне, пока
    человек уже пользуется островом. Имена проверяются по списку: в командную строку попадает только известное."""
    from . import parts

    bad = [n for n in names if n not in parts.PARTS]
    cli = shutil.which("justday")
    if bad or not names:
        return {"ok": False, "error": f"неизвестные части: {', '.join(bad) or 'не названы'}"}
    if not cli or not shutil.which("systemd-run"):
        return {"ok": False, "error": "нет justday или systemd-run"}
    if _systemctl("is-active", "justday-parts.service").stdout.strip() == "active":
        return {"ok": True, "already": True}
    notify = ("notify-send -a JustDay JustDay "
              "\"$( [ $rc = 0 ] && echo 'Части установлены' || echo 'Часть не поставилась: justday parts' )\"")
    script = f'{cli} parts add {" ".join(names)} >"{config.STATE_DIR}/parts.log" 2>&1; rc=$?; {notify}'
    done = subprocess.run(["systemd-run", "--user", "--collect", "--unit=justday-parts",
                           "--description=JustDay: доставка частей", "bash", "-c", script],
                          capture_output=True, text=True, timeout=15)
    return {"ok": done.returncode == 0, "error": done.stderr.strip()[:200]}
