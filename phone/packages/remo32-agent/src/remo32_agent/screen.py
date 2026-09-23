"""Снимок экрана — на телефон.

Посмотреть, что сейчас на компьютере, бывает нужнее любой кнопки: понять,
почему он не спит, не висит ли обновление, чем занят Claude Code. Поэтому
снимок не сохраняется в «Изображения», как делало старое действие, а уходит
прямо в ответ и на диске не остаётся.

Утилиту выбираем не по наличию в системе, а по результату: ``grim`` работает
через wlr-screencopy, которого в KWin нет, и на Plasma он установлен,
запускается и падает. Пробуем по очереди, пока не получится непустой файл.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
import shutil
import tempfile

from remo32_core.errors import CapabilityUnavailableError
from remo32_core.log import get_logger

log = get_logger("agent.screen")

# Команда получает имя файла последним аргументом — кроме тех, где иначе.
TOOLS: tuple[tuple[str, list[str]], ...] = (
    ("spectacle", ["spectacle", "-b", "-n", "-o"]),  # KDE, наш случай
    ("grim", ["grim"]),  # wlroots
    ("gnome-screenshot", ["gnome-screenshot", "-f"]),
    ("import", ["import", "-window", "root"]),  # X11, ImageMagick
    ("scrot", ["scrot", "-o"]),
)

TIMEOUT = 20.0
LIMIT = 24 * 1024 * 1024  # снимок 4K в PNG весит около 10 МБ


def _read(path: str) -> bytes:
    """Прочитать снимок, если он вообще получился."""
    if not os.path.exists(path) or not (size := os.path.getsize(path)):
        return b""
    if size > LIMIT:
        raise CapabilityUnavailableError("снимок слишком большой")
    with open(path, "rb") as fh:
        return fh.read()


async def capture(env: dict[str, str] | None = None) -> bytes:
    """Снимок всего экрана в PNG. Файл удаляется сразу после чтения."""
    fd, path = tempfile.mkstemp(prefix="remo32-screen-", suffix=".png")
    os.close(fd)
    try:
        tried: list[str] = []
        for name, argv in TOOLS:
            if not shutil.which(name):
                continue
            tried.append(name)
            try:
                proc = await asyncio.create_subprocess_exec(
                    *argv,
                    path,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                    env={**os.environ, **(env or {})},
                )
                _, err = await asyncio.wait_for(proc.communicate(), timeout=TIMEOUT)
            except (TimeoutError, OSError) as exc:
                log.info("снимок не вышел", tool=name, error=str(exc))
                continue
            # Утилита умеет отчитаться об успехе, не создав файла. Диск
            # трогаем в отдельном потоке: снимок 4K весит мегабайты, и читать
            # его в цикле событий значит подвесить весь агент на это время.
            png = await asyncio.to_thread(_read, path)
            if proc.returncode == 0 and png:
                log.info("снимок сделан", tool=name, bytes=len(png))
                return png
            log.info(
                "снимок не вышел",
                tool=name,
                code=proc.returncode,
                error=err.decode(errors="replace")[:200],
            )
        raise CapabilityUnavailableError(
            "снимок экрана не удался: "
            + (
                f"пробовали {', '.join(tried)}"
                if tried
                else "не установлено ни одной утилиты (spectacle, grim, import)"
            )
        )
    finally:
        with contextlib.suppress(OSError):
            os.unlink(path)
