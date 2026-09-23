"""Выбор платформенного адаптера."""

from __future__ import annotations

import platform as _stdlib_platform

from remo32_agent.platforms.base import PlatformAdapter, UnsupportedOperationError
from remo32_agent.platforms.linux import LinuxAdapter
from remo32_agent.platforms.macos import MacosAdapter
from remo32_agent.platforms.windows import WindowsAdapter

__all__ = [
    "LinuxAdapter",
    "MacosAdapter",
    "PlatformAdapter",
    "UnsupportedOperationError",
    "WindowsAdapter",
    "get_adapter",
]

_ADAPTERS: dict[str, type[LinuxAdapter | WindowsAdapter | MacosAdapter]] = {
    "linux": LinuxAdapter,
    "windows": WindowsAdapter,
    "darwin": MacosAdapter,
}


def get_adapter(system: str | None = None) -> PlatformAdapter:
    """Адаптер для текущей (или явно заданной) системы.

    Явное указание нужно тестам: так набор argv для Windows проверяется
    на Linux-машине.
    """
    key = (system or _stdlib_platform.system()).lower()
    try:
        return _ADAPTERS[key]()
    except KeyError:
        raise UnsupportedOperationError(f"платформа не поддерживается: {key}") from None
