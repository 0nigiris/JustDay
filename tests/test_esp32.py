"""ESP32: транспорт, симулятор, состояния и честность про железо."""

from __future__ import annotations

import pytest

from remo32_controller.config import Esp32Settings
from remo32_controller.esp32.controller import Esp32Controller, build_transport
from remo32_controller.esp32.mock import MockBehaviour, MockEsp32Transport
from remo32_core.errors import CapabilityUnavailableError, DeviceUnreachableError
from remo32_core.models import DeviceState
from remo32_core.protocol import Esp32Command, Esp32CommandType


@pytest.fixture
def transport() -> MockEsp32Transport:
    return MockEsp32Transport("esp32-test", seed=42)


@pytest.fixture
async def controller(transport: MockEsp32Transport):  # type: ignore[no-untyped-def]
    settings = Esp32Settings(transport="mock", poll_interval_seconds=300.0)
    ctl = Esp32Controller(transport, settings)
    await ctl.start()
    yield ctl
    await ctl.stop()


async def test_status_reports_simulation_honestly(controller: Esp32Controller) -> None:
    """Симулятор обязан быть помечен: иначе легко решить, что железо проверено."""
    status = await controller.refresh()
    assert status.simulated is True
    assert status.state == DeviceState.ONLINE
    assert status.chip == "esp32s3"


async def test_firmware_reports_no_psram(controller: Esp32Controller) -> None:
    """Прошивка работает без PSRAM — это штатный режим, а не сбой."""
    status = await controller.refresh()
    assert status.psram_present is False


async def test_wake_on_lan_is_forwarded(
    controller: Esp32Controller, transport: MockEsp32Transport
) -> None:
    reply = await controller.wake_on_lan("5c:f9:dd:11:22:33", broadcast="192.168.1.255")
    assert reply.ok
    assert transport.wol_history == ["5c:f9:dd:11:22:33"]
    # Симулятор обязан признаться, что настоящий пакет не улетал.
    assert reply.result["simulated"] is True


async def test_offline_device_raises_domain_error(
    controller: Esp32Controller, transport: MockEsp32Transport
) -> None:
    transport.simulate_disconnect()
    with pytest.raises(DeviceUnreachableError):
        await controller.wake_on_lan("5c:f9:dd:11:22:33")


async def test_status_switches_to_offline_immediately(
    controller: Esp32Controller, transport: MockEsp32Transport
) -> None:
    """Обрыв виден сразу, не дожидаясь протухания кэша."""
    await controller.refresh()
    assert controller.status().state == DeviceState.ONLINE
    transport.simulate_disconnect()
    assert controller.status().state == DeviceState.OFFLINE


async def test_reconnect_is_counted(
    controller: Esp32Controller, transport: MockEsp32Transport
) -> None:
    transport.simulate_disconnect()
    transport.simulate_reconnect()
    status = await controller.refresh()
    assert status.state == DeviceState.ONLINE
    assert status.reconnect_count == 1


async def test_command_failure_is_not_silently_swallowed(
    controller: Esp32Controller, transport: MockEsp32Transport
) -> None:
    transport.behaviour = MockBehaviour(fail_command_types={Esp32CommandType.WAKE_ON_LAN})
    with pytest.raises(DeviceUnreachableError, match="симуляция отказа"):
        await controller.wake_on_lan("5c:f9:dd:11:22:33")


async def test_kvm_refuses_without_hardware(controller: Esp32Controller) -> None:
    """Программа не может переключить монитор без физического переключателя."""
    await controller.refresh()
    with pytest.raises(CapabilityUnavailableError, match="физический KVM"):
        await controller.switch_kvm(2)


async def test_gpio_write_only_on_outputs(
    controller: Esp32Controller, transport: MockEsp32Transport
) -> None:
    reply = await controller.gpio_write(18, True)
    assert reply.ok
    with pytest.raises(DeviceUnreachableError, match="не настроен как выход"):
        await controller.gpio_write(4, True)  # это вход


async def test_input_pin_reflects_simulated_power_state(
    controller: Esp32Controller, transport: MockEsp32Transport
) -> None:
    """Изменение входа имитирует включение ПК: загорелся светодиод питания."""
    transport.set_pin_level(4, True)
    status = await controller.refresh()
    pin = next(p for p in status.gpio if p.pin == 4)
    assert pin.level is True


def test_transport_factory_selects_implementation() -> None:
    mock = build_transport(Esp32Settings(transport="mock"))
    assert mock.name == "mock"
    assert mock.simulated is True

    http = build_transport(
        Esp32Settings(transport="http", base_url="http://192.168.1.50"), token="t"
    )
    assert http.name == "http"
    # Реальный транспорт не считает себя симуляцией.
    assert http.simulated is False

    mqtt = build_transport(Esp32Settings(transport="mqtt", mqtt_host="broker"))
    assert mqtt.name == "mqtt"
    assert mqtt.simulated is False


async def test_disabled_esp32_never_raises_in_status() -> None:
    settings = Esp32Settings(enabled=False)
    controller = Esp32Controller(MockEsp32Transport(), settings)
    status = controller.status()
    assert status.state == DeviceState.UNKNOWN
    assert "выключен" in (status.last_error or "")


async def test_standalone_simulator_matches_protocol() -> None:
    """Отдельный симулятор отвечает тем же протоколом, что и встроенный."""
    from remo32_espsim.device import SimulatedDevice

    device = SimulatedDevice("esp32-main", seed=1)
    reply = device.handle(Esp32Command(type=Esp32CommandType.STATUS))
    assert reply.ok
    assert reply.status is not None
    assert reply.status.simulated is True
    assert reply.status.psram_present is False
    assert "kvm" not in reply.status.capabilities


# --- сторож основного ПК -----------------------------------------------------


async def test_snooze_reaches_the_board() -> None:
    """Просьба «не буди» доходит до устройства и записывается."""
    from remo32_controller.config import Esp32Settings
    from remo32_controller.esp32.controller import Esp32Controller
    from remo32_controller.esp32.mock import MockEsp32Transport

    transport = MockEsp32Transport("esp32-test")
    controller = Esp32Controller(transport, Esp32Settings(transport="mock"))
    await controller.start()
    await controller.refresh()

    reply = await controller.guard_snooze(480)
    assert reply is not None
    assert reply.ok
    assert transport.snooze_requests == [480]


async def test_snooze_skipped_when_firmware_cannot_guard() -> None:
    """Старая прошивка без сторожа — не ошибка, а просто отсутствие функции."""
    from remo32_controller.config import Esp32Settings
    from remo32_controller.esp32.controller import Esp32Controller
    from remo32_controller.esp32.mock import MockEsp32Transport

    transport = MockEsp32Transport("esp32-old")
    controller = Esp32Controller(transport, Esp32Settings(transport="mock"))
    await controller.start()
    status = await controller.refresh()
    assert "guard" in status.capabilities

    # Имитируем прошивку без сторожа.
    assert controller._status is not None
    controller._status.capabilities.remove("guard")

    assert await controller.guard_snooze(60) is None
    assert transport.snooze_requests == []


async def test_snooze_sent_even_when_board_is_silent() -> None:
    """Молчащая плата — не повод пропустить предупреждение.

    Пустой список возможностей означает «статус ещё не получен», а не
    «сторожа нет». Промолчать здесь опаснее: плата включит ПК обратно.
    """
    from remo32_controller.config import Esp32Settings
    from remo32_controller.esp32.controller import Esp32Controller
    from remo32_controller.esp32.mock import MockEsp32Transport

    transport = MockEsp32Transport("esp32-silent")
    controller = Esp32Controller(transport, Esp32Settings(transport="mock"))
    await controller.start()
    assert controller.status().capabilities == []  # статус ещё не запрашивали

    reply = await controller.guard_snooze(480)
    assert reply is not None and reply.ok
    assert transport.snooze_requests == [480]
