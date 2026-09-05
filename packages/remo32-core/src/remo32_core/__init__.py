"""Общее ядро Remo32: доменные модели, протокол и утилиты.

Пакет импортируют контроллер, агент и симулятор ESP32. Из тяжёлых
зависимостей здесь только FastAPI (ради общего HTTP-слоя в
``remo32_core.http``); psutil, httpx и прочее живут в конкретных службах.
"""

from remo32_core.errors import (
    ActionFailedError,
    ActionNotFoundError,
    AgentAuthError,
    DeviceUnreachableError,
    Remo32Error,
    TerminalDisabledError,
    WakeFailedError,
)
from remo32_core.models import (
    ActionDescriptor,
    ActionKind,
    ActionResult,
    ApiError,
    ApiResponse,
    CpuStats,
    DeviceState,
    DiskStats,
    Esp32Status,
    GpuStats,
    MemoryStats,
    NetworkStats,
    PcSummary,
    SystemStats,
    TemperatureReading,
)

__all__ = [
    "ActionDescriptor",
    "ActionFailedError",
    "ActionKind",
    "ActionNotFoundError",
    "ActionResult",
    "AgentAuthError",
    "ApiError",
    "ApiResponse",
    "CpuStats",
    "DeviceState",
    "DeviceUnreachableError",
    "DiskStats",
    "Esp32Status",
    "GpuStats",
    "MemoryStats",
    "NetworkStats",
    "PcSummary",
    "Remo32Error",
    "SystemStats",
    "TemperatureReading",
    "TerminalDisabledError",
    "WakeFailedError",
]
