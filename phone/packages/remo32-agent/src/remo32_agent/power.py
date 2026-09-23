"""Управление питанием: выключение, перезагрузка, блокировка экрана.

Самая опасная часть агента, поэтому здесь три независимых предохранителя:

1. ``enabled`` — операции можно полностью запретить в конфигурации;
2. ``dry_run`` — команда логируется, но не выполняется;
3. исполнитель команд внедряется снаружи, и автотесты подставляют
   :class:`~remo32_agent.execution.RecordingRunner`, который физически
   не способен ничего выключить.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from remo32_agent.execution import CommandResult, CommandRunner
from remo32_agent.platforms import PlatformAdapter
from remo32_core.log import get_logger
from remo32_core.models import ActionResult, utcnow

log = get_logger("agent.power")


@dataclass(frozen=True, slots=True)
class PowerPolicy:
    """Что именно разрешено делать с питанием этой машины."""

    shutdown_enabled: bool = True
    reboot_enabled: bool = True
    lock_enabled: bool = True
    dry_run: bool = False
    delay_seconds: int = 5
    """Задержка перед выполнением: даёт шанс отменить случайное нажатие."""


class PowerService:
    def __init__(
        self,
        adapter: PlatformAdapter,
        runner: CommandRunner,
        policy: PowerPolicy | None = None,
    ) -> None:
        self._adapter = adapter
        self._runner = runner
        self._policy = policy or PowerPolicy()

    @property
    def policy(self) -> PowerPolicy:
        return self._policy

    async def shutdown(self) -> ActionResult:
        if not self._policy.shutdown_enabled:
            return self._refused("shutdown", "выключение запрещено конфигурацией")
        argv = self._adapter.shutdown_argv(self._policy.delay_seconds)
        return await self._execute("shutdown", argv)

    async def reboot(self) -> ActionResult:
        if not self._policy.reboot_enabled:
            return self._refused("restart", "перезагрузка запрещена конфигурацией")
        argv = self._adapter.reboot_argv(self._policy.delay_seconds)
        return await self._execute("restart", argv)

    async def cancel(self) -> ActionResult:
        argv = self._adapter.cancel_argv()
        if argv is None:
            return self._refused("cancel", "платформа не умеет отменять отложенное выключение")
        return await self._execute("cancel", argv)

    async def lock(self) -> ActionResult:
        if not self._policy.lock_enabled:
            return self._refused("lock", "блокировка запрещена конфигурацией")
        argv = self._adapter.lock_session_argv()
        if argv is None:
            return self._refused("lock", "платформа не умеет блокировать экран")
        return await self._execute("lock", argv)

    async def _execute(self, action_id: str, argv: list[str]) -> ActionResult:
        started = utcnow()
        if self._policy.dry_run:
            log.warning("dry-run: операция питания не выполнена", action=action_id, argv=argv)
            return ActionResult(
                action_id=action_id,
                success=True,
                started_at=started,
                finished_at=utcnow(),
                exit_code=0,
                message=f"dry-run: команда {' '.join(argv)} НЕ выполнялась",
            )

        log.warning("операция питания", action=action_id, argv=argv)
        result = await self._runner.run(argv, timeout=20.0)
        return _to_action_result(action_id, started, result, self._policy.delay_seconds)

    @staticmethod
    def _refused(action_id: str, reason: str) -> ActionResult:
        now = utcnow()
        log.warning("операция питания отклонена", action=action_id, reason=reason)
        return ActionResult(
            action_id=action_id,
            success=False,
            started_at=now,
            finished_at=now,
            message=reason,
        )


def _to_action_result(
    action_id: str, started: datetime, result: CommandResult, delay: int
) -> ActionResult:
    if result.success:
        message = (
            f"команда принята, выполнение через ~{delay} с" if delay > 0 else "команда принята"
        )
    else:
        message = result.stderr.strip() or f"код выхода {result.exit_code}"
    return ActionResult(
        action_id=action_id,
        success=result.success,
        started_at=started,
        finished_at=utcnow(),
        exit_code=result.exit_code,
        stdout=result.stdout or None,
        stderr=result.stderr or None,
        message=message,
        truncated=result.truncated,
    )
