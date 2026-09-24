"""HTTP API агента.

Все содержательные ручки требуют токен. Единственное исключение —
``/ping``: он не раскрывает ничего, кроме факта «служба жива», и нужен
для диагностики, когда токен как раз и вызывает сомнения.
"""

from __future__ import annotations

import contextlib
import time
from typing import Annotated, Any

from fastapi import APIRouter, Depends, Query, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from pydantic import BaseModel, Field, TypeAdapter, ValidationError

from remo32_agent import __version__, justday, screen
from remo32_agent.actions.models import ActionConfig
from remo32_agent.context import AgentContext
from remo32_agent.stats.collector import collect_stats
from remo32_agent.terminal.session import TerminalConfig, TerminalSession, list_tmux_sessions
from remo32_core.errors import (
    ActionInvalidError,
    ActionsNotEditableError,
    ApprovalsDisabledError,
    NotFoundError,
    TerminalDisabledError,
)
from remo32_core.http import RequestId
from remo32_core.log import get_logger
from remo32_core.models import (
    ActionDescriptor,
    ActionEditorState,
    ActionKind,
    ActionResult,
    AgentHealth,
    ApiResponse,
    ApprovalInfo,
    ApprovalList,
    SystemStats,
)
from remo32_core.protocol import TerminalClientMessage, TerminalServerMessage

log = get_logger("agent.api")

_ACTION_ADAPTER: TypeAdapter[ActionConfig] = TypeAdapter(ActionConfig)


def _first_problem(exc: ValidationError) -> str:
    """Первая ошибка валидации человеческим текстом.

    Полный вывод pydantic на телефоне читать невозможно, а показать нужно
    именно то поле, которое человек только что заполнил.
    """
    errors = exc.errors()
    if not errors:
        return "описание кнопки некорректно"
    first = errors[0]
    where = ".".join(str(p) for p in first.get("loc", ()) if p != "function-after")
    message = first.get("msg", "значение недопустимо")
    return f"{where}: {message}" if where else message


class PingResponse(BaseModel):
    pong: bool = True
    service: str = "remo32-agent"
    version: str = __version__


class JustDayCommand(BaseModel):
    """Просьба ассистенту — ровно то же, что человек сказал бы голосом."""

    text: str = Field(min_length=1, max_length=2000)
    silent: bool = Field(False, description="Не произносить ответ вслух: только текстом")


class JustDayPlayer(BaseModel):
    action: str = Field(min_length=1, max_length=32)
    value: int | str | None = None


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

    # --- правка кнопок ---------------------------------------------------
    #
    # Отдельный префикс, а не /api/actions/...: там уже живёт запуск по
    # идентификатору, и кнопка с именем «manage» перехватывала бы маршрут.

    @router.get(
        "/api/action-editor",
        response_model=ApiResponse[ActionEditorState],
        tags=["действия"],
        dependencies=[auth],
    )
    async def editor_state(request_id: RequestId) -> ApiResponse[ActionEditorState]:
        """Кнопки, заведённые через интерфейс, вместе с их командами."""
        editor = ctx.settings.actions_editor
        state = ActionEditorState(
            enabled=editor.enabled,
            max_actions=editor.max_actions,
            actions=[a.model_dump(mode="json", exclude_none=True) for a in ctx.registry.managed()],
            kinds=list(ActionKind),
        )
        return ApiResponse[ActionEditorState].success(state, request_id)

    @router.put(
        "/api/action-editor/{action_id}",
        response_model=ApiResponse[ActionDescriptor],
        tags=["действия"],
        dependencies=[auth],
    )
    async def upsert_action(
        action_id: str, payload: dict[str, Any], request_id: RequestId
    ) -> ApiResponse[ActionDescriptor]:
        """Заводит кнопку или заменяет существующую.

        Тело проверяется теми же моделями, что и конфигурационный файл:
        произвольная строка для оболочки сюда не пройдёт — вид действия
        должен быть из списка, а команда приходит списком аргументов.
        """
        editor = ctx.settings.actions_editor
        if not editor.enabled:
            raise ActionsNotEditableError("правка кнопок через интерфейс выключена")

        body = dict(payload)
        body["id"] = action_id
        try:
            action = _ACTION_ADAPTER.validate_python(body)
        except ValidationError as exc:
            raise ActionInvalidError(_first_problem(exc)) from exc

        existing = {a.id for a in ctx.registry.managed()}
        if action_id not in existing and len(existing) >= editor.max_actions:
            raise ActionInvalidError(
                f"уже заведено {len(existing)} кнопок — это предел (actions_editor.max_actions)"
            )

        ctx.registry.upsert(action)
        log.info("кнопка сохранена", action_id=action_id, kind=str(action.kind))
        return ApiResponse[ActionDescriptor].success(ctx.registry.describe(action_id), request_id)

    @router.delete(
        "/api/action-editor/{action_id}",
        response_model=ApiResponse[ActionEditorState],
        tags=["действия"],
        dependencies=[auth],
    )
    async def delete_action(
        action_id: str, request_id: RequestId
    ) -> ApiResponse[ActionEditorState]:
        if not ctx.settings.actions_editor.enabled:
            raise ActionsNotEditableError("правка кнопок через интерфейс выключена")
        ctx.registry.delete(action_id)
        log.info("кнопка удалена", action_id=action_id)
        return await editor_state(request_id)

    # --- подтверждение входа и sudo с телефона ----------------------------

    @router.get(
        "/api/approvals",
        response_model=ApiResponse[ApprovalList],
        tags=["подтверждения"],
        dependencies=[auth],
    )
    async def list_approvals(request_id: RequestId) -> ApiResponse[ApprovalList]:
        """Чего компьютер ждёт прямо сейчас.

        Опрашивается вместе с остальным состоянием: человек набирает sudo и
        видит запрос на телефоне через секунду, не открывая ничего особо.
        """
        store = ctx.approvals
        items = [ApprovalInfo(**a.to_json()) for a in store.list()] if store.enabled else []
        return ApiResponse[ApprovalList].success(
            ApprovalList(enabled=store.enabled, items=items), request_id
        )

    @router.post(
        "/api/approvals/session",
        response_model=ApiResponse[ApprovalInfo],
        tags=["подтверждения"],
        dependencies=[auth],
    )
    async def allow_session(request_id: RequestId) -> ApiResponse[ApprovalInfo]:
        """Заранее разрешить следующий вход в систему.

        На экране входа ждать нечего: человек уже стоит перед формой. Поэтому
        одобрение выдаётся заранее, живёт пару минут и сгорает при первом же
        использовании.
        """
        if not ctx.approvals.enabled:
            raise ApprovalsDisabledError("подтверждение с телефона выключено")
        approval = ctx.approvals.create(
            "login",
            state="approved",
            user=ctx.settings.agent_id,
            source="телефон",
            ttl_seconds=ctx.settings.approvals.login_ttl_seconds,
        )
        return ApiResponse[ApprovalInfo].success(ApprovalInfo(**approval.to_json()), request_id)

    @router.post(
        "/api/approvals/{approval_id}",
        response_model=ApiResponse[ApprovalInfo],
        tags=["подтверждения"],
        dependencies=[auth],
    )
    async def decide(
        approval_id: str, payload: dict[str, Any], request_id: RequestId
    ) -> ApiResponse[ApprovalInfo]:
        """Ответить на ожидающий запрос: подтвердить или отклонить."""
        if not ctx.approvals.enabled:
            raise ApprovalsDisabledError("подтверждение с телефона выключено")
        try:
            approval = ctx.approvals.decide(approval_id, bool(payload.get("approved", False)))
        except KeyError:
            raise NotFoundError("запрос не найден или истёк") from None
        return ApiResponse[ApprovalInfo].success(ApprovalInfo(**approval.to_json()), request_id)

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

    # --- JustDay -------------------------------------------------------
    # Агент ничего не решает сам: он передаёт просьбу ассистенту на этой же машине
    # и возвращает его ответ как есть.

    @router.get(
        "/api/justday",
        response_model=ApiResponse[dict[str, Any]],
        tags=["JustDay"],
        dependencies=[auth],
    )
    async def justday_status(request_id: RequestId) -> ApiResponse[dict[str, Any]]:
        """Чем занят ассистент, что играет, какие таймеры стоят."""
        if not justday.available():
            return ApiResponse[dict[str, Any]].success({"available": False}, request_id)
        return ApiResponse[dict[str, Any]].success(await justday.status(), request_id)

    @router.post(
        "/api/justday/ask",
        response_model=ApiResponse[dict[str, Any]],
        tags=["JustDay"],
        dependencies=[auth],
    )
    async def justday_ask(
        command: JustDayCommand, request_id: RequestId
    ) -> ApiResponse[dict[str, Any]]:
        """Просьба текстом — та же, что голосом с кнопки."""
        return ApiResponse[dict[str, Any]].success(
            await justday.ask(command.text, silent=command.silent), request_id
        )

    @router.post(
        "/api/justday/say",
        response_model=ApiResponse[dict[str, Any]],
        tags=["JustDay"],
        dependencies=[auth],
    )
    async def justday_say(
        command: JustDayCommand, request_id: RequestId
    ) -> ApiResponse[dict[str, Any]]:
        """Произнести текст на компьютере — позвать кого-то в комнате."""
        return ApiResponse[dict[str, Any]].success(await justday.say(command.text), request_id)

    @router.post(
        "/api/justday/player",
        response_model=ApiResponse[dict[str, Any]],
        tags=["JustDay"],
        dependencies=[auth],
    )
    async def justday_player(
        command: JustDayPlayer, request_id: RequestId
    ) -> ApiResponse[dict[str, Any]]:
        """Кнопки плеера: pause, resume, next, prev, volume и остальные.

        Отдельным действием здесь же едет громкость голоса ассистента: для
        телефона это соседний ползунок, и заводить ради него ещё один
        маршрут значило бы разносить одно и то же по разным местам.
        """
        if command.action == "voice_volume":
            return ApiResponse[dict[str, Any]].success(
                await justday.voice_volume(int(command.value or 0)), request_id
            )
        return ApiResponse[dict[str, Any]].success(
            await justday.player(command.action, command.value), request_id
        )

    @router.post(
        "/api/justday/dictate",
        response_model=ApiResponse[dict[str, Any]],
        tags=["JustDay"],
        dependencies=[auth],
    )
    async def justday_dictate(
        request: Request,
        request_id: RequestId,
        suffix: str = Query(".webm", max_length=8, pattern=r"^\.[a-z0-9]{2,6}$"),
    ) -> ApiResponse[dict[str, Any]]:
        """Звук с телефона. Распознаёт ассистент на этой машине — наружу запись не уходит."""
        audio = await request.body()
        if not audio:
            raise ActionInvalidError("пустая запись")
        if len(audio) > 8 * 1024 * 1024:  # минута речи весит около 700 КБ
            raise ActionInvalidError("запись слишком длинная")
        return ApiResponse[dict[str, Any]].success(await justday.dictate(audio, suffix), request_id)

    @router.post(
        "/api/justday/session/{action}",
        response_model=ApiResponse[dict[str, Any]],
        tags=["JustDay"],
        dependencies=[auth],
    )
    async def justday_session(action: str, request_id: RequestId) -> ApiResponse[dict[str, Any]]:
        """«Я ушёл» (close) и «я вернулся» (restore); list и save — посмотреть и запомнить."""
        if action not in ("list", "save", "close", "restore"):
            raise ActionInvalidError(f"неизвестное действие сессии: {action}")
        return ApiResponse[dict[str, Any]].success(await justday.session(action), request_id)

    @router.get(
        "/api/screen",
        tags=["рабочий стол"],
        dependencies=[auth],
        response_class=Response,
        responses={200: {"content": {"image/png": {}}, "description": "Снимок экрана"}},
    )
    async def screen_shot() -> Response:
        """Что сейчас на экране. Картинка уходит в ответ и на диске не остаётся.

        Снимок делается в окружении графического сеанса: служба живёт вне его,
        и без DISPLAY/WAYLAND_DISPLAY ни одна утилита ничего не увидит.
        """
        png = await screen.capture(ctx.adapter.graphical_session_env())
        # no-store, а не просто no-cache: содержимое экрана — не то, чему
        # стоит лежать в кэше браузера.
        return Response(png, media_type="image/png", headers={"Cache-Control": "no-store"})

    @router.get(
        "/api/justday/art",
        tags=["JustDay"],
        dependencies=[auth],
        response_class=Response,
        responses={200: {"content": {"image/jpeg": {}}, "description": "Обложка играющего трека"}},
    )
    async def justday_art() -> Response:
        """Обложка того, что играет. Путь к файлу берём у ассистента, а не у телефона."""
        data, kind = await justday.artwork()
        return Response(data, media_type=kind, headers={"Cache-Control": "no-store"})

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
