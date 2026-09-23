"""Исполнение предопределённых действий.

Реестр действий заполняется из двух файлов: ``agent.toml``, который ведёт
хозяин машины руками, и ``actions.toml``, за которым стоит кнопка «Добавить»
в интерфейсе. Разница между ними — в том, кто вправе их переписывать; см.
:mod:`remo32_agent.actions.store`.

Запуск устроен одинаково для обоих: API умеет только назвать идентификатор
уже описанного действия. Даже когда описание пришло из интерфейса, оно
проходит ту же типизированную валидацию и превращается в ``argv``, а не в
строку для оболочки. Произвольная команда не может появиться ни на одном
из путей.
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
from remo32_agent.actions.store import ActionStore
from remo32_agent.execution import CommandResult, CommandRunner
from remo32_agent.platforms import PlatformAdapter
from remo32_core.errors import (
    ActionNotFoundError,
    ActionReadOnlyError,
    ActionsNotEditableError,
)
from remo32_core.log import get_logger
from remo32_core.models import ActionDescriptor, ActionKind, ActionResult, utcnow

log = get_logger("agent.actions")


class ActionRegistry:
    """Реестр действий, доступных на этой машине.

    Действия из ``agent.toml`` неизменяемы; действия из хранилища (файл
    ``actions.toml``) можно править из интерфейса. При совпадении
    идентификаторов побеждает ``agent.toml``: файл, который человек написал
    руками, не должен молча подменяться кнопкой с телефона.
    """

    def __init__(
        self,
        actions: Iterable[ActionConfig],
        store: ActionStore | None = None,
    ) -> None:
        self._static: dict[str, ActionConfig] = {}
        for action in actions:
            if action.id in self._static:
                raise ValueError(f"дублирующийся идентификатор действия: {action.id}")
            self._static[action.id] = action
        self._store = store

    @property
    def store(self) -> ActionStore | None:
        return self._store

    def managed(self) -> list[ActionConfig]:
        """Действия, заведённые через интерфейс. Перечитываются при каждом вызове."""
        if self._store is None:
            return []
        return [a for a in self._store.load() if a.id not in self._static]

    def is_editable(self, action_id: str) -> bool:
        return any(a.id == action_id for a in self.managed())

    @property
    def _actions(self) -> dict[str, ActionConfig]:
        merged: dict[str, ActionConfig] = {a.id: a for a in self.managed()}
        merged.update(self._static)
        return merged

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

    def tmux_sessions(self) -> set[str]:
        """Имена tmux-сессий, которые создают кнопки.

        Веб-терминалу они нужны, чтобы подключиться именно к той сессии,
        которую человек только что запустил кнопкой «Claude Code», а не к
        пустой новой: раньше кнопка и терминал открывали разные сессии, и
        обе выглядели неработающими.
        """
        return {a.session for a in self._actions.values() if isinstance(a, TmuxAction)}

    def descriptors(self) -> list[ActionDescriptor]:
        """Список действий для интерфейса, отсортированный по группе и имени."""
        editable = {a.id for a in self.managed()}
        items = [self._describe(a, a.id in editable) for a in self._actions.values()]
        return sorted(items, key=lambda d: (d.group or "", d.name))

    @staticmethod
    def _describe(action: ActionConfig, editable: bool = False) -> ActionDescriptor:
        descriptor = action.descriptor()
        descriptor.available = action.is_available()
        descriptor.editable = editable
        if not descriptor.available:
            descriptor.description = _mark_unavailable(action, descriptor.description)
        return descriptor

    # --- правка из интерфейса -------------------------------------------

    def upsert(self, action: ActionConfig) -> None:
        """Заводит новую кнопку или заменяет существующую."""
        store = self._require_store()
        if action.id in self._static:
            raise ActionReadOnlyError(
                f"кнопка «{action.id}» описана в agent.toml и меняется только там",
                action_id=action.id,
            )
        current = [a for a in store.load() if a.id != action.id]
        current.append(action)
        store.save(current)

    def delete(self, action_id: str) -> None:
        store = self._require_store()
        if action_id in self._static:
            raise ActionReadOnlyError(
                f"кнопка «{action_id}» описана в agent.toml и удаляется только там",
                action_id=action_id,
            )
        current = store.load()
        if not any(a.id == action_id for a in current):
            raise ActionNotFoundError(f"кнопка не найдена: {action_id}", action_id=action_id)
        store.save([a for a in current if a.id != action_id])

    def _require_store(self) -> ActionStore:
        if self._store is None:
            raise ActionsNotEditableError("правка кнопок через интерфейс выключена")
        return self._store

    def describe(self, action_id: str) -> ActionDescriptor:
        """Дескриптор одного действия — то, что интерфейс покажет после сохранения."""
        return self._describe(self.get(action_id), self.is_editable(action_id))

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
            capture=action.captures_output(),
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
