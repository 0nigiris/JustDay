"""Контракт платформенного адаптера.

Всё, что различается между Linux, Windows и macOS, живёт за этим интерфейсом.
Остальной код агента об операционной системе не знает ничего.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable


class UnsupportedOperationError(RuntimeError):
    """Операция не поддерживается на этой платформе."""


@runtime_checkable
class PlatformAdapter(Protocol):
    """Платформенно-зависимые операции."""

    name: str

    def shutdown_argv(self, delay_seconds: int) -> list[str]:
        """Команда корректного выключения."""
        ...

    def reboot_argv(self, delay_seconds: int) -> list[str]:
        """Команда перезагрузки."""
        ...

    def cancel_argv(self) -> list[str] | None:
        """Команда отмены отложенного выключения, если платформа это умеет."""
        ...

    def lock_session_argv(self) -> list[str] | None:
        """Команда блокировки экрана. ``None`` — платформа не умеет."""
        ...

    def graphical_session_env(self) -> dict[str, str]:
        """Переменные окружения активного графического сеанса.

        Нужны, чтобы запущенное из службы GUI-приложение нашло экран.
        Пустой словарь — графической сессии нет (сервер без монитора).
        """
        ...
