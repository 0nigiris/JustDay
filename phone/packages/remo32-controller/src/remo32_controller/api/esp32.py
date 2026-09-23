"""Аппаратный контроллер и переключение ПК."""

from __future__ import annotations

from fastapi import APIRouter, Request
from pydantic import BaseModel, Field

from remo32_controller.auth.dependencies import Session
from remo32_controller.esp32.controller import Esp32Controller
from remo32_core.errors import CapabilityUnavailableError
from remo32_core.http import RequestId
from remo32_core.models import ApiResponse, Esp32Status
from remo32_core.protocol import GuardConfigPayload

router = APIRouter(prefix="/api/esp32", tags=["ESP32"])


class GpioWriteBody(BaseModel):
    pin: int = Field(ge=0, le=48)
    level: bool
    pulse_ms: int | None = Field(None, ge=1, le=10_000)


class SwitchBody(BaseModel):
    pc_id: str = Field(min_length=1, max_length=64)


def _esp32(request: Request) -> Esp32Controller | None:
    controller: Esp32Controller | None = request.app.state.esp32
    return controller


@router.get("/status", response_model=ApiResponse[Esp32Status])
async def status(
    request: Request, _session: Session, request_id: RequestId
) -> ApiResponse[Esp32Status]:
    """Состояние аппаратного контроллера.

    Поле ``simulated`` показывает, отвечает ли настоящее железо или
    симулятор. Интерфейс обязан это различать.
    """
    controller = _esp32(request)
    if controller is None:
        return ApiResponse[Esp32Status].success(
            Esp32Status(last_error="ESP32 выключен в конфигурации"), request_id
        )
    return ApiResponse[Esp32Status].success(controller.status(), request_id)


@router.post("/refresh", response_model=ApiResponse[Esp32Status])
async def refresh(
    request: Request, _session: Session, request_id: RequestId
) -> ApiResponse[Esp32Status]:
    controller = _esp32(request)
    if controller is None:
        raise CapabilityUnavailableError("ESP32 выключен в конфигурации")
    return ApiResponse[Esp32Status].success(await controller.refresh(), request_id)


@router.post("/guard", response_model=ApiResponse[Esp32Status])
async def guard_config(
    body: GuardConfigPayload, request: Request, _session: Session, request_id: RequestId
) -> ApiResponse[Esp32Status]:
    """Изменить настройки сторожа в самой плате.

    Нужно ровно для двух случаев: исправить записанный MAC и укоротить
    ожидание на время проверки. Консоль у платы только по USB, а стоит
    она в розетке — иначе за настройками пришлось бы идти с проводом.

    Передаются только изменяемые поля; остальное плата оставляет как есть.
    Изменения переживают её перезагрузку, поэтому укороченное ожидание
    нужно возвращать обратно: иначе любой сбой сети станет поводом
    включить ПК.
    """
    controller = _esp32(request)
    if controller is None:
        raise CapabilityUnavailableError("ESP32 выключен в конфигурации")
    await controller.guard_config(body)
    return ApiResponse[Esp32Status].success(await controller.refresh(), request_id)


@router.post("/gpio", response_model=ApiResponse[dict[str, object]])
async def gpio_write(
    body: GpioWriteBody, request: Request, _session: Session, request_id: RequestId
) -> ApiResponse[dict[str, object]]:
    controller = _esp32(request)
    if controller is None:
        raise CapabilityUnavailableError("ESP32 выключен в конфигурации")
    reply = await controller.gpio_write(body.pin, body.level, pulse_ms=body.pulse_ms)
    return ApiResponse[dict[str, object]].success(reply.result, request_id)


@router.post("/switch", response_model=ApiResponse[dict[str, object]])
async def switch_pc(
    body: SwitchBody, request: Request, _session: Session, request_id: RequestId
) -> ApiResponse[dict[str, object]]:
    """Переключение активного ПК на мониторе (KVM).

    Абстракция готова заранее, но без физического переключателя,
    подключённого к ESP32, программа переключить монитор и клавиатуру не
    может — в этом случае возвращается 501 с понятным объяснением.
    """
    controller = _esp32(request)
    if controller is None:
        raise CapabilityUnavailableError("ESP32 выключен в конфигурации")

    registry = request.app.state.devices
    pc = registry.get(body.pc_id)
    if pc.config.kvm_port is None:
        raise CapabilityUnavailableError(
            f"для «{pc.config.name}» не задан номер входа KVM (kvm_port)", pc_id=body.pc_id
        )
    reply = await controller.switch_kvm(pc.config.kvm_port)
    return ApiResponse[dict[str, object]].success(
        {"pc_id": body.pc_id, "kvm_port": pc.config.kvm_port, **reply.result}, request_id
    )
