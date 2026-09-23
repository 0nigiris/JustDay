"""JustDay на этой машине — то же, что делает остров, только с телефона.

Ассистент уже слушает свой сокет в ``$XDG_RUNTIME_DIR/justday.sock`` и понимает там
однострочный JSON. Агент просто говорит с ним на том же языке: ничего не запускает,
ничего не хранит и ничего не умеет сверх того, что умеет сам JustDay.

Сокет принадлежит тому же пользователю и виден только ему — наружу он не смотрит
никогда. Всё, что уходит в сеть, проходит обычный путь агента: токен, затем контроллер.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from remo32_core.errors import ActionInvalidError, DeviceTimeoutError, DeviceUnreachableError
from remo32_core.log import get_logger

log = get_logger("agent.justday")

DEFAULT_TIMEOUT = 15.0
# «Скажи Джарвису» — это целый ход модели: он бывает и минуту.
ASK_TIMEOUT = 180.0


def socket_path() -> Path:
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    return Path(os.environ.get("JUSTDAY_SOCKET", f"{runtime}/justday.sock"))


def available() -> bool:
    """Есть ли на этой машине живой JustDay. Проверка дешёвая: существование сокета."""
    path = socket_path()
    return path.exists() and path.is_socket()


async def call(command: str, *, timeout: float = DEFAULT_TIMEOUT, **payload: Any) -> dict[str, Any]:
    """Одна команда ассистенту. Ответ — его же JSON, как его видит остров."""
    path = socket_path()
    if not available():
        raise DeviceUnreachableError("JustDay на этой машине не запущен")
    request = json.dumps({"cmd": command, **payload}, ensure_ascii=False) + "\n"
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_unix_connection(str(path)), timeout=5.0
        )
    except (OSError, TimeoutError) as exc:
        raise DeviceUnreachableError(f"JustDay не отвечает: {exc}") from exc
    try:
        writer.write(request.encode())
        await writer.drain()
        line = await asyncio.wait_for(reader.readline(), timeout=timeout)
    except TimeoutError as exc:
        raise DeviceTimeoutError(f"JustDay думает дольше {timeout:.0f} с") from exc
    except OSError as exc:
        raise DeviceUnreachableError(f"связь с JustDay оборвалась: {exc}") from exc
    finally:
        writer.close()
        with contextlib.suppress(OSError):
            await writer.wait_closed()
    if not line:
        raise DeviceUnreachableError("JustDay закрыл соединение молча")
    try:
        answer: dict[str, Any] = json.loads(line)
    except ValueError as exc:
        raise DeviceUnreachableError("JustDay ответил не JSON") from exc
    return answer


async def status() -> dict[str, Any]:
    """Чем занят ассистент, что играет, что стоит в таймерах."""
    state = await call("status")
    player = await call("media", action="status")
    reminders = await call("reminders")
    return {
        "available": True,
        "state": state.get("state", ""),
        "brain_busy": bool(state.get("brain_busy")),
        "silent": state.get("silent", ""),
        "model": state.get("model", ""),
        "wakeword": bool(state.get("wakeword")),
        "player": player.get("music") or player.get("player") or {},
        "reminders": reminders.get("reminders") or [],
    }


async def ask(text: str, *, silent: bool = False) -> dict[str, Any]:
    """Просьба — та же, что голосом. Ответ приходит текстом и звучит на компьютере."""
    return await call("ask", text=text, silent=silent, timeout=ASK_TIMEOUT)


async def say(text: str) -> dict[str, Any]:
    """Сказать голосом на компьютере — например, позвать кого-то в комнате."""
    return await call("say", text=text, timeout=60.0)


async def player(action: str, value: Any = None) -> dict[str, Any]:
    return await call("media", action=action, value=value)


async def dictate(audio: bytes, suffix: str = ".webm") -> dict[str, Any]:
    """Надиктованное с телефона. Звук ложится во временный файл и распознаётся ассистентом —
    той же моделью, что слушает микрофон на столе. Файл удаляется сразу после ответа:
    записи голоса не накапливаются нигде.

    Распознавание может занять несколько секунд, поэтому ждём столько же, сколько и просьбу."""
    # mkstemp, а не NamedTemporaryFile: файл должен пережить запись и дожить до конца
    # распознавания, а закрыть его нужно раньше — читает его другой процесс. Права 0600
    # ставит сам mkstemp, так что чужой пользователь запись не прочтёт.
    fd, path = tempfile.mkstemp(prefix="justday-dictate-", suffix=suffix)
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(audio)
        return await call("dictate", path=path, timeout=ASK_TIMEOUT)
    finally:
        with contextlib.suppress(OSError):
            os.unlink(path)


# Обложки ассистент складывает к себе в кэш, музыку — в свою папку. Больше
# ниоткуда картинку не отдаём: путь приходит от ассистента, но проверяет его
# агент — телефон в этот момент просит просто «дай обложку», без путей.
ART_DIRS = ("/.cache/justday/", "/Music/")
ART_TYPES = {
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".webp": "image/webp",
}


def _art_file(path: str) -> tuple[bytes, str]:
    real = Path(path).resolve()
    kind = ART_TYPES.get(real.suffix.lower())
    if not kind or not any(part in str(real) for part in ART_DIRS) or not real.is_file():
        raise ActionInvalidError("обложки нет")
    if real.stat().st_size > 8 * 1024 * 1024:
        raise ActionInvalidError("обложка слишком большая")
    return real.read_bytes(), kind


async def artwork() -> tuple[bytes, str]:
    """Обложка играющего трека — файлом, как он лежит на компьютере."""
    state = await call("media", action="status")
    path = str((state.get("music") or {}).get("thumb") or "")
    if not path:
        raise ActionInvalidError("сейчас ничего не играет")
    return await asyncio.to_thread(_art_file, path)


async def session(action: str) -> dict[str, Any]:
    """«Я ушёл» / «я вернулся»: закрыть открытые программы и вернуть их обратно."""
    return await call("session", action=action, timeout=60.0)
