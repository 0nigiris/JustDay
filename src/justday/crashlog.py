"""Журнал падений (Р2-45): служба упала и перезапустилась молча — «вылетел сам, логи не делал?».

Вызывается из `ExecStopPost=` служб. Нормальный выход ничего не пишет; сбой, убийство сигналом или
таймаут сохраняют хвост журнала службы и версии. Хранятся последние KEEP отчётов."""
from __future__ import annotations

import os
import re
import subprocess
import time
from pathlib import Path

from . import config

KEEP = 20
DIR = config.STATE_DIR / "crashes"


def _run(cmd: list[str], timeout: int = 15) -> str:
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return (p.stdout + p.stderr).strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def scrub(text: str) -> str:
    """Имя пользователя в путях → ~: отчёт можно приложить к Issue, не светя домашнюю папку."""
    home = str(Path.home())
    return re.sub(rf"/home/{re.escape(os.environ.get('USER', Path.home().name))}\b", "~", text.replace(home, "~"))


def save(service: str, result: str | None = None) -> Path | None:
    result = result or os.environ.get("SERVICE_RESULT", "success")
    if result == "success":
        return None
    DIR.mkdir(parents=True, exist_ok=True)
    repo = config.REPO_DIR
    parts = [
        f"служба: {service}   результат: {result}   код: {os.environ.get('EXIT_STATUS', '?')}",
        f"версия: {_run(['git', '-C', str(repo), 'rev-parse', '--short', 'HEAD'])} "
        f"({_run(['git', '-C', str(repo), 'branch', '--show-current'])})",
        f"qs: {_run(['qs', '--version'])}",
        f"ядро: {_run(['uname', '-r'])}   Plasma: {_run(['plasmashell', '--version'])}",
        "", "── журнал службы ──",
        _run(["journalctl", "--user", "-u", service, "-n", "300", "--no-pager"]),
        "", "── coredumpctl ──",
        _run(["coredumpctl", "info", "--no-pager", "-r", "-n", "1"]) or "(нет)",
    ]
    path = DIR / f"{time.strftime('%Y%m%d-%H%M%S')}-{service.removesuffix('.service')}.log"
    path.write_text(scrub("\n".join(parts)), encoding="utf-8")
    for old in sorted(DIR.glob("*.log"))[:-KEEP]:
        old.unlink(missing_ok=True)
    return path


def count() -> int:
    return len(list(DIR.glob("*.log"))) if DIR.is_dir() else 0
