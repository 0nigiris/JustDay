"""HTTP-интерфейс симулятора.

Ручка ``/command`` повторяет то, что будет делать настоящая прошивка.
Ручки ``/sim/*`` — только у симулятора: ими управляют неисправностями.
На реальной плате их не будет.
"""

from __future__ import annotations

import asyncio

from fastapi import Body, FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

from remo32_core.log import get_logger
from remo32_core.models import Esp32Status
from remo32_core.protocol import HEADER_AGENT_TOKEN, Esp32Command, Esp32Reply
from remo32_espsim import __version__
from remo32_espsim.device import SimulatedDevice

log = get_logger("espsim.http")


class FaultBody(BaseModel):
    offline: bool | None = None
    wifi_lost: bool | None = None
    failure_rate: float | None = Field(None, ge=0.0, le=1.0)
    extra_latency_ms: int | None = Field(None, ge=0, le=30_000)
    fail_commands: list[str] | None = None


class PinBody(BaseModel):
    pin: int = Field(ge=0, le=48)
    level: bool


def create_app(device: SimulatedDevice, token: str | None = None) -> FastAPI:
    app = FastAPI(
        title="Симулятор ESP32 Remo32",
        version=__version__,
        description=(
            "Программная имитация аппаратного контроллера. Отвечает тем же "
            "протоколом, что и настоящая прошивка. Ручки /sim/* существуют "
            "только здесь и служат для проверки отказов."
        ),
    )

    def check(presented: str | None) -> None:
        if token and presented != token:
            raise HTTPException(status_code=401, detail="неверный токен")

    @app.post("/command", response_model=Esp32Reply)
    async def command(
        cmd: Esp32Command = Body(...),
        auth: str | None = Header(None, alias=HEADER_AGENT_TOKEN),
    ) -> Esp32Reply:
        check(auth)
        if device.faults.offline or device.faults.wifi_lost:
            # Настоящее выключенное устройство (или потерявшее Wi-Fi) просто
            # не ответит, поэтому держим соединение до таймаута вызывающей
            # стороны, а не возвращаем аккуратную ошибку.
            await asyncio.sleep(30)
            raise HTTPException(status_code=503, detail="устройство не отвечает")
        if device.faults.extra_latency_ms:
            await asyncio.sleep(device.faults.extra_latency_ms / 1000)
        return device.handle(cmd)

    @app.get("/status", response_model=Esp32Status)
    async def status(auth: str | None = Header(None, alias=HEADER_AGENT_TOKEN)) -> Esp32Status:
        check(auth)
        if device.faults.offline or device.faults.wifi_lost:
            await asyncio.sleep(30)
            raise HTTPException(status_code=503, detail="устройство не отвечает")
        return device.status()

    # --- управление симуляцией -------------------------------------------

    @app.get("/sim/state", tags=["симуляция"])
    async def sim_state() -> dict[str, object]:
        return {
            "device_id": device.device_id,
            "faults": _faults_view(),
            "commands_handled": device.commands_handled,
            "wol_log": device.wol_log[-10:],
        }

    def _faults_view() -> dict[str, object]:
        return dict(vars(device.faults)) | {"fail_commands": sorted(device.faults.fail_commands)}

    @app.post("/sim/faults", tags=["симуляция"])
    async def sim_faults(body: FaultBody) -> dict[str, object]:
        if body.offline is not None:
            device.faults.offline = body.offline
        if body.wifi_lost is not None:
            device.faults.wifi_lost = body.wifi_lost
        if body.failure_rate is not None:
            device.faults.failure_rate = body.failure_rate
        if body.extra_latency_ms is not None:
            device.faults.extra_latency_ms = body.extra_latency_ms
        if body.fail_commands is not None:
            device.faults.fail_commands = set(body.fail_commands)
        log.warning("симулятор: изменены неисправности", **vars(device.faults))
        return {"ok": True, "faults": _faults_view()}

    @app.post("/sim/pin", tags=["симуляция"])
    async def sim_pin(body: PinBody) -> dict[str, object]:
        """Имитирует изменение входа: например, ПК включился и загорелся LED."""
        if not device.set_input(body.pin, body.level):
            raise HTTPException(status_code=400, detail="пин не настроен как вход")
        return {"ok": True, "pin": body.pin, "level": body.level}

    @app.post("/sim/reboot", tags=["симуляция"])
    async def sim_reboot() -> dict[str, bool]:
        device.reboot()
        return {"ok": True}

    return app
