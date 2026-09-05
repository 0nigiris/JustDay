"""Исполнение предопределённых действий.

Реестр действий заполняется из конфигурации. API умеет только одно:
назвать идентификатор уже описанного действия. Сконструировать новую
команду через API невозможно — это и есть граница между «безопасными
предопределёнными действиями» и удалённой оболочкой.
"""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime

from remo32_agent.actions.models import (
    ActionConfig,
    DesktopAction,
    ExecAction,
    ShellScriptAction,
    SystemdAction,
    TmuxAction,
)
from remo32_agent.execution import CommandResult, CommandRunner
from remo32_agent.platforms import PlatformAdapter
from remo32_core.errors import ActionNotFoundError
from remo32_core.log import get_logger
from remo32_core.models import ActionDescriptor, ActionKind, ActionResult, utcnow

log = get_logger("agent.actions")


class ActionRegistry:
    """Реестр действий, доступных на этой машине."""

    def __init__(self, actions: Iterable[ActionConfig]) -> None:
        self._actions: dict[str, ActionConfig] = {}
        for action in actions:
            if action.id in self._actions:
                raise ValueError(f"дублирующийся идентификатор действия: {action.id}")
            self._actions[action.id] = action

    def __len__(self) -> int:
        return len(self._actions)

    def __contains__(self, action_id: object) -> bool:
        return action_id in self._actions

    def get(self, action_id: str) -> ActionConfig:
        try:
            return self._actions[action_id]
        except KeyError:
            raise ActionNotFoundError(
                f"действие не найдено: {action_id}", action_id=action_id
            ) from None

    def descriptors(self) -> list[ActionDescriptor]:
        """Список действий для интерфейса, отсортированный по группе и имени."""
        items = [self._describe(a) for a in self._actions.values()]
        return sorted(items, key=lambda d: (d.group or "", d.name))

    @staticmethod
    def _describe(action: ActionConfig) -> ActionDescriptor:
        descriptor = action.descriptor()
        descriptor.available = action.is_available()
        if not descriptor.available:
            descriptor.description = _mark_unavailable(action, descriptor.description)
        return descriptor

    def availability(self) -> dict[str, bool]:
        return {a.id: a.is_available() for a in self._actions.values()}


def _mark_unavailable(action: ActionConfig, description: str | None) -> str:
    exe = action.executable() or "программа"
    note = f"недоступно: {exe} не найден(а) на этой машине"
    return f"{description} — {note}" if description else note


class ActionExecutor:
    """Превращает описание действия в конкретный ``argv`` и запускает его."""

    def __init__(
        self,
        registry: ActionRegistry,
        runner: CommandRunner,
        adapter: PlatformAdapter,
    ) -> None:
        self._registry = registry
        self._runner = runner
        self._adapter = adapter

    @property
    def registry(self) -> ActionRegistry:
        return self._registry

    async def run(self, action_id: str) -> ActionResult:
        action = self._registry.get(action_id)
        started = utcnow()

        if not action.is_available():
            log.warning("действие недоступно", action=action_id, exe=action.executable())
            return ActionResult(
                action_id=action_id,
                success=False,
                started_at=started,
                finished_at=utcnow(),
                message=_mark_unavailable(action, None),
            )

        if (
            isinstance(action, TmuxAction)
            and action.reuse
            and await self._tmux_session_exists(action.session)
        ):
            log.info("tmux-сессия уже существует", action=action_id, session=action.session)
            return ActionResult(
                action_id=action_id,
                success=True,
                started_at=started,
                finished_at=utcnow(),
                exit_code=0,
                message=f"сессия «{action.session}» уже запущена, подключайтесь терминалом",
            )

        argv = self._build_argv(action)
        env = dict(action.env)
        if isinstance(action, DesktopAction):
            env = {**self._adapter.graphical_session_env(), **env}

        cwd = action.resolved_workdir()
        if cwd is not None and not cwd.is_dir():
            return ActionResult(
                action_id=action_id,
                success=False,
                started_at=started,
                finished_at=utcnow(),
                message=f"рабочий каталог не существует: {cwd}",
            )

        log.info("выполняется действие", action=action_id, kind=action.kind, argv=argv)
        result = await self._runner.run(
            argv,
            cwd=str(cwd) if cwd else None,
            env=env or None,
            timeout=action.timeout_seconds,
            detach=action.detach,
        )
        return _result_from_command(action_id, started, result)

    def _build_argv(self, action: ActionConfig) -> list[str]:
        """Единственное место, где описание превращается в команду."""
        match action:
            case ExecAction() | DesktopAction():
                return list(action.argv)
            case ShellScriptAction():
                return [str(action.script), *action.args]
            case SystemdAction():
                base = ["systemctl"]
                if action.kind is ActionKind.SYSTEMD_USER:
                    base.append("--user")
                return [*base, action.verb, action.unit]
            case TmuxAction():
                argv = ["tmux", "new-session", "-d", "-s", action.session]
                workdir = action.resolved_workdir()
                if workdir is not None:
                    argv += ["-c", str(workdir)]
                argv.append(action.command_string())
                return argv
            case _:  # pragma: no cover — исчерпывающий match по union
                raise TypeError(f"неизвестный вид действия: {type(action)!r}")

    async def _tmux_session_exists(self, session: str) -> bool:
        result = await self._runner.run(["tmux", "has-session", "-t", f"={session}"], timeout=5.0)
        return result.exit_code == 0


def _result_from_command(action_id: str, started: datetime, result: CommandResult) -> ActionResult:
    if result.detached:
        message = "запущено в фоне"
    elif result.timed_out:
        message = "превышен таймаут"
    elif result.success:
        message = "выполнено"
    else:
        message = result.stderr.strip()[:300] or f"код выхода {result.exit_code}"

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
