"""Wake-on-LAN: формат пакета и обработка ошибок."""

from __future__ import annotations

import pytest

from remo32_controller.wol import build_magic_packet, normalize_mac, send_magic_packet
from remo32_core.errors import WakeFailedError


def test_packet_has_canonical_format() -> None:
    packet = build_magic_packet("5c:f9:dd:11:22:33")
    assert len(packet) == 102
    assert packet[:6] == b"\xff" * 6
    assert packet[6:].hex().count("5cf9dd112233") == 16


@pytest.mark.parametrize(
    "mac",
    ["5c:f9:dd:11:22:33", "5C-F9-DD-11-22-33", "5cf9dd112233", "5CF9.DD11.2233"],
)
def test_mac_formats_are_accepted(mac: str) -> None:
    assert normalize_mac(mac) == "5cf9dd112233"


@pytest.mark.parametrize("mac", ["", "не-мак", "5c:f9:dd:11:22", "5c:f9:dd:11:22:33:99", "zz" * 6])
def test_bad_mac_rejected(mac: str) -> None:
    with pytest.raises(ValueError):
        build_magic_packet(mac)


async def test_send_wraps_bad_mac_into_domain_error() -> None:
    with pytest.raises(WakeFailedError, match="некорректный MAC"):
        await send_magic_packet("мусор")


async def test_send_reports_network_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Сбой сети должен стать понятной ошибкой, а не трассировкой."""

    def boom(*args: object, **kwargs: object) -> None:
        raise OSError("сеть недоступна")

    monkeypatch.setattr("remo32_controller.wol._send_sync", boom)
    with pytest.raises(WakeFailedError, match="сеть недоступна"):
        await send_magic_packet("5c:f9:dd:11:22:33")
