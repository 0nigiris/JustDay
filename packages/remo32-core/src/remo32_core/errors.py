"""Иерархия ошибок Remo32.

Каждая ошибка несёт машиночитаемый `code` и HTTP-статус, чтобы API отдавал
одинаковые ответы независимо от того, где ошибка возникла.
"""

from __future__ import annotations

from typing import Any


class Remo32Error(Exception):
    """Базовая ошибка домена. Никогда не поднимается напрямую."""

    code: str = "internal_error"
    http_status: int = 500

    def __init__(self, message: str, /, **details: Any) -> None:
        super().__init__(message)
        self.message = message
        self.details: dict[str, Any] = details


class ConfigurationError(Remo32Error):
    """Конфигурация некорректна или неполна."""

    code = "configuration_error"
    http_status = 500


class NotFoundError(Remo32Error):
    """Запрошенный объект не существует."""

    code = "not_found"
    http_status = 404


class PcNotFoundError(NotFoundError):
    code = "pc_not_found"


class ActionNotFoundError(NotFoundError):
    code = "action_not_found"


class DeviceUnreachableError(Remo32Error):
    """Устройство не отвечает: выключено, вне сети или агент не запущен.

    Это ожидаемое состояние, а не сбой контроллера — отсюда 503, а не 500.
    """

    code = "device_unreachable"
    http_status = 503


class DeviceTimeoutError(DeviceUnreachableError):
    code = "device_timeout"


class ActionFailedError(Remo32Error):
    """Действие дошло до устройства, но завершилось неуспешно."""

    code = "action_failed"
    http_status = 502


class WakeFailedError(Remo32Error):
    """Не удалось отправить magic packet ни одним из доступных путей."""

    code = "wake_failed"
    http_status = 502


class AgentAuthError(Remo32Error):
    """Агент отверг токен контроллера.

    Отдельный класс, потому что путать это с «пользователь не вошёл»
    нельзя: при 401 браузер выбрасывал бы владельца на экран входа из-за
    чужой ошибки конфигурации. Виноват не пользователь, а рассогласование
    токенов между контроллером и агентом.
    """

    code = "agent_unauthorized"
    http_status = 502


class TerminalDisabledError(Remo32Error):
    """Удалённый терминал выключен в конфигурации."""

    code = "terminal_disabled"
    http_status = 403


class UnauthorizedError(Remo32Error):
    code = "unauthorized"
    http_status = 401


class ForbiddenError(Remo32Error):
    code = "forbidden"
    http_status = 403


class CapabilityUnavailableError(Remo32Error):
    """Возможность заявлена в API, но не реализована на этом железе.

    Пример: переключение KVM, пока физический KVM не подключён к ESP32.
    """

    code = "capability_unavailable"
    http_status = 501
