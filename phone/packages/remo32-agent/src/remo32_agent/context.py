"""Собранное состояние агента.

Один объект, который держит все службы и передаётся в маршруты. Ничего
глобального и изменяемого: тест создаёт свой контекст со своим
исполнителем команд и получает полностью изолированный агент.
"""

from __future__ import annotations

import platform as _platform
import socket
import time
from collections.abc import Callable
from typing import Annotated

from fastapi import Header

from remo32_agent import __version__
from remo32_agent.actions.runner import ActionExecutor, ActionRegistry
from remo32_agent.actions.store import ActionStore
from remo32_agent.approvals import ApprovalStore
from remo32_agent.config import AgentSettings
from remo32_agent.execution import CommandRunner, RecordingRunner, SubprocessRunner
from remo32_agent.platforms import PlatformAdapter, get_adapter
from remo32_agent.power import PowerPolicy, PowerService
from remo32_agent.security import TokenAuth
from remo32_agent.terminal.audit import TerminalAudit
from remo32_core.log import get_logger
from remo32_core.models import AgentHealth
from remo32_core.protocol import HEADER_AGENT_TOKEN

log = get_logger("agent.context")


class AgentContext:
    def __init__(
        self,
        settings: AgentSettings,
        *,
        runner: CommandRunner | None = None,
        adapter: PlatformAdapter | None = None,
    ) -> None:
        self.settings = settings
        self.started_at = time.monotonic()
        self.adapter: PlatformAdapter = adapter or get_adapter()

        # Если операции питания в режиме dry_run, то и остальные команды
        # разумно не выполнять: иначе поведение было бы непоследовательным.
        self.runner: CommandRunner = runner or (
            RecordingRunner() if settings.power.dry_run else SubprocessRunner()
        )

        self.auth = TokenAuth(
            settings.security.resolve_token(),
            allow_insecure=settings.security.allow_insecure_no_token,
        )
        store = (
            ActionStore(settings.actions_editor.store_path)
            if settings.actions_editor.enabled
            else None
        )
        self.approvals = ApprovalStore(
            settings.approvals.directory, enabled=settings.approvals.enabled
        )
        self.registry = ActionRegistry(settings.actions, store)
        self.executor = ActionExecutor(self.registry, self.runner, self.adapter)
        self.power = PowerService(
            self.adapter,
            self.runner,
            PowerPolicy(
                shutdown_enabled=settings.power.shutdown_enabled,
                reboot_enabled=settings.power.restart_enabled,
                lock_enabled=settings.power.lock_enabled,
                dry_run=settings.power.dry_run,
                delay_seconds=settings.power.delay_seconds,
            ),
        )
        self.audit = TerminalAudit(
            settings.terminal.audit_log,
            max_bytes=settings.terminal.audit_max_bytes,
            keep=settings.terminal.audit_keep,
        )

    @property
    def auth_dependency(self) -> Callable[..., None]:
        """Зависимость FastAPI, замкнутая на настроенный :class:`TokenAuth`."""

        auth = self.auth

        def _verify(
            token: Annotated[str | None, Header(alias=HEADER_AGENT_TOKEN)] = None,
        ) -> None:
            auth.verify(token)

        return _verify

    def terminal_session_name(self, raw: str) -> str:
        """Приводит имя сессии к безопасному виду с префиксом.

        Префикс гарантирует, что агент не подключится к посторонней
        tmux-сессии пользователя и не создаст путаницы.

        Исключение — сессии собственных кнопок вида ``tmux``: «Claude Code»
        создаёт сессию с тем именем, которое записано в настройках, и
        терминал обязан попадать именно в неё. Иначе кнопка запускает одно,
        терминал открывает другое, и обе выглядят сломанными.
        """
        cleaned = "".join(ch for ch in raw if ch.isalnum() or ch in "_-")[:32] or "main"
        if cleaned in self.registry.tmux_sessions():
            return cleaned
        prefix = self.settings.terminal.session_prefix
        return cleaned if cleaned.startswith(f"{prefix}-") else f"{prefix}-{cleaned}"

    def health(self) -> AgentHealth:
        return AgentHealth(
            status="ok",
            agent_version=__version__,
            hostname=socket.gethostname(),
            platform=_platform.system().lower(),
            uptime_seconds=time.monotonic() - self.started_at,
            terminal_enabled=self.settings.terminal.enabled,
            action_count=len(self.executor.registry),
        )
