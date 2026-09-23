"""Wake-on-LAN.

Magic packet — это 6 байт 0xFF, за которыми 16 раз повторён MAC-адрес.
Отправляется широковещательно по UDP.

Важное ограничение, которое нельзя обойти программно: широковещательный
пакет не проходит через Tailscale и вообще через маршрутизаторы. Разбудить
машину может только устройство, физически находящееся в той же локальной
сети. Поэтому у контроллера два пути пробуждения — собственный пакет
(когда контроллер дома) и команда ESP32 (когда контроллер снаружи).
"""

from __future__ import annotations

import asyncio
import socket

from remo32_core.errors import WakeFailedError
from remo32_core.log import get_logger

log = get_logger("controller.wol")


def normalize_mac(mac: str) -> str:
    """Приводит MAC к виду ``aabbccddeeff``."""
    cleaned = mac.replace(":", "").replace("-", "").replace(".", "").strip().lower()
    if len(cleaned) != 12 or not all(c in "0123456789abcdef" for c in cleaned):
        raise ValueError(f"некорректный MAC-адрес: {mac}")
    return cleaned


def build_magic_packet(mac: str) -> bytes:
    """Собирает magic packet для указанного MAC."""
    payload = bytes.fromhex(normalize_mac(mac))
    return b"\xff" * 6 + payload * 16


def _send_sync(packet: bytes, broadcast: str, port: int, repeat: int) -> None:
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)
        sock.settimeout(2.0)
        for _ in range(repeat):
            sock.sendto(packet, (broadcast, port))


async def send_magic_packet(
    mac: str,
    *,
    broadcast: str = "255.255.255.255",
    port: int = 9,
    repeat: int = 3,
) -> None:
    """Отправляет magic packet. Бросает :class:`WakeFailedError` при сбое.

    Повторы нужны потому, что UDP не гарантирует доставку, а сетевая карта
    в спящем режиме может пропустить первый пакет.
    """
    try:
        packet = build_magic_packet(mac)
    except ValueError as exc:
        raise WakeFailedError(str(exc), mac=mac) from exc

    log.info("отправка magic packet", mac=mac, broadcast=broadcast, port=port, repeat=repeat)
    try:
        await asyncio.to_thread(_send_sync, packet, broadcast, port, repeat)
    except OSError as exc:
        raise WakeFailedError(
            f"не удалось отправить magic packet: {exc}",
            mac=mac,
            broadcast=broadcast,
        ) from exc
