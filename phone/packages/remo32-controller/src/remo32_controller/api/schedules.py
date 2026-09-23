"""Расписания: создание и правка прямо с телефона."""

from __future__ import annotations

from fastapi import APIRouter, Request

from remo32_controller.auth.dependencies import Session
from remo32_controller.schedule.models import ScheduleCreate, ScheduleEntry, ScheduleUpdate
from remo32_controller.schedule.service import ScheduleService
from remo32_core.http import RequestId
from remo32_core.log import get_logger
from remo32_core.models import ApiResponse

log = get_logger("controller.api.schedules")

router = APIRouter(prefix="/api/schedules", tags=["расписание"])


def _service(request: Request) -> ScheduleService:
    service: ScheduleService = request.app.state.schedules
    return service


@router.get("", response_model=ApiResponse[list[ScheduleEntry]])
async def list_schedules(
    request: Request, _session: Session, request_id: RequestId
) -> ApiResponse[list[ScheduleEntry]]:
    """Все правила с результатом последнего срабатывания."""
    return ApiResponse[list[ScheduleEntry]].success(_service(request).list_entries(), request_id)


@router.post("", response_model=ApiResponse[ScheduleEntry], status_code=201)
async def create_schedule(
    data: ScheduleCreate, request: Request, _session: Session, request_id: RequestId
) -> ApiResponse[ScheduleEntry]:
    """Новое правило.

    Действие не проверяется на существование: ПК может быть выключен в
    момент создания, а список действий живёт на нём. Ошибка всплывёт при
    срабатывании и попадёт в поле последнего результата.
    """
    return ApiResponse[ScheduleEntry].success(_service(request).create(data), request_id)


@router.get("/{schedule_id}", response_model=ApiResponse[ScheduleEntry])
async def get_schedule(
    schedule_id: str, request: Request, _session: Session, request_id: RequestId
) -> ApiResponse[ScheduleEntry]:
    return ApiResponse[ScheduleEntry].success(_service(request).get(schedule_id), request_id)


@router.patch("/{schedule_id}", response_model=ApiResponse[ScheduleEntry])
async def update_schedule(
    schedule_id: str,
    data: ScheduleUpdate,
    request: Request,
    _session: Session,
    request_id: RequestId,
) -> ApiResponse[ScheduleEntry]:
    """Частичное изменение: передаются только изменяемые поля."""
    return ApiResponse[ScheduleEntry].success(
        _service(request).update(schedule_id, data), request_id
    )


@router.delete("/{schedule_id}", response_model=ApiResponse[None])
async def delete_schedule(
    schedule_id: str, request: Request, _session: Session, request_id: RequestId
) -> ApiResponse[None]:
    _service(request).delete(schedule_id)
    return ApiResponse[None].success(None, request_id)


@router.post("/{schedule_id}/run", response_model=ApiResponse[ScheduleEntry])
async def run_schedule(
    schedule_id: str, request: Request, _session: Session, request_id: RequestId
) -> ApiResponse[ScheduleEntry]:
    """Выполнить правило прямо сейчас, не дожидаясь времени.

    Плановое срабатывание при этом не отменяется.
    """
    entry = await _service(request).run_now(schedule_id)
    return ApiResponse[ScheduleEntry].success(entry, request_id)
