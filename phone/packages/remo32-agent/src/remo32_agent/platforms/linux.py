"""Linux — основная платформа проекта.

Выключение идёт через ``systemctl``, а не через ``shutdown``: systemd
корректно завершает пользовательские сессии и не требует прав root,
если настроено правило polkit (см. ``deploy/polkit``).
"""

from __future__ import annotations

import os
import subprocess

from remo32_core.log import get_logger

log = get_logger("agent.platform.linux")

# Переменные, без которых GUI-приложение не найдёт экран и шину.
_GRAPHICAL_ENV_KEYS = (
    "DISPLAY",
    "WAYLAND_DISPLAY",
    "XDG_RUNTIME_DIR",
    "XDG_SESSION_TYPE",
    "XDG_CURRENT_DESKTOP",
    "DBUS_SESSION_BUS_ADDRESS",
    "XAUTHORITY",
    "QT_QPA_PLATFORM",
)


class LinuxAdapter:
    name = "linux"

    def shutdown_argv(self, delay_seconds: int) -> list[str]:
        # systemd понимает только минуты в +N, поэтому секунды округляем вверх.
        if delay_seconds <= 0:
            return ["systemctl", "poweroff"]
        minutes = max(1, (delay_seconds + 59) // 60)
        return ["shutdown", "-P", f"+{minutes}"]

    def reboot_argv(self, delay_seconds: int) -> list[str]:
        if delay_seconds <= 0:
            return ["systemctl", "reboot"]
        minutes = max(1, (delay_seconds + 59) // 60)
        return ["shutdown", "-r", f"+{minutes}"]

    def cancel_argv(self) -> list[str] | None:
        return ["shutdown", "-c"]

    def lock_session_argv(self) -> list[str] | None:
        return ["loginctl", "lock-session"]

    def graphical_session_env(self) -> dict[str, str]:
        """Собирает окружение сеанса.

        Сначала пробуем то, что уже есть в процессе (агент запущен как
        пользовательская служба — тогда всё на месте), затем добираем
        недостающее из ``systemctl --user show-environment``.
        """
        env = {k: v for k in _GRAPHICAL_ENV_KEYS if (v := os.environ.get(k))}

        if "WAYLAND_DISPLAY" in env or "DISPLAY" in env:
            env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
            return env

        try:
            proc = subprocess.run(
                ["systemctl", "--user", "show-environment"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
            log.debug("не удалось прочитать окружение сеанса", error=str(exc))
            return env

        if proc.returncode == 0:
            for line in proc.stdout.splitlines():
                key, _, value = line.partition("=")
                if key in _GRAPHICAL_ENV_KEYS and value:
                    env.setdefault(key, value)

        if env:
            env.setdefault("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")
        return env
