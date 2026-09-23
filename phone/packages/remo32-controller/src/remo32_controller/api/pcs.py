"""Управление ПК."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, Field

from remo32_controller.auth.dependencies import Session
from remo32_controller.devices import DeviceRegistry
from remo32_core.errors import ActionInvalidError
from remo32_core.http import RequestId
from remo32_core.log import get_logger
from remo32_core.models import (
    ActionDescriptor,
    ActionEditorState,
    ActionResult,
    ApiResponse,
    ApprovalInfo,
    ApprovalList,
    PcSummary,
    SystemStats,
)

log = get_logger("controller.api.pcs")

router = APIRouter(prefix="/api/pcs", tags=["ПК"])


class WakeResult(BaseModel):
    mac_address: str
    attempts: list[dict[str, Any]]


def _registry(request: Request) -> DeviceRegistry:
    registry: DeviceRegistry = request.app.state.devices
    return registry


@router.get("", response_model=ApiResponse[list[PcSummary]])
async def list_pcs(
    request: Request, _session: Session, request_id: RequestId
) -> ApiResponse[list[PcSummary]]:
    """Все зарегистрированные ПК с последним известным состоянием.

    Ответ приходит мгновенно даже если все ПК выключены: контроллер
    отдаёт то, что знает из фонового опроса, и не ходит по сети синхронно.
    """
    return ApiResponse[list[PcSummary]].success(_registry(request).summaries(), request_id)


@router.get("/{pc_id}", response_model=ApiResponse[PcSummary])
async def get_pc(
    pc_id: str, request: Request, _session: Session, request_id: RequestId
) -> ApiResponse[PcSummary]:
    return ApiResponse[PcSummary].success(_registry(request).summary(pc_id), request_id)


@router.get("/{pc_id}/stats", response_model=ApiResponse[SystemStats])
async def get_stats(
    pc_id: str, request: Request, _session: Session, request_id: RequestId
) -> ApiResponse[SystemStats]:
    """Свежая статистика: запрашивается у агента прямо сейчас."""
    return ApiResponse[SystemStats].success(await _registry(request).stats(pc_id), request_id)


@router.post("/{pc_id}/wake", response_model=ApiResponse[WakeResult])
async def wake(
    pc_id: str, request: Request, _session: Session, request_id: RequestId
) -> ApiResponse[WakeResult]:
    """Пробуждение по сети.

    Контроллер пробует оба доступных пути — собственный magic packet и
    команду ESP32 — и сообщает, что из этого сработало.
    """
    result = await _registry(request).wake(pc_id)
    return ApiResponse[WakeResult].success(WakeResult.model_validate(result), request_id)


@router.post("/{pc_id}/shutdown", response_model=ApiResponse[ActionResult])
async def shutdown(
    pc_id: str, request: Request, _session: Session, request_id: RequestId
) -> ApiResponse[ActionResult]:
    """Корректное выключение через агент."""
    return ApiResponse[ActionResult].success(await _registry(request).shutdown(pc_id), request_id)


@router.post("/{pc_id}/restart", response_model=ApiResponse[ActionResult])
async def restart(
    pc_id: str, request: Request, _session: Session, request_id: RequestId
) -> ApiResponse[ActionResult]:
    return ApiResponse[ActionResult].success(await _registry(request).restart(pc_id), request_id)


@router.get("/{pc_id}/actions", response_model=ApiResponse[list[ActionDescriptor]])
async def list_actions(
    pc_id: str, request: Request, _session: Session, request_id: RequestId
) -> ApiResponse[list[ActionDescriptor]]:
    return ApiResponse[list[ActionDescriptor]].success(
        await _registry(request).actions(pc_id), request_id
    )


# --- JustDay ---------------------------------------------------------------
# Ассистент живёт на самом ПК; контроллер только передаёт просьбу и возвращает ответ.


class JustDayAsk(BaseModel):
    text: str = Field(min_length=1, max_length=2000)
    silent: bool = False
    aloud: bool = Field(False, description="Не просьба, а текст, который надо произнести")


class JustDayPlayer(BaseModel):
    action: str = Field(min_length=1, max_length=32)
    value: int | str | None = None


@router.get("/{pc_id}/justday", response_model=ApiResponse[dict[str, Any]])
async def justday_status(
    pc_id: str, request: Request, _session: Session, request_id: RequestId
) -> ApiResponse[dict[str, Any]]:
    """Чем занят ассистент на этом ПК, что играет, что стоит в таймерах."""
    return ApiResponse[dict[str, Any]].success(
        await _registry(request).get(pc_id).client.justday_status(), request_id
    )


@router.post("/{pc_id}/justday/ask", response_model=ApiResponse[dict[str, Any]])
async def justday_ask(
    pc_id: str, payload: JustDayAsk, request: Request, _session: Session, request_id: RequestId
) -> ApiResponse[dict[str, Any]]:
    """Просьба ассистенту — та же, что голосом. `aloud` — просто произнести текст."""
    client = _registry(request).get(pc_id).client
    log.info("просьба ассистенту", pc_id=pc_id, aloud=payload.aloud)
    got = (
        await client.justday_say(payload.text)
        if payload.aloud
        else await client.justday_ask(payload.text, silent=payload.silent)
    )
    return ApiResponse[dict[str, Any]].success(got, request_id)


@router.post("/{pc_id}/justday/player", response_model=ApiResponse[dict[str, Any]])
async def justday_player(
    pc_id: str, payload: JustDayPlayer, request: Request, _session: Session, request_id: RequestId
) -> ApiResponse[dict[str, Any]]:
    return ApiResponse[dict[str, Any]].success(
        await _registry(request).get(pc_id).client.justday_player(payload.action, payload.value),
        request_id,
    )


# Голос, надиктованный в браузере: файл идёт сквозь контроллер к агенту без разбора и
# без записи на диск — распознаёт его сам ассистент на компьютере.
DICTATE_LIMIT = 8 * 1024 * 1024


@router.post("/{pc_id}/justday/dictate", response_model=ApiResponse[dict[str, Any]])
async def justday_dictate(
    pc_id: str,
    request: Request,
    _session: Session,
    request_id: RequestId,
    suffix: str = Query(".webm", max_length=8, pattern=r"^\.[a-z0-9]{2,6}$"),
) -> ApiResponse[dict[str, Any]]:
    """Надиктованное с телефона: запись уезжает на ПК, ответ приходит как на обычную просьбу."""
    audio = await request.body()
    if not audio:
        raise ActionInvalidError("пустая запись")
    if len(audio) > DICTATE_LIMIT:
        raise ActionInvalidError("запись слишком длинная")
    log.info("надиктовка", pc_id=pc_id, bytes=len(audio))
    return ApiResponse[dict[str, Any]].success(
        await _registry(request).get(pc_id).client.justday_dictate(audio, suffix), request_id
    )


@router.post("/{pc_id}/justday/session/{action}", response_model=ApiResponse[dict[str, Any]])
async def justday_session(
    pc_id: str, action: str, request: Request, _session: Session, request_id: RequestId
) -> ApiResponse[dict[str, Any]]:
    """«Я ушёл» (close) и «я вернулся» (restore)."""
    log.info("сессия рабочего стола", pc_id=pc_id, action=action)
    return ApiResponse[dict[str, Any]].success(
        await _registry(request).get(pc_id).client.justday_session(action), request_id
    )


@router.get("/{pc_id}/approvals", response_model=ApiResponse[ApprovalList])
async def approvals(
    pc_id: str, request: Request, _session: Session, request_id: RequestId
) -> ApiResponse[ApprovalList]:
    """Чего компьютер ждёт от вас прямо сейчас: подтверждения входа или sudo."""
    return ApiResponse[ApprovalList].success(
        await _registry(request).get(pc_id).client.approvals(), request_id
    )


@router.post("/{pc_id}/approvals/session", response_model=ApiResponse[ApprovalInfo])
async def allow_session(
    pc_id: str, request: Request, _session: Session, request_id: RequestId
) -> ApiResponse[ApprovalInfo]:
    """Заранее разрешить следующий вход в систему на этом ПК."""
    log.info("разрешён следующий вход", pc_id=pc_id)
    return ApiResponse[ApprovalInfo].success(
        await _registry(request).get(pc_id).client.allow_session(), request_id
    )


@router.post("/{pc_id}/approvals/{approval_id}", response_model=ApiResponse[ApprovalInfo])
async def decide_approval(
    pc_id: str,
    approval_id: str,
    payload: dict[str, Any],
    request: Request,
    _session: Session,
    request_id: RequestId,
) -> ApiResponse[ApprovalInfo]:
    approved = bool(payload.get("approved", False))
    log.info("решение по подтверждению", pc_id=pc_id, id=approval_id, approved=approved)
    return ApiResponse[ApprovalInfo].success(
        await _registry(request).get(pc_id).client.decide_approval(approval_id, approved),
        request_id,
    )


@router.get("/{pc_id}/action-editor", response_model=ApiResponse[ActionEditorState])
async def action_editor(
    pc_id: str, request: Request, _session: Session, request_id: RequestId
) -> ApiResponse[ActionEditorState]:
    """Кнопки, заведённые через интерфейс, вместе с их командами.

    Контроллер здесь посредник: описания проверяет агент — только он знает,
    какие виды действий понимает его операционная система.
    """
    return ApiResponse[ActionEditorState].success(
        await _registry(request).action_editor(pc_id), request_id
    )


@router.put("/{pc_id}/action-editor/{action_id}", response_model=ApiResponse[ActionDescriptor])
async def save_action(
    pc_id: str,
    action_id: str,
    payload: dict[str, Any],
    request: Request,
    _session: Session,
    request_id: RequestId,
) -> ApiResponse[ActionDescriptor]:
    log.info("правка кнопки", pc_id=pc_id, action_id=action_id)
    return ApiResponse[ActionDescriptor].success(
        await _registry(request).save_action(pc_id, action_id, payload), request_id
    )


@router.delete("/{pc_id}/action-editor/{action_id}", response_model=ApiResponse[ActionEditorState])
async def delete_action(
    pc_id: str,
    action_id: str,
    request: Request,
    _session: Session,
    request_id: RequestId,
) -> ApiResponse[ActionEditorState]:
    log.info("удаление кнопки", pc_id=pc_id, action_id=action_id)
    return ApiResponse[ActionEditorState].success(
        await _registry(request).delete_action(pc_id, action_id), request_id
    )


@router.post("/{pc_id}/actions/{action_id}", response_model=ApiResponse[ActionResult])
async def run_action(
    pc_id: str,
    action_id: str,
    request: Request,
    _session: Session,
    request_id: RequestId,
) -> ApiResponse[ActionResult]:
    """Выполняет предопределённое действие.

    Произвольную команду передать нельзя: принимается только идентификатор
    действия, описанного в конфигурации агента.
    """
    result = await _registry(request).run_action(pc_id, action_id)
    log.info("выполнено действие", pc=pc_id, action=action_id, success=result.success)
    return ApiResponse[ActionResult].success(result, request_id)
