"""Проброс терминала: браузер ↔ контроллер ↔ агент.

Браузер никогда не подключается к агенту напрямую. Контроллер проверяет
сессию, находит нужный ПК и открывает собственное соединение с агентом,
подставляя токен агента. Токен агента в браузер не попадает.
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from typing import Annotated

import websockets
from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect

from remo32_core.errors import Remo32Error
from remo32_core.log import get_logger
from remo32_core.protocol import TerminalServerMessage

log = get_logger("controller.api.terminal")

router = APIRouter(tags=["терминал"])


@router.websocket("/api/pcs/{pc_id}/terminal/ws")
async def terminal_proxy(
    websocket: WebSocket,
    pc_id: str,
    session: Annotated[str | None, Query()] = None,
    cols: Annotated[int, Query(ge=1, le=1000)] = 80,
    rows: Annotated[int, Query(ge=1, le=1000)] = 24,
) -> None:
    auth = websocket.app.state.auth
    registry = websocket.app.state.devices

    token = websocket.cookies.get(str(auth.cookie_settings()["key"]))
    if not token:
        await websocket.close(code=4401, reason="требуется вход")
        return
    try:
        payload = auth.sessions.verify(token)
    except Remo32Error:
        await websocket.close(code=4401, reason="сессия недействительна")
        return

    # Терминал — самая мощная дверь в системе, а cookie живёт неделями.
    # Поэтому здесь спрашивается не «вошёл ли ты когда-то», а «вошёл ли
    # недавно»: украденная сессия даёт пульт, но не оболочку.
    max_age = auth.terminal_max_session_age_seconds
    if max_age > 0:
        age = time.time() - float(payload.get("iat", 0))
        if age > max_age:
            log.warning("терминал отклонён: несвежая сессия", pc=pc_id, age_seconds=int(age))
            await websocket.close(
                code=4403,
                reason="войдите заново — терминал требует свежего входа",
            )
            return

    try:
        target = registry.terminal_target(pc_id, session, cols, rows)
    except Remo32Error as exc:
        await websocket.close(code=4403, reason=exc.message[:120])
        return

    await websocket.accept()
    log.warning("открыт проброс терминала", pc=pc_id, session=session)

    try:
        async with websockets.connect(target, open_timeout=10, ping_interval=20) as upstream:
            await _pump(websocket, upstream)
    except (OSError, websockets.exceptions.WebSocketException, TimeoutError) as exc:
        log.warning("не удалось подключиться к терминалу агента", pc=pc_id, error=str(exc))
        with contextlib.suppress(RuntimeError):
            await websocket.send_text(
                TerminalServerMessage(
                    type="error", data=f"агент недоступен: {exc}"
                ).model_dump_json()
            )
        with contextlib.suppress(RuntimeError):
            await websocket.close(code=1011)
    except WebSocketDisconnect:
        pass
    finally:
        log.info("проброс терминала закрыт", pc=pc_id)


async def _pump(browser: WebSocket, agent: websockets.ClientConnection) -> None:
    """Гоняет сообщения в обе стороны, пока жива каждая из сторон."""

    async def browser_to_agent() -> None:
        while True:
            message = await browser.receive_text()
            await agent.send(message)

    async def agent_to_browser() -> None:
        async for message in agent:
            text = message.decode() if isinstance(message, bytes) else message
            await browser.send_text(text)

    tasks = [
        asyncio.create_task(browser_to_agent(), name="term-b2a"),
        asyncio.create_task(agent_to_browser(), name="term-a2b"),
    ]
    try:
        _done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
    finally:
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
