"""MQTT-сторона симулятора.

Повторяет то, что будет делать прошивка: подключается исходящим
соединением, публикует LWT ``offline``, ретейнит статус и отвечает на
команды.
"""

from __future__ import annotations

import asyncio
import contextlib
import ssl

from remo32_core.log import get_logger
from remo32_core.protocol import (
    AVAILABILITY_OFFLINE,
    AVAILABILITY_ONLINE,
    Esp32Command,
    MqttTopics,
)
from remo32_espsim.config import SimulatorSettings
from remo32_espsim.device import SimulatedDevice

log = get_logger("espsim.mqtt")

RECONNECT_MIN = 1.0
RECONNECT_MAX = 30.0


async def run_mqtt(device: SimulatedDevice, settings: SimulatorSettings) -> None:
    """Держит соединение с брокером до отмены задачи."""
    import aiomqtt

    if settings.mqtt_host is None:
        log.error("режим MQTT выбран, но адрес брокера не задан")
        return
    topics = MqttTopics(settings.mqtt_topic_prefix, device.device_id)
    delay = RECONNECT_MIN

    while True:
        try:
            async with aiomqtt.Client(
                hostname=settings.mqtt_host,
                port=settings.mqtt_port,
                username=settings.mqtt_username,
                password=settings.mqtt_password,
                tls_context=ssl.create_default_context() if settings.mqtt_tls else None,
                # LWT: если устройство пропадёт, брокер сам объявит его офлайном.
                will=aiomqtt.Will(
                    topics.availability, AVAILABILITY_OFFLINE.encode(), qos=1, retain=True
                ),
            ) as client:
                log.info(
                    "симулятор подключён к брокеру",
                    host=settings.mqtt_host,
                    port=settings.mqtt_port,
                    topic=topics.command,
                )
                delay = RECONNECT_MIN
                await client.publish(
                    topics.availability, AVAILABILITY_ONLINE.encode(), qos=1, retain=True
                )
                await client.subscribe(topics.command)

                status_task = asyncio.create_task(_publish_status(client, device, topics, settings))
                try:
                    await _consume(client, device, topics)
                finally:
                    status_task.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await status_task
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            log.warning("симулятор: связь с брокером потеряна", error=str(exc), retry_in=delay)
            await asyncio.sleep(delay)
            delay = min(delay * 2, RECONNECT_MAX)


async def _publish_status(
    client: object, device: SimulatedDevice, topics: MqttTopics, settings: SimulatorSettings
) -> None:
    while True:
        if not device.faults.offline and not device.faults.wifi_lost:
            await client.publish(  # type: ignore[attr-defined]
                topics.status, device.status().model_dump_json().encode(), qos=0, retain=True
            )
        await asyncio.sleep(settings.status_interval_seconds)


async def _consume(client: object, device: SimulatedDevice, topics: MqttTopics) -> None:
    async for message in client.messages:  # type: ignore[attr-defined]
        if device.faults.offline:
            continue  # выключенное устройство молчит
        payload = message.payload
        text = payload.decode() if isinstance(payload, bytes) else str(payload)
        try:
            command = Esp32Command.model_validate_json(text)
        except ValueError as exc:
            log.warning("симулятор: некорректная команда", error=str(exc))
            continue

        if device.faults.extra_latency_ms:
            await asyncio.sleep(device.faults.extra_latency_ms / 1000)

        reply = device.handle(command)
        await client.publish(  # type: ignore[attr-defined]
            topics.reply, reply.model_dump_json().encode(), qos=1
        )
