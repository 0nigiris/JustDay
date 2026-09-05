"""Типизированное описание действий из конфигурации.

Ключевая идея безопасности: в конфиге НЕ хранится строка, которую можно
скормить оболочке. Каждый вид действия — отдельная модель со своим набором
полей, и каждая знает, как превратить себя в ``argv`` (список аргументов),
который уходит в ``subprocess`` без ``shell=True``.

Строка вида ``cd ~/JII && claude -c`` из технического задания раскладывается
на ``kind = "tmux"``, ``workdir = "~/JII"``, ``argv = ["claude", "-c"]``.
Тот же результат, но без интерпретации пользовательского текста оболочкой.
"""

from __future__ import annotations

import os
import shlex
import shutil
from pathlib import Path
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from remo32_core.models import ActionDescriptor, ActionId, ActionKind


class _ActionBase(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: ActionId
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    icon: str | None = Field(None, max_length=16)
    group: str | None = Field(None, max_length=64)
    dangerous: bool = False
    timeout_seconds: float = Field(30.0, gt=0, le=3600)
    workdir: str | None = Field(None, description="Рабочий каталог; ~ раскрывается")
    env: dict[str, str] = Field(
        default_factory=dict, description="Дополнительные переменные окружения"
    )
    detach: bool = Field(
        False,
        description=(
            "Не ждать завершения. Для GUI-приложений и долгих процессов: "
            "иначе действие «запустить Steam» висело бы, пока Steam не закроют."
        ),
    )

    def resolved_workdir(self) -> Path | None:
        if self.workdir is None:
            return None
        return Path(self.workdir).expanduser()

    def descriptor(self) -> ActionDescriptor:
        return ActionDescriptor(
            id=self.id,
            name=self.name,
            description=self.description,
            kind=ActionKind(self.kind),  # type: ignore[attr-defined]
            icon=self.icon,
            group=self.group,
            dangerous=self.dangerous,
            timeout_seconds=self.timeout_seconds,
        )

    def executable(self) -> str | None:
        """Исполняемый файл, наличие которого определяет доступность действия."""
        return None

    def is_available(self) -> bool:
        """Есть ли на машине то, что действие пытается запустить.

        Позволяет интерфейсу показать кнопку серой, а не выдать ошибку
        после нажатия.
        """
        exe = self.executable()
        if exe is None:
            return True
        if "/" in exe:
            return os.access(Path(exe).expanduser(), os.X_OK)
        return shutil.which(exe) is not None


class ExecAction(_ActionBase):
    """Запуск программы напрямую, без оболочки. Самый безопасный вид."""

    kind: Literal[ActionKind.EXEC] = ActionKind.EXEC
    argv: list[str] = Field(min_length=1, description="Программа и её аргументы")

    @field_validator("argv")
    @classmethod
    def _no_empty(cls, v: list[str]) -> list[str]:
        if not v[0].strip():
            raise ValueError("первый элемент argv должен быть именем программы")
        return v

    def executable(self) -> str | None:
        return self.argv[0]


class ShellScriptAction(_ActionBase):
    """Запуск заранее написанного скрипта с диска.

    Скрипт — это файл, который пользователь положил сам и который лежит вне
    зоны действия API. Так можно выразить любую логику, не давая контроллеру
    возможности сконструировать произвольную команду.
    """

    kind: Literal[ActionKind.SHELL_SCRIPT] = ActionKind.SHELL_SCRIPT
    script: str = Field(description="Путь к исполняемому файлу")
    args: list[str] = Field(default_factory=list)

    @field_validator("script")
    @classmethod
    def _absolute(cls, v: str) -> str:
        p = Path(v).expanduser()
        if not p.is_absolute():
            raise ValueError("путь к скрипту должен быть абсолютным")
        return v

    def executable(self) -> str | None:
        return self.script


class SystemdAction(_ActionBase):
    """Управление systemd-юнитом.

    ``verb`` ограничен белым списком: ``systemctl`` не должен получать
    произвольный глагол вроде ``mask`` или ``link``.
    """

    kind: Literal[ActionKind.SYSTEMD_USER, ActionKind.SYSTEMD_SYSTEM]
    unit: str = Field(pattern=r"^[A-Za-z0-9@:._\\-]+$", max_length=128)
    verb: Literal["start", "stop", "restart", "reload", "status", "is-active"] = "start"

    def executable(self) -> str | None:
        return "systemctl"


class TmuxAction(_ActionBase):
    """Запуск команды внутри именованной tmux-сессии.

    Именно так запускается ``claude -c``: процесс живёт в tmux, поэтому
    обрыв связи с телефоном его не убивает, а веб-терминал позже
    подключается к той же сессии.
    """

    kind: Literal[ActionKind.TMUX] = ActionKind.TMUX
    session: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    argv: list[str] = Field(min_length=1)
    reuse: bool = Field(
        True, description="Если сессия уже есть — не создавать новую, а оставить как есть"
    )

    def executable(self) -> str | None:
        return "tmux"

    def command_string(self) -> str:
        """Команда для tmux одной строкой.

        tmux всё равно запускает её через ``sh -c``, поэтому мы сами
        экранируем каждый аргумент через :func:`shlex.quote`. Экранируем
        МЫ, а не пользователь — в конфиге лежит список, а не строка,
        и склеить его в инъекцию невозможно.
        """
        return " ".join(shlex.quote(a) for a in self.argv)


class DesktopAction(_ActionBase):
    """Запуск GUI-приложения в активном графическом сеансе.

    Отличается от :class:`ExecAction` тем, что процессу передаётся окружение
    графической сессии (``WAYLAND_DISPLAY``/``DISPLAY``/``DBUS_SESSION_BUS_ADDRESS``),
    иначе приложение не найдёт экран.
    """

    kind: Literal[ActionKind.DESKTOP] = ActionKind.DESKTOP
    argv: list[str] = Field(min_length=1)
    detach: bool = True

    def executable(self) -> str | None:
        return self.argv[0]


ActionConfig = Annotated[
    ExecAction | ShellScriptAction | SystemdAction | TmuxAction | DesktopAction,
    Field(discriminator="kind"),
]
