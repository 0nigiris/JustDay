"""Служебные ручки: здоровье контроллера и поток событий."""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator

from fastapi import APIRouter, Request
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from remo32_controller import __version__
from remo32_controller.auth.dependencies import Session
from remo32_core.http import RequestId
from remo32_core.log import get_logger
from remo32_core.models import ApiResponse, DeviceState

log = get_logger("controller.api.system")

router = APIRouter(tags=["служебные"])

# Как часто слать «сердцебиение», если ничего не происходит. Нужно, чтобы
# промежуточные прокси не рвали простаивающее соединение.
HEARTBEAT_SECONDS = 20.0


class ControllerHealth(BaseModel):
    status: str = "ok"
    version: str = __version__
    pcs_total: int
    pcs_online: int
    esp32_state: DeviceState
    esp32_simulated: bool
    terminal_enabled_pcs: int


@router.get("/api/health", response_model=ApiResponse[ControllerHealth])
async def health(request: Request, request_id: RequestId) -> ApiResponse[ControllerHealth]:
    """Здоровье контроллера. Без аутентификации: нужна для мониторинга.

    Никаких подробностей об устройствах здесь нет — только счётчики.
    """
    registry = request.app.state.devices
    esp32 = request.app.state.esp32
    summaries = registry.summaries()
    status = esp32.status() if esp32 is not None else None
    return ApiResponse[ControllerHealth].success(
        ControllerHealth(
            pcs_total=len(summaries),
            pcs_online=sum(1 for s in summaries if s.state == DeviceState.ONLINE),
            esp32_state=status.state if status else DeviceState.UNKNOWN,
            esp32_simulated=bool(status and status.simulated),
            terminal_enabled_pcs=sum(1 for s in summaries if s.terminal_supported),
        ),
        request_id,
    )


@router.get("/api/events")
async def events(request: Request, _session: Session) -> StreamingResponse:
    """Поток событий (SSE) для живого обновления интерфейса.

    Выбран SSE, а не WebSocket: поток односторонний, переподключение
    браузер делает сам, и работает он через любые прокси.
    """
    registry = request.app.state.devices
    queue = registry.subscribe()

    async def stream() -> AsyncIterator[bytes]:
        try:
            yield b'event: hello\ndata: {"ok":true}\n\n'
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event = await asyncio.wait_for(queue.get(), timeout=HEARTBEAT_SECONDS)
                except TimeoutError:
                    yield b": heartbeat\n\n"
                    continue
                payload = json.dumps({"event": event}, ensure_ascii=False)
                yield f"event: update\ndata: {payload}\n\n".encode()
        finally:
            registry.unsubscribe(queue)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # чтобы nginx не буферизовал поток
        },
    )
