"""Модель устройства: состояние, GPIO, обработка команд.

Здесь сосредоточено поведение «платы». Транспорты (HTTP, MQTT) — тонкие
обёртки поверх этого класса, ровно как в настоящей прошивке, где логика
команд не зависит от того, пришли они по HTTP или по MQTT.
"""

from __future__ import annotations

import random
import time
from dataclasses import dataclass, field

from remo32_core.log import get_logger
from remo32_core.models import (
    DeviceState,
    Esp32Status,
    GpioPinState,
    GuardStatus,
    utcnow,
)
from remo32_core.protocol import (
    Esp32Command,
    Esp32CommandType,
    Esp32Reply,
    GpioReadPayload,
    GpioWritePayload,
    GuardSnoozePayload,
    KvmSwitchPayload,
    WakeOnLanPayload,
)

log = get_logger("espsim.device")

FIRMWARE_VERSION = "0.1.0-simulator"
CHIP = "esp32s3"


@dataclass
class Faults:
    """Управляемые неисправности.

    Симулятор ценен не тем, что он «работает», а тем, что умеет ломаться
    так же, как настоящее железо.
    """

    offline: bool = False
    wifi_lost: bool = False
    failure_rate: float = 0.0
    extra_latency_ms: int = 0
    fail_commands: set[str] = field(default_factory=set)


@dataclass
class GpioPin:
    pin: int
    mode: str
    level: bool = False
    label: str | None = None

    def to_model(self) -> GpioPinState:
        return GpioPinState(
            pin=self.pin,
            mode=self.mode,
            level=None if self.mode == "unused" else self.level,
            label=self.label,
        )


class SimulatedDevice:
    """Симулируемая плата ESP32-S3."""

    def __init__(
        self,
        device_id: str = "esp32-main",
        *,
        wifi_ssid: str = "СИМУЛЯЦИЯ",
        send_real_wol: bool = False,
        seed: int | None = None,
    ) -> None:
        self.device_id = device_id
        self.faults = Faults()
        self._wifi_ssid = wifi_ssid
        self._send_real_wol = send_real_wol
        self._boot = time.monotonic()
        self._rng = random.Random(seed)  # noqa: S311 — имитация, не криптография
        self._reconnects = 0
        self._commands_handled = 0
        self._wol_log: list[dict[str, object]] = []
        self._kvm_port: int | None = None

        # Сторож основного ПК. Симулятор не пингует ничего по-настоящему:
        # он лишь честно повторяет протокол, чтобы контроллер и интерфейс
        # можно было проверить без платы.
        self._guard_snooze_until: float | None = None
        self._guard_wakes = 0

        # Раскладка соответствует схеме в docs/HARDWARE.md.
        self._gpio: dict[int, GpioPin] = {
            4: GpioPin(4, "input", False, "Датчик питания ПК #1"),
            5: GpioPin(5, "input", False, "Датчик питания ПК #2"),
            18: GpioPin(18, "output", False, "Светодиод состояния"),
            21: GpioPin(21, "output", False, "Резерв (реле)"),
        }

    # --- управление симуляцией -------------------------------------------

    @property
    def wol_log(self) -> list[dict[str, object]]:
        return list(self._wol_log)

    @property
    def commands_handled(self) -> int:
        return self._commands_handled

    def set_input(self, pin: int, level: bool) -> bool:
        gpio = self._gpio.get(pin)
        if gpio is None or gpio.mode != "input":
            return False
        gpio.level = level
        log.info("симулятор: изменён вход", pin=pin, level=level)
        return True

    def reconnect(self) -> None:
        self._reconnects += 1
        self.faults.wifi_lost = False
        self.faults.offline = False

    def reboot(self) -> None:
        self._boot = time.monotonic()
        self._reconnects = 0
        for gpio in self._gpio.values():
            if gpio.mode == "output":
                gpio.level = False
        log.warning("симулятор: перезагрузка устройства")

    # --- состояние --------------------------------------------------------

    def status(self) -> Esp32Status:
        online = not (self.faults.offline or self.faults.wifi_lost)
        return Esp32Status(
            state=DeviceState.ONLINE if online else DeviceState.OFFLINE,
            device_id=self.device_id,
            firmware_version=FIRMWARE_VERSION,
            simulated=True,
            chip=CHIP,
            uptime_seconds=time.monotonic() - self._boot,
            # Похоже на реальный ESP32-S3 с выключенным PSRAM.
            free_heap_bytes=self._rng.randint(180_000, 250_000),
            min_free_heap_bytes=165_000,
            psram_present=False,
            wifi_rssi_dbm=None if self.faults.wifi_lost else self._rng.randint(-75, -42),
            wifi_ssid=None if self.faults.wifi_lost else self._wifi_ssid,
            ip_address=None if self.faults.wifi_lost else "192.168.1.250",
            mac_address="7c:df:a1:00:11:22",
            last_seen=utcnow(),
            reconnect_count=self._reconnects,
            gpio=[g.to_model() for g in self._gpio.values()],
            guard=GuardStatus(
                state="плановое выключение" if self._snoozing else "наблюдение",
                host_alive=True,
                attempts=0,
                total_wakes=self._guard_wakes,
            ),
            capabilities=["wol", "gpio_in", "gpio_out", "status", "reboot", "guard"],
        )

    @property
    def _snoozing(self) -> bool:
        return self._guard_snooze_until is not None and time.monotonic() < self._guard_snooze_until

    # --- обработка команд -------------------------------------------------

    def handle(self, command: Esp32Command) -> Esp32Reply:
        self._commands_handled += 1

        if command.type.value in self.faults.fail_commands:
            return Esp32Reply(command_id=command.id, ok=False, error="симуляция отказа команды")
        if self.faults.failure_rate and self._rng.random() < self.faults.failure_rate:
            return Esp32Reply(command_id=command.id, ok=False, error="симуляция случайного сбоя")

        match command.type:
            case Esp32CommandType.PING | Esp32CommandType.STATUS:
                return Esp32Reply(command_id=command.id, ok=True, status=self.status())

            case Esp32CommandType.WAKE_ON_LAN:
                if not isinstance(command.payload, WakeOnLanPayload):
                    return Esp32Reply(
                        command_id=command.id, ok=False, error="в команде отсутствует payload"
                    )
                return self._wake(command.id, command.payload)

            case Esp32CommandType.GPIO_READ:
                if not isinstance(command.payload, GpioReadPayload):
                    return Esp32Reply(
                        command_id=command.id, ok=False, error="в команде отсутствует payload"
                    )
                gpio = self._gpio.get(command.payload.pin)
                if gpio is None:
                    return Esp32Reply(
                        command_id=command.id,
                        ok=False,
                        error=f"пин {command.payload.pin} не сконфигурирован",
                    )
                return Esp32Reply(
                    command_id=command.id, ok=True, result={"pin": gpio.pin, "level": gpio.level}
                )

            case Esp32CommandType.GPIO_WRITE:
                if not isinstance(command.payload, GpioWritePayload):
                    return Esp32Reply(
                        command_id=command.id, ok=False, error="в команде отсутствует payload"
                    )
                gpio = self._gpio.get(command.payload.pin)
                if gpio is None or gpio.mode != "output":
                    return Esp32Reply(
                        command_id=command.id,
                        ok=False,
                        error=f"пин {command.payload.pin} не настроен как выход",
                    )
                gpio.level = command.payload.level
                if command.payload.pulse_ms:
                    # Настоящая прошивка вернёт уровень обратно по таймеру;
                    # симулятору достаточно отразить это в ответе.
                    gpio.level = not command.payload.level
                return Esp32Reply(
                    command_id=command.id,
                    ok=True,
                    result={
                        "pin": gpio.pin,
                        "level": gpio.level,
                        "pulse_ms": command.payload.pulse_ms,
                        "simulated": True,
                    },
                )

            case Esp32CommandType.KVM_SWITCH:
                if not isinstance(command.payload, KvmSwitchPayload):
                    return Esp32Reply(
                        command_id=command.id, ok=False, error="в команде отсутствует payload"
                    )
                self._kvm_port = command.payload.port
                return Esp32Reply(
                    command_id=command.id,
                    ok=False,
                    error="физический KVM к симулятору не подключён",
                    result={"requested_port": command.payload.port},
                )

            case Esp32CommandType.GUARD_SNOOZE:
                if not isinstance(command.payload, GuardSnoozePayload):
                    return Esp32Reply(
                        command_id=command.id, ok=False, error="в команде отсутствует payload"
                    )
                minutes = command.payload.minutes
                self._guard_snooze_until = time.monotonic() + minutes * 60 if minutes > 0 else None
                return Esp32Reply(
                    command_id=command.id,
                    ok=True,
                    result={"minutes": minutes, "simulated": True},
                )

            case Esp32CommandType.REBOOT:
                self.reboot()
                return Esp32Reply(command_id=command.id, ok=True, result={"simulated": True})

            case _:  # pragma: no cover
                return Esp32Reply(
                    command_id=command.id, ok=False, error=f"неизвестная команда: {command.type}"
                )

    def _wake(self, command_id: str, payload: WakeOnLanPayload) -> Esp32Reply:
        entry: dict[str, object] = {
            "mac_address": payload.mac_address,
            "broadcast": payload.broadcast_address,
            "port": payload.port,
            "repeat": payload.repeat,
            "at": utcnow().isoformat(),
            "really_sent": False,
        }

        if self._send_real_wol:
            # Симулятор запущен на настоящем компьютере в той же сети,
            # поэтому при желании он может отправить НАСТОЯЩИЙ magic packet.
            # Это делает удалённое пробуждение рабочим ещё до появления платы.
            import socket

            from remo32_core.log import get_logger as _gl

            try:
                mac = payload.mac_address.replace(":", "").replace("-", "")
                packet = b"\xff" * 6 + bytes.fromhex(mac) * 16
                with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                    sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
                    for _ in range(payload.repeat):
                        sock.sendto(packet, (payload.broadcast_address, payload.port))
                entry["really_sent"] = True
            except OSError as exc:
                _gl("espsim.device").warning("не удалось отправить magic packet", error=str(exc))
                self._wol_log.append(entry)
                return Esp32Reply(command_id=command_id, ok=False, error=f"ошибка отправки: {exc}")

        self._wol_log.append(entry)
        log.info(
            "симулятор: обработан Wake-on-LAN",
            mac=payload.mac_address,
            really_sent=entry["really_sent"],
        )
        return Esp32Reply(
            command_id=command_id,
            ok=True,
            result={**entry, "simulated": not entry["really_sent"]},
        )
