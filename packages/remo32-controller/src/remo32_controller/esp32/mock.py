"""Симулятор ESP32, встроенный в процесс контроллера.

Нужен, чтобы разрабатывать и тестировать всю систему, когда платы нет под
рукой. Отвечает ровно тем же протоколом, что и реальное устройство.

Отдельно от него существует :mod:`remo32_espsim` — самостоятельный
процесс-симулятор, который подключается к контроллеру снаружи так же, как
настоящая плата. Здешний мок проще: он для тестов и для режима
``transport = "mock"``.

Симулятор НЕ является доказательством работоспособности железа. Любой
успешный вызов здесь означает лишь то, что протокол согласован.
"""

from __future__ import annotations

import asyncio
import random
import time
from dataclasses import dataclass, field

from remo32_core.errors import DeviceUnreachableError
from remo32_core.log import get_logger
from remo32_core.models import (
    DeviceState,
    Esp32Status,
    GpioPinState,
    GuardConfig,
    GuardStatus,
    utcnow,
)
from remo32_core.protocol import (
    Esp32Command,
    Esp32CommandType,
    Esp32Reply,
    GpioReadPayload,
    GpioWritePayload,
    GuardConfigPayload,
    GuardSnoozePayload,
    KvmSwitchPayload,
    WakeOnLanPayload,
)

log = get_logger("controller.esp32.mock")

FIRMWARE_VERSION = "0.1.0-sim"


@dataclass
class MockBehaviour:
    """Управление поведением симулятора — для проверки отказов.

    Настоящее железо иногда отваливается, теряет Wi-Fi и не отвечает.
    Система должна это переживать, значит это надо уметь воспроизводить.
    """

    offline: bool = False
    """Устройство «выключено»: любая команда приводит к ошибке связи."""

    failure_rate: float = 0.0
    """Доля команд, на которые устройство отвечает отказом (0.0–1.0)."""

    latency_seconds: float = 0.01
    delay_before_reply: float = 0.0
    fail_command_types: set[Esp32CommandType] = field(default_factory=set)
    """Типы команд, которые всегда завершаются ошибкой."""


class MockEsp32Transport:
    """Симулятор устройства."""

    name = "mock"

    def __init__(
        self,
        device_id: str = "esp32-sim",
        *,
        behaviour: MockBehaviour | None = None,
        seed: int | None = None,
    ) -> None:
        self._device_id = device_id
        self.behaviour = behaviour or MockBehaviour()
        self._started_at = time.monotonic()
        self._random = random.Random(seed)  # noqa: S311 — не криптография, а имитация сбоев
        self._gpio: dict[int, GpioPinState] = {
            4: GpioPinState(pin=4, mode="input", level=False, label="Датчик питания ПК #1"),
            5: GpioPinState(pin=5, mode="input", level=False, label="Датчик питания ПК #2"),
            18: GpioPinState(pin=18, mode="output", level=False, label="Светодиод состояния"),
        }
        self._wol_sent: list[str] = []
        self._kvm_port: int | None = None
        self._snooze_requests: list[int] = []
        # Настройки сторожа держим так же, как настоящая плата: в своей
        # памяти, пережившими перезапуск команды. Значения похожи на
        # рабочие, чтобы на симуляторе интерфейс выглядел правдиво.
        self._guard: dict[str, object] = {
            "enabled": True,
            "host": "192.168.1.250",
            "mac_address": "7c:df:a1:00:11:22",
            "broadcast_address": "255.255.255.255",
            "grace_minutes": 10,
            "retry_minutes": 15,
            "max_attempts": 3,
        }
        self._reconnects = 0
        self._running = False

    # --- управление симуляцией -------------------------------------------

    @property
    def wol_history(self) -> list[str]:
        """MAC-адреса, которым «отправлялся» magic packet."""
        return list(self._wol_sent)

    @property
    def kvm_port(self) -> int | None:
        return self._kvm_port

    @property
    def snooze_requests(self) -> list[int]:
        """Просьбы «не буди ПК», полученные от контроллера, в минутах."""
        return list(self._snooze_requests)

    def set_pin_level(self, pin: int, level: bool) -> None:
        """Имитирует изменение состояния входа — например, ПК включился."""
        if pin in self._gpio:
            self._gpio[pin].level = level

    def simulate_disconnect(self) -> None:
        self.behaviour.offline = True
        log.warning("симулятор: устройство ушло в офлайн")

    def simulate_reconnect(self) -> None:
        self.behaviour.offline = False
        self._reconnects += 1
        log.info("симулятор: устройство вернулось", reconnects=self._reconnects)

    # --- транспорт --------------------------------------------------------

    @property
    def simulated(self) -> bool:
        return True

    @property
    def state(self) -> DeviceState:
        if not self._running:
            return DeviceState.UNKNOWN
        return DeviceState.OFFLINE if self.behaviour.offline else DeviceState.ONLINE

    async def start(self) -> None:
        self._running = True
        log.info("симулятор ESP32 запущен", device_id=self._device_id)

    async def stop(self) -> None:
        self._running = False

    async def send(self, command: Esp32Command, *, timeout: float) -> Esp32Reply:
        if self.behaviour.delay_before_reply:
            await asyncio.sleep(min(self.behaviour.delay_before_reply, timeout + 1))
        else:
            await asyncio.sleep(self.behaviour.latency_seconds)

        if self.behaviour.offline or not self._running:
            raise DeviceUnreachableError("симулятор ESP32 не отвечает", device_id=self._device_id)

        if command.type in self.behaviour.fail_command_types:
            return Esp32Reply(command_id=command.id, ok=False, error="симуляция отказа команды")
        if self.behaviour.failure_rate and self._random.random() < self.behaviour.failure_rate:
            return Esp32Reply(command_id=command.id, ok=False, error="симуляция случайного сбоя")

        return self._handle(command)

    def _handle(self, command: Esp32Command) -> Esp32Reply:
        match command.type:
            case Esp32CommandType.PING | Esp32CommandType.STATUS:
                return Esp32Reply(command_id=command.id, ok=True, status=self.status())

            case Esp32CommandType.WAKE_ON_LAN:
                if not isinstance(command.payload, WakeOnLanPayload):
                    return Esp32Reply(
                        command_id=command.id, ok=False, error="в команде отсутствует payload"
                    )
                self._wol_sent.append(command.payload.mac_address)
                log.info(
                    "симулятор: magic packet НЕ отправлен по-настоящему",
                    mac=command.payload.mac_address,
                )
                return Esp32Reply(
                    command_id=command.id,
                    ok=True,
                    result={
                        "mac_address": command.payload.mac_address,
                        "repeat": command.payload.repeat,
                        "simulated": True,
                    },
                )

            case Esp32CommandType.GUARD_SNOOZE:
                if not isinstance(command.payload, GuardSnoozePayload):
                    return Esp32Reply(
                        command_id=command.id, ok=False, error="в команде отсутствует payload"
                    )
                self._snooze_requests.append(command.payload.minutes)
                return Esp32Reply(
                    command_id=command.id,
                    ok=True,
                    result={"minutes": command.payload.minutes, "simulated": True},
                )

            case Esp32CommandType.GUARD_CONFIG:
                if not isinstance(command.payload, GuardConfigPayload):
                    return Esp32Reply(
                        command_id=command.id, ok=False, error="в команде отсутствует payload"
                    )
                # Настоящая плата сохраняет только переданные поля и
                # хранит их в своей памяти. Симулятор обязан вести себя
                # так же, иначе на нём нельзя проверить интерфейс.
                changes = command.payload.model_dump(exclude_none=True)
                self._guard.update(changes)
                if self._guard.get("enabled") and not self._guard.get("mac_address"):
                    return Esp32Reply(
                        command_id=command.id,
                        ok=False,
                        error="сторож включён, но не задан MAC ПК",
                    )
                log.info("симулятор: настройки сторожа изменены", **changes)
                return Esp32Reply(command_id=command.id, ok=True, status=self.status())

            case Esp32CommandType.GPIO_READ:
                if not isinstance(command.payload, GpioReadPayload):
                    return Esp32Reply(
                        command_id=command.id, ok=False, error="в команде отсутствует payload"
                    )
                pin = self._gpio.get(command.payload.pin)
                if pin is None:
                    return Esp32Reply(
                        command_id=command.id,
                        ok=False,
                        error=f"пин {command.payload.pin} не сконфигурирован",
                    )
                return Esp32Reply(
                    command_id=command.id, ok=True, result={"pin": pin.pin, "level": pin.level}
                )

            case Esp32CommandType.GPIO_WRITE:
                if not isinstance(command.payload, GpioWritePayload):
                    return Esp32Reply(
                        command_id=command.id, ok=False, error="в команде отсутствует payload"
                    )
                pin = self._gpio.get(command.payload.pin)
                if pin is None or pin.mode != "output":
                    return Esp32Reply(
                        command_id=command.id,
                        ok=False,
                        error=f"пин {command.payload.pin} не настроен как выход",
                    )
                pin.level = command.payload.level
                return Esp32Reply(
                    command_id=command.id,
                    ok=True,
                    result={"pin": pin.pin, "level": pin.level, "simulated": True},
                )

            case Esp32CommandType.KVM_SWITCH:
                if not isinstance(command.payload, KvmSwitchPayload):
                    return Esp32Reply(
                        command_id=command.id, ok=False, error="в команде отсутствует payload"
                    )
                # Симулятор запоминает номер входа, но физического KVM нет.
                self._kvm_port = command.payload.port
                return Esp32Reply(
                    command_id=command.id,
                    ok=True,
                    result={
                        "port": command.payload.port,
                        "simulated": True,
                        "note": "физический KVM не подключён",
                    },
                )

            case Esp32CommandType.REBOOT:
                self._started_at = time.monotonic()
                self._reconnects += 1
                return Esp32Reply(command_id=command.id, ok=True, result={"simulated": True})

            case _:  # pragma: no cover
                return Esp32Reply(
                    command_id=command.id, ok=False, error=f"неизвестная команда: {command.type}"
                )

    def status(self) -> Esp32Status:
        return Esp32Status(
            state=self.state,
            device_id=self._device_id,
            firmware_version=FIRMWARE_VERSION,
            simulated=True,
            chip="esp32s3",
            uptime_seconds=time.monotonic() - self._started_at,
            # Правдоподобные значения для ESP32-S3 без PSRAM.
            free_heap_bytes=self._random.randint(180_000, 240_000),
            min_free_heap_bytes=170_000,
            psram_present=False,
            wifi_rssi_dbm=self._random.randint(-72, -45),
            wifi_ssid="СИМУЛЯЦИЯ",
            ip_address="192.168.1.250",
            mac_address="7c:df:a1:00:11:22",
            last_seen=utcnow(),
            reconnect_count=self._reconnects,
            gpio=list(self._gpio.values()),
            guard=GuardStatus(
                state="наблюдение" if self._guard.get("enabled") else "выключен",
                host_alive=True,
                attempts=0,
                total_wakes=0,
                config=GuardConfig(**self._guard),
            ),
            capabilities=["wol", "gpio_in", "gpio_out", "status", "guard", "guard_config"],
        )
