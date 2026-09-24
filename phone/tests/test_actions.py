"""Запуск предопределённых действий."""

from __future__ import annotations

import pytest

from remo32_agent.actions.models import DesktopAction, ExecAction, MacroAction
from remo32_agent.actions.runner import ActionExecutor, ActionRegistry
from remo32_agent.execution import CommandResult, RecordingRunner
from remo32_agent.platforms import get_adapter
from remo32_core.errors import ActionNotFoundError


@pytest.fixture
def executor(sample_actions: list[object], runner: RecordingRunner) -> ActionExecutor:
    return ActionExecutor(
        ActionRegistry(sample_actions),  # type: ignore[arg-type]
        runner,
        get_adapter("linux"),
    )


async def test_unknown_action_is_rejected(executor: ActionExecutor) -> None:
    with pytest.raises(ActionNotFoundError):
        await executor.run("не-существует")


async def test_exec_action_runs_without_shell(
    executor: ActionExecutor, runner: RecordingRunner
) -> None:
    result = await executor.run("beep")
    assert result.success
    # Команда — список аргументов, а не строка для оболочки.
    assert runner.last_argv == ["/usr/bin/true"]


async def test_systemd_action_builds_user_scoped_command(
    executor: ActionExecutor, runner: RecordingRunner
) -> None:
    await executor.run("mc-start")
    assert runner.last_argv == ["systemctl", "--user", "start", "minecraft.service"]


async def test_tmux_action_creates_detached_session(
    executor: ActionExecutor, runner: RecordingRunner
) -> None:
    # Сессии ещё нет: has-session возвращает ненулевой код.
    runner.responses["tmux"] = CommandResult(["tmux"], exit_code=1, stdout="", stderr="")
    await executor.run("claude")

    checks: list[list[str]] = [c["argv"] for c in runner.calls]  # type: ignore[misc]
    assert ["tmux", "has-session", "-t", "=claude"] in checks
    create = checks[-1]
    assert create[:5] == ["tmux", "new-session", "-d", "-s", "claude"]
    assert create[-1] == "claude -c"


async def test_tmux_action_does_not_wait_for_its_output(
    executor: ActionExecutor, runner: RecordingRunner
) -> None:
    """Вывод tmux не читаем — иначе кнопка висит, пока жив сервер tmux.

    `tmux new-session -d` возвращается сразу, но заодно поднимает сервер
    tmux, а тот наследует наши трубы и держит их открытыми, пока существует
    хоть одна сессия. Из-за этого первое нажатие «Claude Code» висело весь
    таймаут и отчитывалось ошибкой, хотя сессия уже была создана.
    """
    runner.responses["tmux"] = CommandResult(["tmux"], exit_code=1, stdout="", stderr="")
    await executor.run("claude")
    assert runner.calls[-1]["capture"] is False


async def test_desktop_action_still_captures_nothing_but_detaches(
    executor: ActionExecutor, runner: RecordingRunner
) -> None:
    """Обычные действия вывод по-прежнему читают: он показывается в ответе."""
    await executor.run("mc-start")
    assert runner.calls[-1]["capture"] is True


async def test_tmux_action_reuses_existing_session(
    executor: ActionExecutor, runner: RecordingRunner
) -> None:
    """Повторное нажатие не должно плодить сессии и терять запущенное."""
    runner.responses["tmux"] = CommandResult(["tmux"], exit_code=0, stdout="", stderr="")
    result = await executor.run("claude")
    assert result.success
    assert "уже запущена" in (result.message or "")
    assert len(runner.calls) == 1  # только проверка, без создания


async def test_desktop_action_receives_session_environment(
    runner: RecordingRunner, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("WAYLAND_DISPLAY", "wayland-1")
    monkeypatch.setenv("XDG_RUNTIME_DIR", "/run/user/1000")

    registry = ActionRegistry([DesktopAction(id="gui", name="GUI", argv=["/usr/bin/true"])])
    executor = ActionExecutor(registry, runner, get_adapter("linux"))
    await executor.run("gui")

    env = runner.calls[-1]["env"]
    assert isinstance(env, dict)
    assert env["WAYLAND_DISPLAY"] == "wayland-1"
    # GUI-приложение запускается отсоединённым, иначе действие висело бы
    # до закрытия программы.
    assert runner.calls[-1]["detach"] is True


async def test_unavailable_action_fails_before_execution(
    executor: ActionExecutor, runner: RecordingRunner
) -> None:
    result = await executor.run("missing-script")
    assert not result.success
    assert "недоступно" in (result.message or "")
    assert runner.calls == []


async def test_missing_workdir_is_reported(runner: RecordingRunner) -> None:
    registry = ActionRegistry(
        [ExecAction(id="x", name="X", argv=["/usr/bin/true"], workdir="/nonexistent/dir")]
    )
    executor = ActionExecutor(registry, runner, get_adapter("linux"))
    result = await executor.run("x")
    assert not result.success
    assert "рабочий каталог" in (result.message or "")


async def test_descriptors_are_sorted_and_marked(executor: ActionExecutor) -> None:
    descriptors = executor.registry.descriptors()
    ids = [d.id for d in descriptors]
    assert set(ids) == {"beep", "claude", "mc-start", "obs", "missing-script"}
    by_id = {d.id: d for d in descriptors}
    assert by_id["missing-script"].available is False
    assert by_id["beep"].available is True
    # Описание действия не раскрывает саму команду.
    assert not hasattr(by_id["claude"], "argv")


async def test_timeout_is_reported_not_hidden(runner: RecordingRunner) -> None:
    registry = ActionRegistry([ExecAction(id="slow", name="Долгое", argv=["/usr/bin/true"])])
    runner.responses["/usr/bin/true"] = CommandResult(
        ["/usr/bin/true"], exit_code=None, stdout="", stderr="", timed_out=True
    )
    executor = ActionExecutor(registry, runner, get_adapter("linux"))
    result = await executor.run("slow")
    assert not result.success
    assert "таймаут" in (result.message or "")


async def test_duplicate_ids_rejected_by_registry() -> None:
    with pytest.raises(ValueError, match="дублирующийся"):
        ActionRegistry(
            [
                ExecAction(id="dup", name="A", argv=["true"]),
                ExecAction(id="dup", name="B", argv=["true"]),
            ]
        )


# --- мультидействие ---------------------------------------------------------


def _macro_executor(
    runner: RecordingRunner, **macro: object
) -> tuple[ActionExecutor, ActionRegistry]:
    actions = [
        ExecAction(id="light", name="Свет", argv=["/usr/bin/true"]),
        ExecAction(id="obs", name="OBS", argv=["/usr/bin/true"]),
        ExecAction(id="gone", name="Нет такой программы", argv=["/nonexistent/remo32-нет"]),
        MacroAction(id="stream", name="Начать стрим", **macro),  # type: ignore[arg-type]
    ]
    registry = ActionRegistry(actions)  # type: ignore[arg-type]
    return ActionExecutor(registry, runner, get_adapter("linux")), registry


async def test_macro_runs_steps_in_order(runner: RecordingRunner) -> None:
    executor, _ = _macro_executor(runner, steps=["light", "obs"])
    result = await executor.run("stream")

    assert result.success
    assert result.message == "выполнено: Свет, OBS"
    assert [c["argv"] for c in runner.calls] == [["/usr/bin/true"], ["/usr/bin/true"]]  # type: ignore[misc]


async def test_macro_stops_on_first_failure(runner: RecordingRunner) -> None:
    executor, _ = _macro_executor(runner, steps=["light", "gone", "obs"])
    result = await executor.run("stream")

    assert not result.success
    # Видно и что успело сработать, и где встало: иначе кнопка молчит.
    assert "Свет" in result.message and "Нет такой программы" in result.message
    assert len(runner.calls) == 1


async def test_macro_can_keep_going_after_failure(runner: RecordingRunner) -> None:
    executor, _ = _macro_executor(runner, steps=["gone", "obs"], stop_on_error=False)
    result = await executor.run("stream")

    assert not result.success
    assert len(runner.calls) == 1  # недоступный шаг до запуска не доходит


async def test_macro_does_not_call_itself(runner: RecordingRunner) -> None:
    executor, _ = _macro_executor(runner, steps=["stream"])
    result = await executor.run("stream")

    assert not result.success
    assert "сама себя" in result.message


async def test_macro_is_unavailable_when_a_step_is(runner: RecordingRunner) -> None:
    _, registry = _macro_executor(runner, steps=["light", "gone"])
    described = registry.describe("stream")

    assert not described.available
    assert "gone" in (described.description or "")
    assert described.steps == ["light", "gone"]
