"""Безопасность операций питания.

Эти тесты — причина, по которой исполнитель команд вынесен за интерфейс.
Ни один из них не должен привести к реальному выключению машины.
"""

from __future__ import annotations

import pytest

from remo32_agent.execution import RecordingRunner
from remo32_agent.platforms import get_adapter
from remo32_agent.power import PowerPolicy, PowerService


@pytest.fixture
def service(runner: RecordingRunner) -> PowerService:
    return PowerService(get_adapter("linux"), runner, PowerPolicy(delay_seconds=5))


async def test_shutdown_does_not_execute_anything_real(
    service: PowerService, runner: RecordingRunner
) -> None:
    result = await service.shutdown()
    assert result.success
    # Команда только записана. Настоящий subprocess не вызывался.
    assert runner.last_argv == ["shutdown", "-P", "+1"]
    assert len(runner.calls) == 1


async def test_restart_builds_expected_command(
    service: PowerService, runner: RecordingRunner
) -> None:
    await service.reboot()
    assert runner.last_argv == ["shutdown", "-r", "+1"]


async def test_zero_delay_uses_systemctl(runner: RecordingRunner) -> None:
    service = PowerService(get_adapter("linux"), runner, PowerPolicy(delay_seconds=0))
    await service.shutdown()
    assert runner.last_argv == ["systemctl", "poweroff"]


async def test_shutdown_can_be_forbidden_by_config(runner: RecordingRunner) -> None:
    service = PowerService(get_adapter("linux"), runner, PowerPolicy(shutdown_enabled=False))
    result = await service.shutdown()
    assert not result.success
    assert "запрещено" in (result.message or "")
    assert runner.calls == []  # запрет срабатывает до исполнителя


async def test_dry_run_skips_runner_entirely(runner: RecordingRunner) -> None:
    service = PowerService(get_adapter("linux"), runner, PowerPolicy(dry_run=True))
    result = await service.shutdown()
    assert result.success
    assert "dry-run" in (result.message or "")
    assert runner.calls == []


async def test_windows_adapter_builds_windows_command(runner: RecordingRunner) -> None:
    """Команды чужой платформы проверяются, не покидая Linux."""
    service = PowerService(get_adapter("windows"), runner, PowerPolicy(delay_seconds=30))
    await service.shutdown()
    assert runner.last_argv == ["shutdown", "/s", "/t", "30"]


async def test_macos_adapter_builds_macos_command(runner: RecordingRunner) -> None:
    service = PowerService(get_adapter("darwin"), runner, PowerPolicy(delay_seconds=0))
    await service.reboot()
    assert runner.last_argv == ["shutdown", "-r", "now"]


async def test_failed_command_is_reported_honestly(runner: RecordingRunner) -> None:
    from remo32_agent.execution import CommandResult

    runner.responses["shutdown"] = CommandResult(
        ["shutdown"], exit_code=1, stdout="", stderr="Access denied"
    )
    service = PowerService(get_adapter("linux"), runner, PowerPolicy())
    result = await service.shutdown()
    assert not result.success
    assert result.message == "Access denied"
