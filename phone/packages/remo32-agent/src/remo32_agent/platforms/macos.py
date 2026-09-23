"""macOS.

Как и Windows, реализовано по документации и не проверено на железе.
"""

from __future__ import annotations


class MacosAdapter:
    name = "darwin"

    def shutdown_argv(self, delay_seconds: int) -> list[str]:
        if delay_seconds <= 0:
            return ["shutdown", "-h", "now"]
        return ["shutdown", "-h", f"+{max(1, (delay_seconds + 59) // 60)}"]

    def reboot_argv(self, delay_seconds: int) -> list[str]:
        if delay_seconds <= 0:
            return ["shutdown", "-r", "now"]
        return ["shutdown", "-r", f"+{max(1, (delay_seconds + 59) // 60)}"]

    def cancel_argv(self) -> list[str] | None:
        return ["killall", "shutdown"]

    def lock_session_argv(self) -> list[str] | None:
        return [
            "/System/Library/CoreServices/Menu Extras/User.menu/Contents/Resources/CGSession",
            "-suspend",
        ]

    def graphical_session_env(self) -> dict[str, str]:
        return {}
