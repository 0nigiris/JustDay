"""Уведомление на самом компьютере: «отсюда кое-что ушло на телефон».

Смысл не в вежливости, а в том, что снимок экрана и файл с диска — это то,
что покидает машину. Человек, сидящий за ней, должен видеть это сразу, не
листая журналы: если уведомление появилось, а телефона в руках нет, значит
с доступом что-то не так.

Служба живёт вне графического сеанса, поэтому окружение сеанса передаётся
снаружи — тем же способом, каким делается снимок экрана. Ошибки здесь
глотаются намеренно: уведомление не показалось — это не повод не отдать
человеку то, что он попросил.
"""

from __future__ import annotations

import asyncio
import os
import shutil

from remo32_core.log import get_logger

log = get_logger("agent.notify")

TIMEOUT = 5.0
APP = "Remo32"


async def show(
    body: str,
    *,
    title: str = "Ушло на телефон",
    icon: str = "smartphone",
    env: dict[str, str] | None = None,
) -> bool:
    """Показать уведомление. Возвращает, получилось ли; не бросает никогда."""
    if not shutil.which("notify-send"):
        log.debug("notify-send не установлен — уведомление пропущено")
        return False
    argv = [
        "notify-send",
        "--app-name",
        APP,
        "--icon",
        icon,
        # Снимки и файлы идут потоком, когда листаешь галерею с телефона:
        # заменяем своё же прошлое уведомление, а не копим их в столбик.
        "--hint",
        "string:x-canonical-private-synchronous:remo32-outbound",
        title,
        body,
    ]
    try:
        proc = await asyncio.create_subprocess_exec(
            *argv,
            stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.DEVNULL,
            env={**os.environ, **(env or {})},
        )
        await asyncio.wait_for(proc.wait(), timeout=TIMEOUT)
    except (TimeoutError, OSError) as exc:
        log.debug("уведомление не показалось", error=str(exc))
        return False
    return proc.returncode == 0
