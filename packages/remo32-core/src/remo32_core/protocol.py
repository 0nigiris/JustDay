"""Протокол обмена между контроллером, агентами и ESP32.

Здесь описан контракт, а не транспорт. Один и тот же
:class:`Esp32Command` уходит и в MQTT-топик, и в HTTP-запрос к реальному
устройству, и в симулятор — поэтому подменить транспорт можно, не трогая
остальной код.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Any, Literal
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from remo32_core.models import Esp32Status, MacAddress, utcnow

PROTOCOL_VERSION = 1

# --------------------------------------------------------------------------
# Заголовки HTTP
# --------------------------------------------------------------------------

HEADER_REQUEST_ID = "X-Remo32-Request-Id"
HEADER_AGENT_TOKEN = "X-Remo32-Agent-Token"  # noqa: S105 — имя заголовка, не секрет

# --------------------------------------------------------------------------
# Команды ESP32
# --------------------------------------------------------------------------


class Esp32CommandType(StrEnum):
    PING = "ping"
    STATUS = "status"
    WAKE_ON_LAN = "wake_on_lan"
    GPIO_READ = "gpio_read"
    GPIO_WRITE = "gpio_write"
    KVM_SWITCH = "kvm_switch"
    GUARD_SNOOZE = "guard_snooze"
    REBOOT = "reboot"


class WakeOnLanPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    mac_address: MacAddress
    broadcast_address: str = Field("255.255.255.255", description="Куда слать magic packet")
    port: int = Field(9, ge=1, le=65535)
    repeat: int = Field(3, ge=1, le=10, description="Сколько раз повторить пакет")


class GuardSnoozePayload(BaseModel):
    """Просьба к плате не будить ПК ближайшее время.

    Плата умеет сама поднимать основной ПК, когда тот пропал: контроллер
    работает на этом же ПК и себя разбудить не может. Обратная сторона —
    плановое выключение выглядит для платы точно так же, как авария.
    Поэтому контроллер предупреждает её заранее.
    """

    model_config = ConfigDict(extra="forbid")

    minutes: int = Field(
        ge=0,
        le=1440,
        description="Сколько минут не вмешиваться. 0 — отменить и снова следить.",
    )


class GpioReadPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pin: int = Field(ge=0, le=48)


class GpioWritePayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pin: int = Field(ge=0, le=48)
    level: bool
    pulse_ms: int | None = Field(
        None, ge=1, le=10_000, description="Если задано — импульс: выставить и вернуть обратно"
    )


class KvmSwitchPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    port: int = Field(ge=1, le=16, description="Номер входа KVM")


Esp32Payload = Annotated[
    WakeOnLanPayload
    | GpioReadPayload
    | GpioWritePayload
    | KvmSwitchPayload
    | GuardSnoozePayload
    | None,
    Field(description="Полезная нагрузка, зависит от типа команды"),
]


class Esp32Command(BaseModel):
    """Команда устройству. ``id`` нужен, чтобы сопоставить ответ с запросом."""

    model_config = ConfigDict(extra="forbid")

    protocol_version: int = PROTOCOL_VERSION
    id: str = Field(default_factory=lambda: uuid4().hex[:12])
    type: Esp32CommandType
    payload: Esp32Payload = None
    issued_at: Any = Field(default_factory=utcnow)


class Esp32Reply(BaseModel):
    """Ответ устройства на команду."""

    model_config = ConfigDict(extra="forbid")

    protocol_version: int = PROTOCOL_VERSION
    command_id: str
    ok: bool
    error: str | None = None
    status: Esp32Status | None = Field(None, description="Заполняется для команд ping/status")
    result: dict[str, Any] = Field(default_factory=dict)


# --------------------------------------------------------------------------
# MQTT
# --------------------------------------------------------------------------


class MqttTopics:
    """Схема топиков.

    Всё живёт под одним префиксом, чтобы на общем брокере не пересечься
    с чужими устройствами и чтобы права можно было выдать одним шаблоном.
    """

    def __init__(self, prefix: str, device_id: str) -> None:
        self.prefix = prefix.rstrip("/")
        self.device_id = device_id

    @property
    def command(self) -> str:
        """Контроллер пишет, устройство читает."""
        return f"{self.prefix}/{self.device_id}/cmd"

    @property
    def reply(self) -> str:
        """Устройство пишет, контроллер читает."""
        return f"{self.prefix}/{self.device_id}/reply"

    @property
    def status(self) -> str:
        """Периодический статус, retained."""
        return f"{self.prefix}/{self.device_id}/status"

    @property
    def availability(self) -> str:
        """LWT: ``online``/``offline``. Брокер сам поставит offline при обрыве."""
        return f"{self.prefix}/{self.device_id}/availability"


AVAILABILITY_ONLINE = "online"
AVAILABILITY_OFFLINE = "offline"


# --------------------------------------------------------------------------
# Терминал
# --------------------------------------------------------------------------


class TerminalClientMessage(BaseModel):
    """Сообщение из браузера в агент по WebSocket."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["input", "resize", "ping"]
    data: str | None = Field(None, description="Для input — вводимые байты в UTF-8")
    cols: int | None = Field(None, ge=1, le=1000)
    rows: int | None = Field(None, ge=1, le=1000)


class TerminalServerMessage(BaseModel):
    """Сообщение из агента в браузер."""

    model_config = ConfigDict(extra="forbid")

    type: Literal["output", "exit", "error", "pong", "ready"]
    data: str | None = None
    session: str | None = None
    exit_code: int | None = None
