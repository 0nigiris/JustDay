"""HTTP API агента.

Все содержательные ручки требуют токен. Единственное исключение —
``/ping``: он не раскрывает ничего, кроме факта «служба жива», и нужен
для диагностики, когда токен как раз и вызывает сомнения.
"""

from __future__ import annotations

import contextlib
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, WebSocket, WebSocketDisconnect
from pydantic import BaseModel, Field

from remo32_agent import __version__
from remo32_agent.context import AgentContext
from remo32_agent.stats.collector import collect_stats
from remo32_agent.terminal.session import TerminalConfig, TerminalSession, list_tmux_sessions
from remo32_core.errors import TerminalDisabledError
from remo32_core.http import RequestId
from remo32_core.log import get_logger
from remo32_core.models import (
    ActionDescriptor,
    ActionResult,
    AgentHealth,
    ApiResponse,
    SystemStats,
)
from remo32_core.protocol import TerminalClientMessage, TerminalServerMessage

log = get_logger("agent.api")


class PingResponse(BaseModel):
    pong: bool = True
    service: str = "remo32-agent"
    version: str = __version__


class TerminalInfo(BaseModel):
    enabled: bool
    sessions: list[str] = Field(default_factory=list)
    default_session: str | None = None


def build_router(ctx: AgentContext) -> APIRouter:
    router = APIRouter()
    auth = Depends(ctx.auth_dependency)

    @router.get("/ping", response_model=PingResponse, tags=["служебные"])
    async def ping() -> PingResponse:
        """Проверка живости без аутентификации."""
        return PingResponse()

    @router.get(
        "/api/health",
        response_model=ApiResponse[AgentHealth],
        tags=["служебные"],
        dependencies=[auth],
    )
    async def health(request_id: RequestId) -> ApiResponse[AgentHealth]:
        """Лёгкий статус агента. Именно его контроллер опрашивает по кругу."""
        return ApiResponse[AgentHealth].success(ctx.health(), request_id)

    @router.get(
        "/api/stats",
        response_model=ApiResponse[SystemStats],
        tags=["статистика"],
        dependencies=[auth],
    )
    async def stats(request_id: RequestId) -> ApiResponse[SystemStats]:
        """Снимок состояния машины. Недоступные датчики отдаются как null."""
        return ApiResponse[SystemStats].success(collect_stats(), request_id)

    @router.get(
        "/api/actions",
        response_model=ApiResponse[list[ActionDescriptor]],
        tags=["действия"],
        dependencies=[auth],
    )
    async def list_actions(request_id: RequestId) -> ApiResponse[list[ActionDescriptor]]:
        """Все предопределённые действия этой машины.

        Поле ``available`` показывает, установлена ли соответствующая
        программа: интерфейс рисует такие кнопки неактивными.
        """
        return ApiResponse[list[ActionDescriptor]].success(
            ctx.executor.registry.descriptors(), request_id
        )

    @router.post(
        "/api/actions/{action_id}",
        response_model=ApiResponse[ActionResult],
        tags=["действия"],
        dependencies=[auth],
    )
    async def run_action(action_id: str, request_id: RequestId) -> ApiResponse[ActionResult]:
        """Выполняет действие по идентификатору.

        Произвольную команду сюда передать нельзя: принимается только имя
        уже описанного в конфигурации действия.
        """
        result = await ctx.executor.run(action_id)
        return ApiResponse[ActionResult].success(result, request_id)

    @router.post(
        "/api/power/shutdown",
        response_model=ApiResponse[ActionResult],
        tags=["питание"],
        dependencies=[auth],
    )
    async def shutdown(request_id: RequestId) -> ApiResponse[ActionResult]:
        """Корректное выключение машины."""
        return ApiResponse[ActionResult].success(await ctx.power.shutdown(), request_id)

    @router.post(
        "/api/power/restart",
        response_model=ApiResponse[ActionResult],
        tags=["питание"],
        dependencies=[auth],
    )
    async def restart(request_id: RequestId) -> ApiResponse[ActionResult]:
        return ApiResponse[ActionResult].success(await ctx.power.reboot(), request_id)

    @router.post(
        "/api/power/cancel",
        response_model=ApiResponse[ActionResult],
        tags=["питание"],
        dependencies=[auth],
    )
    async def cancel(request_id: RequestId) -> ApiResponse[ActionResult]:
        """Отменяет отложенное выключение, если успеть в течение задержки."""
        return ApiResponse[ActionResult].success(await ctx.power.cancel(), request_id)

    @router.post(
        "/api/power/lock",
        response_model=ApiResponse[ActionResult],
        tags=["питание"],
        dependencies=[auth],
    )
    async def lock(request_id: RequestId) -> ApiResponse[ActionResult]:
        return ApiResponse[ActionResult].success(await ctx.power.lock(), request_id)

    @router.get(
        "/api/terminal",
        response_model=ApiResponse[TerminalInfo],
        tags=["терминал"],
        dependencies=[auth],
    )
    async def terminal_info(request_id: RequestId) -> ApiResponse[TerminalInfo]:
        """Включён ли терминал и какие сессии уже существуют."""
        if not ctx.settings.terminal.enabled:
            return ApiResponse[TerminalInfo].success(TerminalInfo(enabled=False), request_id)
        sessions = await list_tmux_sessions()
        return ApiResponse[TerminalInfo].success(
            TerminalInfo(
                enabled=True,
                sessions=sessions,
                default_session=ctx.terminal_session_name(ctx.settings.terminal.default_session),
            ),
            request_id,
        )

    @router.websocket("/api/terminal/ws")
    async def terminal_ws(
        websocket: WebSocket,
        token: Annotated[str | None, Query()] = None,
        session: Annotated[str | None, Query()] = None,
        cols: Annotated[int, Query(ge=1, le=1000)] = 80,
        rows: Annotated[int, Query(ge=1, le=1000)] = 24,
    ) -> None:
        """Двусторонний поток терминала.

        Токен передаётся параметром запроса, потому что браузерный WebSocket
        не умеет задавать заголовки. К агенту подключается не браузер, а
        контроллер, и соединение идёт по приватной сети — но токен всё равно
        обязателен.
        """
        await _terminal_websocket(ctx, websocket, token, session, cols, rows)

    return router


async def _terminal_websocket(
    ctx: AgentContext,
    websocket: WebSocket,
    token: str | None,
    session: str | None,
    cols: int,
    rows: int,
) -> None:
    if not ctx.settings.terminal.enabled:
        await websocket.close(code=4403, reason="терминал выключен в конфигурации агента")
        raise TerminalDisabledError("терминал выключен в конфигурации агента")

    try:
        ctx.auth.verify(token)
    except Exception:
        await websocket.close(code=4401, reason="неверный токен")
        return

    name = ctx.terminal_session_name(session or ctx.settings.terminal.default_session)
    peer = websocket.client.host if websocket.client else "?"

    existing = await list_tmux_sessions()
    if name not in existing and len(existing) >= ctx.settings.terminal.max_sessions:
        await websocket.close(code=4429, reason="достигнут предел числа сессий")
        return

    await websocket.accept()
    ctx.audit.record("terminal_open", session=name, peer=peer, cols=cols, rows=rows)
    log.warning("открыт удалённый терминал", session=name, peer=peer)

    term = TerminalSession(
        TerminalConfig(
            session_name=name,
            shell=ctx.settings.terminal.shell,
            cols=cols,
            rows=rows,
            scrollback_lines=ctx.settings.terminal.scrollback_lines,
        )
    )
    started = time.monotonic()
    try:
        await term.start()
        await _send(websocket, TerminalServerMessage(type="ready", session=name))
        await _pump(ctx, websocket, term, name)
    except WebSocketDisconnect:
        pass
    except Exception as exc:
        log.exception("сбой терминальной сессии", session=name)
        await _send(websocket, TerminalServerMessage(type="error", data=str(exc)))
    finally:
        await term.close()
        ctx.audit.record(
            "terminal_close",
            session=name,
            peer=peer,
            duration_s=round(time.monotonic() - started, 1),
        )
        log.info("удалённый терминал закрыт", session=name, peer=peer)


async def _pump(ctx: AgentContext, websocket: WebSocket, term: TerminalSession, name: str) -> None:
    """Перекачивает данные в обе стороны, пока жива хотя бы одна сторона."""
    import asyncio

    async def to_client() -> None:
        async for chunk in term.read_output():
            await _send(
                websocket,
                TerminalServerMessage(type="output", data=chunk.decode("utf-8", errors="replace")),
            )
        await _send(websocket, TerminalServerMessage(type="exit", session=name))

    async def from_client() -> None:
        while True:
            raw = await websocket.receive_text()
            try:
                msg = TerminalClientMessage.model_validate_json(raw)
            except ValueError:
                await _send(
                    websocket,
                    TerminalServerMessage(type="error", data="некорректное сообщение"),
                )
                continue
            match msg.type:
                case "input" if msg.data:
                    ctx.audit.record("terminal_input", session=name, bytes=len(msg.data))
                    term.write(msg.data.encode("utf-8"))
                case "resize" if msg.rows and msg.cols:
                    term.resize(msg.rows, msg.cols)
                case "ping":
                    await _send(websocket, TerminalServerMessage(type="pong"))
                case _:
                    pass

    tasks = [asyncio.create_task(to_client()), asyncio.create_task(from_client())]
    try:
        done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
        for task in pending:
            task.cancel()
        for task in done:
            if (exc := task.exception()) and not isinstance(exc, WebSocketDisconnect):
                raise exc
    finally:
        for task in tasks:
            task.cancel()


async def _send(websocket: WebSocket, message: TerminalServerMessage) -> None:
    # Клиент мог отключиться между сообщениями — это нормальный ход событий.
    with contextlib.suppress(WebSocketDisconnect, RuntimeError):
        await websocket.send_text(message.model_dump_json())


def openapi_tags() -> list[dict[str, Any]]:
    return [
        {"name": "служебные", "description": "Живость и здоровье агента"},
        {"name": "статистика", "description": "CPU, память, диски, сеть, температуры, GPU"},
        {"name": "действия", "description": "Предопределённые безопасные действия"},
        {"name": "питание", "description": "Выключение, перезагрузка, блокировка"},
        {"name": "терминал", "description": "Удалённый терминал (по умолчанию выключен)"},
    ]
