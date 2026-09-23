"""Windows.

Реализовано по документации и НЕ проверено на живой машине — у автора
проекта обе машины на Linux. Структура готова, но перед использованием
требует проверки.
"""

from __future__ import annotations


class WindowsAdapter:
    name = "windows"

    def shutdown_argv(self, delay_seconds: int) -> list[str]:
        return ["shutdown", "/s", "/t", str(max(0, delay_seconds))]

    def reboot_argv(self, delay_seconds: int) -> list[str]:
        return ["shutdown", "/r", "/t", str(max(0, delay_seconds))]

    def cancel_argv(self) -> list[str] | None:
        return ["shutdown", "/a"]

    def lock_session_argv(self) -> list[str] | None:
        return ["rundll32.exe", "user32.dll,LockWorkStation"]

    def graphical_session_env(self) -> dict[str, str]:
        return {}  # в Windows графический сеанс не описывается переменными
