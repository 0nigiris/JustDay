"""Доменные модели Remo32.

Все модели — pydantic, потому что они одновременно служат схемой REST API
(FastAPI генерирует из них OpenAPI) и контрактом между контроллером, агентом
и симулятором ESP32.

Правило про недоступные данные: если датчик, GPU или температура недоступны,
поле равно ``None``. Модели никогда не выдумывают значения и не падают.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# --------------------------------------------------------------------------
# Состояния устройств
# --------------------------------------------------------------------------


class DeviceState(StrEnum):
    """Состояние устройства, как его показывает интерфейс.

    Разделение ``UNKNOWN`` и ``OFFLINE`` принципиально: ``UNKNOWN`` означает,
    что контроллер ещё не успел опросить устройство (например, только что
    стартовал), а ``OFFLINE`` — что опрос был и устройство не ответило.
    Показывать «выключено» вместо «пока не знаю» — вранье пользователю.
    """

    ONLINE = "online"
    OFFLINE = "offline"
    UNKNOWN = "unknown"
    CONNECTING = "connecting"
    ERROR = "error"


class PowerState(StrEnum):
    """Физическое состояние питания, если его умеет читать ESP32.

    Отличается от :class:`DeviceState`: ПК может быть физически включён
    (``ON``), но не отвечать агенту — это значит «завис», а не «выключен».
    """

    ON = "on"
    OFF = "off"
    UNKNOWN = "unknown"


# --------------------------------------------------------------------------
# Идентификаторы
# --------------------------------------------------------------------------

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")

DeviceId = Annotated[
    str,
    Field(
        min_length=1,
        max_length=64,
        pattern=_ID_RE.pattern,
        description=(
            "Идентификатор устройства: строчные латинские буквы, цифры, дефис, подчёркивание."
        ),
        examples=["vasya", "minevpsex"],
    ),
]

ActionId = Annotated[
    str,
    Field(
        min_length=1,
        max_length=64,
        pattern=_ID_RE.pattern,
        description="Идентификатор действия.",
        examples=["claude", "vscode", "mc-start"],
    ),
]

MacAddress = Annotated[
    str,
    Field(
        pattern=r"^([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}$",
        description="MAC-адрес для Wake-on-LAN.",
        examples=["7c:df:a1:00:11:22"],
    ),
]


def utcnow() -> datetime:
    """Текущее время в UTC. Вынесено, чтобы тесты могли подменить."""
    return datetime.now(UTC)


# --------------------------------------------------------------------------
# Системная статистика
# --------------------------------------------------------------------------


class StatsModel(BaseModel):
    """Базовая модель статистики: запрещает лишние поля, но допускает None."""

    model_config = ConfigDict(extra="forbid")


class CpuStats(StatsModel):
    usage_percent: float | None = Field(None, ge=0, le=100, description="Загрузка CPU, %")
    core_count: int | None = Field(None, gt=0, description="Число логических ядер")
    frequency_mhz: float | None = Field(None, gt=0, description="Текущая частота, МГц")
    load_average: tuple[float, float, float] | None = Field(
        None, description="Load average за 1/5/15 минут (только Unix)"
    )


class MemoryStats(StatsModel):
    total_bytes: int | None = Field(None, ge=0)
    used_bytes: int | None = Field(None, ge=0)
    available_bytes: int | None = Field(None, ge=0)
    usage_percent: float | None = Field(None, ge=0, le=100)
    swap_total_bytes: int | None = Field(None, ge=0)
    swap_used_bytes: int | None = Field(None, ge=0)


class DiskStats(StatsModel):
    mountpoint: str
    device: str | None = None
    total_bytes: int | None = Field(None, ge=0)
    used_bytes: int | None = Field(None, ge=0)
    free_bytes: int | None = Field(None, ge=0)
    usage_percent: float | None = Field(None, ge=0, le=100)


class NetworkStats(StatsModel):
    interface: str
    bytes_sent: int | None = Field(None, ge=0)
    bytes_received: int | None = Field(None, ge=0)
    packets_sent: int | None = Field(None, ge=0)
    packets_received: int | None = Field(None, ge=0)
    errors_in: int | None = Field(None, ge=0)
    errors_out: int | None = Field(None, ge=0)
    is_up: bool | None = None


class TemperatureReading(StatsModel):
    label: str = Field(description="Человекочитаемое имя датчика, например 'CPU Package'")
    celsius: float | None = Field(None, description="Температура; None если датчик недоступен")
    high_celsius: float | None = None
    critical_celsius: float | None = None


class GpuStats(StatsModel):
    """Статистика GPU.

    Все поля опциональны: у AMD и Intel через sysfs доступна лишь часть,
    у NVIDIA — почти всё, а без драйвера не доступно ничего.
    """

    index: int = Field(ge=0)
    name: str | None = None
    vendor: Literal["nvidia", "amd", "intel", "unknown"] = "unknown"
    utilization_percent: float | None = Field(None, ge=0, le=100)
    memory_total_bytes: int | None = Field(None, ge=0)
    memory_used_bytes: int | None = Field(None, ge=0)
    temperature_celsius: float | None = None
    power_watts: float | None = Field(None, ge=0)
    fan_percent: float | None = Field(None, ge=0, le=100)


class SystemStats(StatsModel):
    """Полный снимок состояния машины.

    Собирается агентом. Любой сборщик может вернуть ``None``/пустой список,
    не роняя остальные — см. ``remo32_agent.stats.collector``.
    """

    collected_at: datetime = Field(default_factory=utcnow)
    hostname: str | None = None
    platform: str | None = Field(None, description="linux / windows / darwin")
    uptime_seconds: float | None = Field(None, ge=0)
    boot_time: datetime | None = None
    cpu: CpuStats = Field(default_factory=CpuStats)
    memory: MemoryStats = Field(default_factory=MemoryStats)
    disks: list[DiskStats] = Field(default_factory=list)
    networks: list[NetworkStats] = Field(default_factory=list)
    temperatures: list[TemperatureReading] = Field(default_factory=list)
    gpus: list[GpuStats] = Field(default_factory=list)
    degraded: list[str] = Field(
        default_factory=list,
        description="Имена сборщиков, которые не смогли отработать. Пустой список — всё собралось.",
    )


# --------------------------------------------------------------------------
# Действия
# --------------------------------------------------------------------------


class ActionKind(StrEnum):
    """Как именно исполняется действие.

    Каждый вид имеет собственный исполнитель с собственной валидацией.
    Произвольная строка из конфига НИКОГДА не уходит в ``shell=True``.
    """

    EXEC = "exec"
    """Запуск программы списком аргументов, без оболочки."""

    SHELL_SCRIPT = "shell_script"
    """Запуск заранее записанного на диск скрипта. Путь валидируется."""

    SYSTEMD_USER = "systemd_user"
    """systemctl --user <verb> <unit>."""

    SYSTEMD_SYSTEM = "systemd_system"
    """systemctl <verb> <unit>. Требует прав, выдаваемых через polkit-правило."""

    TMUX = "tmux"
    """Команда, запускаемая внутри именованной tmux-сессии (переживает обрыв связи)."""

    DESKTOP = "desktop"
    """Запуск GUI-приложения в активном графическом сеансе пользователя."""

    POWER = "power"
    """Управление питанием: shutdown / reboot. Обрабатывается отдельно."""


class ActionDescriptor(BaseModel):
    """Описание действия, отдаваемое наружу.

    Намеренно НЕ содержит саму команду: интерфейсу она не нужна, а утечка
    внутренних путей в браузер — лишняя.
    """

    model_config = ConfigDict(extra="forbid")

    id: ActionId
    name: str = Field(description="Отображаемое имя, например «Claude Code»")
    description: str | None = None
    kind: ActionKind
    icon: str | None = Field(None, description="Эмодзи или имя иконки для интерфейса")
    group: str | None = Field(None, description="Группа для раскладки в интерфейсе")
    dangerous: bool = Field(
        False, description="Требует подтверждения в интерфейсе (перезагрузка, стоп сервера)"
    )
    timeout_seconds: float = Field(30.0, gt=0, le=3600)
    available: bool = Field(
        True,
        description=(
            "Есть ли на машине то, что действие запускает. Позволяет показать "
            "кнопку неактивной вместо ошибки после нажатия."
        ),
    )
    editable: bool = Field(
        False,
        description=(
            "Заведено через интерфейс и может быть в нём изменено. Действия из "
            "agent.toml редактировать нельзя: файл принадлежит хозяину машины, "
            "и переписывать его комментарии и порядок мы не вправе."
        ),
    )


class ActionEditorState(BaseModel):
    """Что интерфейс знает о правке кнопок на конкретной машине.

    ``actions`` — полные описания вместе с командами, а не дескрипторы: форме
    редактирования нужно показать то, что она собирается менять. Схема каждого
    описания зависит от вида действия и известна агенту — он же её и проверяет.
    Контроллер здесь только посредник и намеренно не пытается угадать формат:
    набор видов может отличаться от машины к машине.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = Field(description="Разрешена ли правка кнопок на этой машине")
    max_actions: int = Field(64, description="Предел на число заведённых кнопок")
    actions: list[dict[str, Any]] = Field(
        default_factory=list, description="Кнопки, заведённые через интерфейс"
    )
    kinds: list[ActionKind] = Field(
        default_factory=list, description="Виды действий, которые понимает этот агент"
    )


class ActionResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    action_id: ActionId
    success: bool
    started_at: datetime
    finished_at: datetime | None = None
    exit_code: int | None = None
    stdout: str | None = Field(None, description="Обрезано до лимита агента")
    stderr: str | None = None
    message: str | None = Field(None, description="Человекочитаемый итог для интерфейса")
    truncated: bool = False

    @property
    def duration_seconds(self) -> float | None:
        if self.finished_at is None:
            return None
        return (self.finished_at - self.started_at).total_seconds()


# --------------------------------------------------------------------------
# ПК
# --------------------------------------------------------------------------


class AgentHealth(BaseModel):
    """Ответ агента на /health. Лёгкий: его дёргают часто."""

    model_config = ConfigDict(extra="forbid")

    status: Literal["ok", "degraded"] = "ok"
    agent_version: str
    hostname: str
    platform: str
    uptime_seconds: float | None = None
    terminal_enabled: bool = False
    action_count: int = 0


class PcSummary(BaseModel):
    """ПК глазами контроллера — то, что рисует главный экран."""

    model_config = ConfigDict(extra="forbid")

    id: DeviceId
    name: str
    description: str | None = None
    state: DeviceState = DeviceState.UNKNOWN
    power_state: PowerState = PowerState.UNKNOWN
    last_seen: datetime | None = Field(None, description="Когда агент последний раз ответил")
    last_error: str | None = None
    address: str | None = Field(None, description="Адрес агента (host:port), как задан в конфиге")
    mac_address: str | None = None
    wake_supported: bool = False
    terminal_supported: bool = False
    stats: SystemStats | None = Field(None, description="Последний снимок; None если ПК не отвечал")
    stats_age_seconds: float | None = Field(
        None, description="Возраст снимка. Больше stale_after — интерфейс покажет данные тусклыми."
    )
    stale: bool = Field(False, description="Данные устарели, но ещё показываются")
    actions: list[ActionDescriptor] = Field(default_factory=list)


# --------------------------------------------------------------------------
# ESP32
# --------------------------------------------------------------------------


class GpioPinState(BaseModel):
    model_config = ConfigDict(extra="forbid")

    pin: int = Field(ge=0, le=48, description="Номер GPIO ESP32-S3")
    mode: Literal["input", "output", "unused"] = "unused"
    level: bool | None = Field(None, description="None если пин не сконфигурирован")
    label: str | None = None


class GuardConfig(BaseModel):
    """Настройки сторожа, как они записаны в самой плате.

    Плата отдаёт их вместе с состоянием, потому что консоль у неё только
    по USB, а живёт она от розетки. Без этих полей нельзя проверить по
    сети, туда ли вообще уходит magic packet: разбор неудачной побудки
    начинается именно с вопроса «а верный ли MAC записан».
    """

    model_config = ConfigDict(extra="ignore")

    enabled: bool | None = None
    host: str | None = Field(None, description="IP основного ПК в домашней сети")
    mac_address: str | None = Field(None, description="MAC, на который уходит magic packet")
    broadcast_address: str | None = None
    grace_minutes: int | None = Field(None, ge=0, description="Ждать перед первой побудкой")
    retry_minutes: int | None = Field(None, ge=0)
    max_attempts: int | None = Field(None, ge=0, description="0 — без предела")


class GuardStatus(BaseModel):
    """Состояние сторожа основного ПК на плате.

    Сторож существует потому, что контроллер работает на том самом ПК,
    который может умереть. Плата — единственный, кто способен заметить это
    и поднять машину сам, без телефона и без контроллера.
    """

    # Здесь намеренно "ignore", а не "forbid": эту структуру заполняет
    # прошивка, которая живёт своей жизнью и обновляется отдельно от
    # контроллера. Плата с более новой прошивкой не должна выглядеть
    # сломанной только потому, что научилась сообщать что-то ещё.
    model_config = ConfigDict(extra="ignore")

    state: str = Field(description="выключен, наблюдение, ПК пропал, побудка, ...")
    host_alive: bool | None = None
    attempts: int | None = Field(None, ge=0, description="Побудок в текущей серии")
    total_wakes: int | None = Field(None, ge=0, description="Побудок с запуска платы")
    last_seen_ms: float | None = Field(
        None, description="Время платы, когда ПК отвечал; -1 — не отвечал ни разу"
    )
    snooze_until_ms: float | None = Field(None, description="0 — сна нет")
    config: GuardConfig | None = Field(
        None, description="Настройки в плате; None — прошивка их ещё не отдаёт"
    )


class Esp32Status(BaseModel):
    """Состояние аппаратного контроллера.

    Одинаково для реального устройства и симулятора — в этом весь смысл:
    контроллер не знает, с кем разговаривает.
    """

    # Здесь намеренно "ignore", а не "forbid": эту структуру заполняет
    # прошивка, которая живёт своей жизнью и обновляется отдельно от
    # контроллера. Плата с более новой прошивкой не должна выглядеть
    # сломанной только потому, что научилась сообщать что-то ещё.
    model_config = ConfigDict(extra="ignore")

    state: DeviceState = DeviceState.UNKNOWN
    device_id: str | None = None
    firmware_version: str | None = None
    simulated: bool = Field(False, description="True — отвечает симулятор, а не железо")
    chip: str | None = Field(None, description="Например esp32s3")
    uptime_seconds: float | None = Field(None, ge=0)
    free_heap_bytes: int | None = Field(None, ge=0)
    min_free_heap_bytes: int | None = Field(None, ge=0)
    psram_present: bool | None = Field(
        None, description="False/None — прошивка работает без PSRAM, это штатный режим"
    )
    wifi_rssi_dbm: int | None = None
    wifi_ssid: str | None = None
    ip_address: str | None = None
    mac_address: str | None = None
    last_seen: datetime | None = None
    last_error: str | None = None
    reconnect_count: int | None = Field(None, ge=0)
    gpio: list[GpioPinState] = Field(default_factory=list)
    guard: GuardStatus | None = Field(
        None, description="Сторож основного ПК; None — прошивка его не поддерживает"
    )
    capabilities: list[str] = Field(
        default_factory=list,
        description="Что умеет прошивка: wol, gpio_in, gpio_out, guard, kvm, oled, sensors",
    )


# --------------------------------------------------------------------------
# Конверт ответа API
# --------------------------------------------------------------------------


class ApiError(BaseModel):
    model_config = ConfigDict(extra="forbid")

    code: str = Field(description="Машиночитаемый код, например pc_not_found")
    message: str = Field(description="Человекочитаемое описание")
    details: dict[str, Any] = Field(default_factory=dict)


class ApiResponse[T](BaseModel):
    """Единый конверт всех ответов API.

    Ровно одно из ``data``/``error`` заполнено. Клиенту не нужно гадать
    по HTTP-статусу, что произошло.
    """

    model_config = ConfigDict(extra="forbid")

    ok: bool
    data: T | None = None
    error: ApiError | None = None
    request_id: str | None = None

    @classmethod
    def success(cls, data: T, request_id: str | None = None) -> ApiResponse[T]:
        return cls(ok=True, data=data, request_id=request_id)

    @classmethod
    def failure(
        cls,
        code: str,
        message: str,
        *,
        details: dict[str, Any] | None = None,
        request_id: str | None = None,
    ) -> ApiResponse[T]:
        return cls(
            ok=False,
            error=ApiError(code=code, message=message, details=details or {}),
            request_id=request_id,
        )

    @field_validator("error")
    @classmethod
    def _check_envelope(cls, v: ApiError | None, info: Any) -> ApiError | None:
        if info.data.get("ok") and v is not None:
            raise ValueError("успешный ответ не может содержать error")
        return v
