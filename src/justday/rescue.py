"""Экстренная перезагрузка: сначала снять отладку, потом перезапустить.

Зачем в таком порядке. Островок или демон застыли, человек жмёт клавишу, всё перезапускается и
работает, а что было не так, уже не узнать: журнал прокрутился, состояние ушло. Поэтому перед
перезапуском на диск ложится снимок: хвосты журналов обеих служб, состояние юнитов, самые
жирные процессы и последняя строка очереди. Его читают потом, спокойно.
"""
from __future__ import annotations

import subprocess
import time
from pathlib import Path

from . import config

UNITS = ("justday", "justday-ui")


def _run(cmd: list[str], limit: int = 60000) -> str:
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"[не вышло: {e}]"
    return ((out.stdout or "") + (out.stderr or ""))[-limit:]


def bundle(folder: Path | None = None) -> Path:
    """Пишет снимок отладки и возвращает путь к нему."""
    folder = folder or config.STATE_DIR / "debug"
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / time.strftime("rescue-%Y%m%d-%H%M%S.txt")
    parts = [f"JustDay: снимок перед экстренным перезапуском, {time.strftime('%F %T')}\n"]
    for unit in UNITS:
        parts.append(f"\n===== {unit}: состояние =====\n" + _run(["systemctl", "--user", "status", unit, "--no-pager", "-n", "0"]))
        parts.append(f"\n===== {unit}: журнал, последние 300 строк =====\n"
                     + _run(["journalctl", "--user", "-u", unit, "-n", "300", "--no-pager"]))
    parts.append("\n===== процессы по памяти =====\n" + _run(["ps", "-eo", "pid,pcpu,pmem,etime,comm", "--sort=-pmem"], 4000))
    path.write_text("".join(parts), encoding="utf-8")
    path.chmod(0o600)   # в журнале бывают куски разговоров
    return path


def restart() -> Path:
    """Снимок, затем перезапуск демона и острова: демон первым, остров через три секунды."""
    path = bundle()
    subprocess.run(["systemctl", "--user", "restart", "justday"], capture_output=True)
    time.sleep(3)
    subprocess.run(["systemctl", "--user", "restart", "justday-ui"], capture_output=True)
    return path
