"""Филин внутри JustDay: включить, снять и узнать, тронули ли компьютер, пока его не было.

Сам Филин — отдельный проект (github.com/0nigiris/Filin): его ставят и без JustDay. Здесь только
связка: служба systemd, строка в настройках, слова для голоса и весть о срабатывании. Без вести
он узнавал о чужом касании, только когда сам открывал папку со снимками.
"""
import shutil
import subprocess
import sys
from pathlib import Path

from . import config

UNIT = "justday-filin"
SEEN = config.STATE_DIR / "filin-seen"


def _out() -> Path | None:
    try:
        from filin import OUT
    except ImportError:  # Windows или поставлен без Филина
        return None
    return OUT


def control(action: str = "status", delay: float = 15) -> dict:
    out = _out()
    if out is None:
        return {"available": False, "on": False}
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
    log = out / "журнал.txt"
    last = log.read_text(encoding="utf-8").strip().splitlines()[-1:] if log.exists() else []
    return {"available": True, "on": state == "active", "photos": str(out), "last": last[0] if last else ""}


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
