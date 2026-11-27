"""Филин внутри JustDay: включить, снять и узнать, тронули ли компьютер, пока его не было.

Сам Филин — отдельный проект (github.com/0nigiris/Filin): его ставят и без JustDay. Здесь только
связка: служба systemd, строка в настройках, слова для голоса и весть о срабатывании. Без вести
он узнавал о чужом касании, только когда сам открывал папку со снимками.
"""
import os
import shutil
import signal
import subprocess
import sys
from pathlib import Path

from . import config

UNIT = "justday-filin"
SEEN = config.STATE_DIR / "filin-seen"
PID = config.STATE_DIR / "filin.pid"


def _out() -> Path | None:
    try:
        from filin import OUT
    except ImportError:  # поставлен без Филина
        return None
    return OUT


def control(action: str = "status", delay: float = 15) -> dict:
    out = _out()
    if out is None:
        return {"available": False, "on": False}
    if config.WINDOWS:
        on = _control_windows(action, delay)
    else:
        on = _control_systemd(action, delay)
    log = out / "журнал.txt"
    last = log.read_text(encoding="utf-8").strip().splitlines()[-1:] if log.exists() else []
    return {"available": True, "on": on, "photos": str(out), "last": last[0] if last else ""}


def _alive(pid: int) -> bool:
    """os.kill(pid, 0) на Windows не проверяет, а убивает процесс, поэтому — через OpenProcess."""
    import ctypes

    k = ctypes.windll.kernel32
    h = k.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not h:
        return False
    code = ctypes.c_ulong()
    k.GetExitCodeProcess(h, ctypes.byref(code))
    k.CloseHandle(h)
    return code.value == 259  # STILL_ACTIVE


def _control_windows(action: str, delay: float) -> bool:
    """systemd нет: Филин — отдельный процесс JustDay, его номер лежит в filin.pid.
    ponytail: номер может достаться чужому процессу после перезагрузки; хватит до первой жалобы."""
    try:
        pid = int(PID.read_text())
    except (OSError, ValueError):
        pid = 0
    if action in ("on", "off") and pid and _alive(pid):
        os.kill(pid, signal.SIGTERM)  # на Windows это TerminateProcess
        pid = 0
    if action == "on":
        # JustDay.exe — он же и команды (island/host.py); без сборки — тот же Python, что у демона.
        cmd = [sys.executable] if getattr(sys, "frozen", False) else [sys.executable, "-m", "justday.cli"]
        p = subprocess.Popen([*cmd, "filin", "run", "--delay", str(delay)],
                             creationflags=0x00000008 | 0x00000200)  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
        PID.parent.mkdir(parents=True, exist_ok=True)
        PID.write_text(str(p.pid))
        return True
    return bool(pid) and _alive(pid)


def _control_systemd(action: str, delay: float) -> bool:
    if action == "on":
        exe = shutil.which("filin", path=str(Path(sys.executable).parent)) or shutil.which("filin")
        subprocess.run(["systemctl", "--user", "stop", UNIT], capture_output=True, timeout=30)
        # --collect: сработавший Филин выходит сам, и упавшая служба не должна висеть до перезагрузки.
        subprocess.run(["systemd-run", "--user", "--collect", f"--unit={UNIT}", exe, "--delay", str(delay)],
                       capture_output=True, timeout=30)
    elif action == "off":
        subprocess.run(["systemctl", "--user", "stop", UNIT], capture_output=True, timeout=30)
    state = subprocess.run(["systemctl", "--user", "is-active", UNIT],
                           capture_output=True, text=True, timeout=10).stdout.strip()
    return state == "active"


def news() -> list[str]:
    """Срабатывания, о которых ещё не сказали: строки журнала Филина после прочитанного места."""
    out = _out()
    log = out / "журнал.txt" if out else None
    if not log or not log.exists():
        return []
    lines = log.read_text(encoding="utf-8").splitlines()
    try:
        seen = int(SEEN.read_text())
    except (OSError, ValueError):
        seen = -1
    SEEN.parent.mkdir(parents=True, exist_ok=True)
    SEEN.write_text(str(len(lines)))
    if seen < 0:  # первый запуск: старые срабатывания уже видел в папке, не вываливать их разом
        return []
    return [ln for ln in lines[seen:] if "тронули" in ln]
