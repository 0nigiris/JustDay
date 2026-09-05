"""Состояния ПК и устойчивость реестра к отказам."""

from __future__ import annotations

from typing import Any

import pytest

from remo32_controller.config import ControllerSettings
from remo32_controller.devices import DeviceRegistry
from remo32_core.errors import (
    DeviceTimeoutError,
    DeviceUnreachableError,
    PcNotFoundError,
    TerminalDisabledError,
    WakeFailedError,
)
from remo32_core.models import AgentHealth, DeviceState, SystemStats


class FakeAgentClient:
    """Подставной агент: можно заставить его отвечать или падать."""

    def __init__(self, *, online: bool = True, terminal: bool = False) -> None:
        self.online = online
        self.terminal = terminal
        self.calls: list[str] = []
        self.shutdown_called = False

    async def health(self, *, timeout: float | None = None) -> AgentHealth:
        self.calls.append("health")
        if not self.online:
            raise DeviceUnreachableError("агент недоступен")
        return AgentHealth(
            agent_version="test",
            hostname="fake",
            platform="linux",
            terminal_enabled=self.terminal,
            action_count=0,
        )

    async def stats(self) -> SystemStats:
        if not self.online:
            raise DeviceTimeoutError("нет ответа")
        return SystemStats(hostname="fake", platform="linux")

    async def actions(self) -> list[Any]:
        return []

    async def shutdown(self) -> Any:
        from remo32_core.models import ActionResult, utcnow

        self.shutdown_called = True
        return ActionResult(
            action_id="shutdown", success=True, started_at=utcnow(), finished_at=utcnow()
        )

    async def restart(self) -> Any:
        return await self.shutdown()

    async def run_action(self, action_id: str, *, timeout: float = 60.0) -> Any:
        from remo32_core.models import ActionResult, utcnow

        return ActionResult(
            action_id=action_id, success=True, started_at=utcnow(), finished_at=utcnow()
        )

    def terminal_ws_url(self, session: str | None, cols: int, rows: int) -> str:
        return f"ws://fake/api/terminal/ws?cols={cols}&rows={rows}"

    async def aclose(self) -> None:
        return None


@pytest.fixture
def clients() -> dict[str, FakeAgentClient]:
    return {"testpc": FakeAgentClient(), "nomac": FakeAgentClient(online=False)}


@pytest.fixture
def registry(
    controller_settings: ControllerSettings, clients: dict[str, FakeAgentClient]
) -> DeviceRegistry:
    return DeviceRegistry(controller_settings, None, clients=clients)  # type: ignore[arg-type]


async def test_initial_state_is_unknown_not_offline(registry: DeviceRegistry) -> None:
    """До первого опроса состояние «неизвестно»: врать «выключен» нельзя."""
    for summary in registry.summaries():
        assert summary.state == DeviceState.UNKNOWN


async def test_online_pc_gets_stats(registry: DeviceRegistry) -> None:
    await registry.poll_one("testpc")
    summary = registry.summary("testpc")
    assert summary.state == DeviceState.ONLINE
    assert summary.stats is not None
    assert summary.last_seen is not None
    assert summary.stale is False


async def test_offline_requires_several_failures(
    registry: DeviceRegistry, controller_settings: ControllerSettings
) -> None:
    """Одна потерянная датаграмма не должна давать «выключен»."""
    assert controller_settings.poller.offline_after_failures == 2
    await registry.poll_one("nomac")
    assert registry.summary("nomac").state in (DeviceState.UNKNOWN, DeviceState.OFFLINE)
    await registry.poll_one("nomac")
    assert registry.summary("nomac").state == DeviceState.OFFLINE


async def test_one_broken_pc_does_not_break_the_others(registry: DeviceRegistry) -> None:
    await registry.poll_all()
    await registry.poll_all()
    states = {s.id: s.state for s in registry.summaries()}
    assert states["testpc"] == DeviceState.ONLINE
    assert states["nomac"] == DeviceState.OFFLINE


async def test_last_error_is_preserved_for_diagnostics(registry: DeviceRegistry) -> None:
    await registry.poll_one("nomac")
    await registry.poll_one("nomac")
    assert "недоступен" in (registry.summary("nomac").last_error or "")


async def test_recovery_clears_error(
    registry: DeviceRegistry, clients: dict[str, FakeAgentClient]
) -> None:
    await registry.poll_one("nomac")
    await registry.poll_one("nomac")
    assert registry.summary("nomac").state == DeviceState.OFFLINE

    clients["nomac"].online = True
    await registry.poll_one("nomac")
    summary = registry.summary("nomac")
    assert summary.state == DeviceState.ONLINE
    assert summary.last_error is None


async def test_unknown_pc_raises(registry: DeviceRegistry) -> None:
    with pytest.raises(PcNotFoundError):
        registry.summary("нет-такого")


async def test_wake_without_mac_fails_clearly(registry: DeviceRegistry) -> None:
    with pytest.raises(WakeFailedError, match="MAC"):
        await registry.wake("nomac")


async def test_wake_fails_when_all_paths_disabled(registry: DeviceRegistry) -> None:
    """Без собственного пакета и без ESP32 будить нечем — и об этом надо сказать."""
    with pytest.raises(WakeFailedError, match="ни одним способом"):
        await registry.wake("testpc")


async def test_wake_succeeds_via_esp32_alone(
    controller_settings: ControllerSettings, clients: dict[str, FakeAgentClient]
) -> None:
    from remo32_controller.config import Esp32Settings
    from remo32_controller.esp32.controller import Esp32Controller
    from remo32_controller.esp32.mock import MockEsp32Transport

    transport = MockEsp32Transport("esp32-test")
    esp32 = Esp32Controller(transport, Esp32Settings(transport="mock"))
    await esp32.start()
    try:
        registry = DeviceRegistry(controller_settings, esp32, clients=clients)  # type: ignore[arg-type]
        result = await registry.wake("testpc")
        attempts: list[dict[str, object]] = result["attempts"]  # type: ignore[assignment]
        methods = {a["method"]: a["ok"] for a in attempts}
        assert methods["esp32"] is True
        assert transport.wol_history == ["5c:f9:dd:11:22:33"]
    finally:
        await esp32.stop()


async def test_terminal_blocked_by_controller_config(registry: DeviceRegistry) -> None:
    with pytest.raises(TerminalDisabledError, match="контроллера"):
        registry.terminal_target("testpc", None, 80, 24)


async def test_terminal_blocked_by_agent(
    controller_settings: ControllerSettings, clients: dict[str, FakeAgentClient]
) -> None:
    """Двойной выключатель: разрешения контроллера мало, нужен и агент."""
    controller_settings.pcs[0].terminal_enabled = True
    registry = DeviceRegistry(controller_settings, None, clients=clients)  # type: ignore[arg-type]
    await registry.poll_one("testpc")  # агент сообщает terminal_enabled=False
    with pytest.raises(TerminalDisabledError, match="агент"):
        registry.terminal_target("testpc", None, 80, 24)


async def test_terminal_allowed_when_both_agree(
    controller_settings: ControllerSettings, clients: dict[str, FakeAgentClient]
) -> None:
    controller_settings.pcs[0].terminal_enabled = True
    clients["testpc"].terminal = True
    registry = DeviceRegistry(controller_settings, None, clients=clients)  # type: ignore[arg-type]
    await registry.poll_one("testpc")
    url = registry.terminal_target("testpc", "main", 100, 30)
    assert "cols=100" in url and "rows=30" in url


async def test_state_change_notifies_subscribers(
    registry: DeviceRegistry, clients: dict[str, FakeAgentClient]
) -> None:
    """Интерфейс обновляется по событию, а не по опросу."""
    queue = registry.subscribe()
    await registry.poll_one("testpc")
    assert not queue.empty()
    assert await queue.get() == "state"


async def test_stale_flag_after_threshold(
    registry: DeviceRegistry, controller_settings: ControllerSettings
) -> None:
    await registry.poll_one("testpc")
    runtime = registry.get("testpc")
    # Сдвигаем момент сбора статистики в прошлое.
    runtime.stats_at = runtime.stats_at - controller_settings.poller.stale_after_seconds - 1  # type: ignore[operator]
    assert registry.summary("testpc").stale is True


# --- сторож основного ПК -----------------------------------------------------


async def _registry_with_board(
    controller_settings: ControllerSettings, clients: dict[str, Any], *, guarded: bool
) -> tuple[DeviceRegistry, Any, Any]:
    from remo32_controller.config import Esp32Settings
    from remo32_controller.esp32.controller import Esp32Controller
    from remo32_controller.esp32.mock import MockEsp32Transport

    for pc in controller_settings.pcs:
        if pc.id == "testpc":
            pc.guarded_by_esp32 = guarded
            pc.guard_snooze_minutes = 480

    transport = MockEsp32Transport("esp32-test")
    esp32 = Esp32Controller(transport, Esp32Settings(transport="mock"))
    await esp32.start()
    await esp32.refresh()
    registry = DeviceRegistry(controller_settings, esp32, clients=clients)
    return registry, transport, esp32


async def test_planned_shutdown_warns_the_board(
    controller_settings: ControllerSettings, clients: dict[str, Any]
) -> None:
    """Плановое выключение обязано предупредить сторожа.

    Иначе плата увидит пропажу ПК, посчитает её аварией и включит машину
    обратно — система дралась бы с собственным пользователем.
    """
    registry, transport, esp32 = await _registry_with_board(
        controller_settings, clients, guarded=True
    )
    try:
        result = await registry.shutdown("testpc")
        assert result.success
        assert transport.snooze_requests == [480]
    finally:
        await esp32.stop()


async def test_unguarded_pc_does_not_warn(
    controller_settings: ControllerSettings, clients: dict[str, Any]
) -> None:
    """За ПК без сторожа плату дёргать незачем."""
    registry, transport, esp32 = await _registry_with_board(
        controller_settings, clients, guarded=False
    )
    try:
        await registry.shutdown("testpc")
        assert transport.snooze_requests == []
    finally:
        await esp32.stop()


async def test_shutdown_survives_unreachable_board(
    controller_settings: ControllerSettings, clients: dict[str, Any]
) -> None:
    """Молчащая плата не должна мешать выключить компьютер."""
    from remo32_controller.esp32.mock import MockBehaviour

    registry, transport, esp32 = await _registry_with_board(
        controller_settings, clients, guarded=True
    )
    transport.behaviour = MockBehaviour(offline=True)
    try:
        result = await registry.shutdown("testpc")
        assert result.success
    finally:
        await esp32.stop()
