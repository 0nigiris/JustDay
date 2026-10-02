"""Режим сервера: компьютер выключен для человека и работает для ассистента.

Зачем. Человек уходит, а работа остаётся: скачать, собрать, смонтировать, дождаться ответа. Гасить
машину нельзя — работа встанет; оставлять как есть тоже плохо: экраны горят всю ночь, звук играет в
пустой комнате, а через десять минут всё засыпает само и работа опять встаёт.

Что делает режим. Экраны гаснут, звук глохнет, засыпание запрещается — и это всё. Сеанс **не**
блокируется нарочно: ассистент управляет окнами того же сеанса, и блокировка отняла бы у него
руки ровно в тот момент, когда он остаётся работать один.

Выход. Любое движение мышью будит экраны само — это делает сам монитор, а не мы. Поэтому режим
кончается не «когда человек вернулся», а когда его выключили: `justday server off`. Так честнее,
чем угадывать по движению мыши, которое бывает и от кошки.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from . import config

STATE = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "justday-server-mode.json"


def _run(*cmd: str, timeout: float = 10) -> bool:
    if not shutil.which(cmd[0]):
        return False
    try:
        return subprocess.run(cmd, capture_output=True, timeout=timeout).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _screens(on: bool) -> bool:
    """Погасить или зажечь экраны. Это DPMS, а не выключение: мышь будит их сама."""
    return _run("kscreen-doctor", f"--dpms={'on' if on else 'off'}")


def _mute(on: bool) -> bool:
    return _run("wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1" if on else "0")


def _keep_awake(why: str) -> int:
    """Запретить засыпание, пока идёт работа. Возвращает pid сторожа, 0 — не вышло.

    Сторож — отдельный процесс systemd-inhibit, который просто спит: пока он жив, система не
    уснёт. Это надёжнее, чем менять настройки энергосбережения: мы ничего не ломаем человеку, и
    всё возвращается само, если нас убьют.
    """
    if not shutil.which("systemd-inhibit"):
        return 0
    try:
        p = subprocess.Popen(
            ["systemd-inhibit", "--what=idle:sleep:handle-lid-switch", "--who=JustDay",
             f"--why={why}", "--mode=block", "sleep", "infinity"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return p.pid
    except OSError:
        return 0


def state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def on(why: str = "работа ассистента") -> dict:
    """Включить режим сервера."""
    was = state()
    if was.get("on"):
        return {"ok": True, "already": True, **was}
    out = {"on": True, "why": why,
           "screens_off": _screens(False),
           "muted": _mute(True),
           "guard": _keep_awake(why)}
    try:
        STATE.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    except OSError as e:
        return {"ok": False, "error": str(e)}
    out["ok"] = True
    return out


def off() -> dict:
    """Вернуть всё как было: экраны, звук, засыпание."""
    was = state()
    pid = int(was.get("guard") or 0)
    if pid:
        try:
            os.kill(pid, 15)
        except (OSError, ProcessLookupError):
            pass
    out = {"ok": True, "on": False, "screens_on": _screens(True)}
    if was.get("muted"):
        out["unmuted"] = _mute(False)
    STATE.unlink(missing_ok=True)
    return out


def status() -> dict:
    was = state()
    return {"ok": True, "on": bool(was.get("on")), "why": was.get("why", ""),
            "guard_alive": bool(was.get("guard")) and Path(f"/proc/{was.get('guard')}").exists(),
            "config": (config.load().get("session") or {}).get("server_mode", None)}
