"""Транспорт к устройству через MQTT-брокер.

Единственный вариант, который работает, когда контроллер и плата в разных
местах: соединение с брокером устанавливает сама плата — исходящее.
Дома не остаётся ни одного открытого порта.

Адрес брокера — параметр конфигурации. Начать можно с бесплатного
облачного, потом поднять свой ``mosquitto``: код при этом не меняется.
"""

from __future__ import annotations

import asyncio
import contextlib
import ssl
from typing import Any

from remo32_core.errors import DeviceTimeoutError, DeviceUnreachableError
from remo32_core.log import get_logger
from remo32_core.models import DeviceState, Esp32Status
from remo32_core.protocol import (
    AVAILABILITY_ONLINE,
    Esp32Command,
    Esp32Reply,
    MqttTopics,
)

log = get_logger("controller.esp32.mqtt")

RECONNECT_MIN_DELAY = 1.0
RECONNECT_MAX_DELAY = 60.0


class MqttEsp32Transport:
    """Клиент брокера с автоматическим переподключением.

    Задачи-обработчики живут внутри транспорта; наружу отдаётся обычный
    ``send`` — вызывающему коду разницы с HTTP нет.
    """

    name = "mqtt"

    def __init__(
        self,
        *,
        host: str,
        port: int = 8883,
        device_id: str = "esp32-main",
        username: str | None = None,
        password: str | None = None,
        use_tls: bool = True,
        topic_prefix: str = "remo32",
        keepalive: int = 30,
    ) -> None:
        self._host = host
        self._port = port
        self._username = username
        self._password = password
        self._use_tls = use_tls
        self._keepalive = keepalive
        self._topics = MqttTopics(topic_prefix, device_id)

        self._state = DeviceState.UNKNOWN
        self._task: asyncio.Task[None] | None = None
        self._client: Any = None
        self._pending: dict[str, asyncio.Future[Esp32Reply]] = {}
        self._last_status: Esp32Status | None = None
        self._stopping = asyncio.Event()

    @property
    def simulated(self) -> bool:
        return False

    @property
    def state(self) -> DeviceState:
        return self._state

    @property
    def last_status(self) -> Esp32Status | None:
        """Последний статус, пришедший в retained-топик."""
        return self._last_status

    async def start(self) -> None:
        self._stopping.clear()
        self._state = DeviceState.CONNECTING
        self._task = asyncio.create_task(self._run(), name="esp32-mqtt")

    async def stop(self) -> None:
        self._stopping.set()
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        self._state = DeviceState.UNKNOWN

    async def _run(self) -> None:
        """Держит соединение с брокером, переподключаясь с ростом паузы."""
        import aiomqtt

        delay = RECONNECT_MIN_DELAY
        while not self._stopping.is_set():
            try:
                tls_context = ssl.create_default_context() if self._use_tls else None
                async with aiomqtt.Client(
                    hostname=self._host,
                    port=self._port,
                    username=self._username,
                    password=self._password,
                    tls_context=tls_context,
                    keepalive=self._keepalive,
                ) as client:
                    self._client = client
                    self._state = DeviceState.CONNECTING
                    await client.subscribe(self._topics.reply)
                    await client.subscribe(self._topics.status)
                    await client.subscribe(self._topics.availability)
                    log.info(
                        "подключено к MQTT-брокеру",
                        host=self._host,
                        port=self._port,
                        prefix=self._topics.prefix,
                    )
                    delay = RECONNECT_MIN_DELAY
                    await self._consume(client)
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                self._state = DeviceState.OFFLINE
                self._client = None
                self._fail_pending(f"соединение с брокером потеряно: {exc}")
                if self._stopping.is_set():
                    return
                log.warning(
                    "нет связи с MQTT-брокером, повтор", error=str(exc), retry_in=round(delay, 1)
                )
                await asyncio.sleep(delay)
                delay = min(delay * 2, RECONNECT_MAX_DELAY)

    async def _consume(self, client: Any) -> None:
        async for message in client.messages:
            topic = str(message.topic)
            payload = message.payload
            text = (
                payload.decode("utf-8", errors="replace")
                if isinstance(payload, bytes)
                else str(payload)
            )

            if topic == self._topics.availability:
                self._state = (
                    DeviceState.ONLINE
                    if text.strip() == AVAILABILITY_ONLINE
                    else DeviceState.OFFLINE
                )
                log.info("изменилась доступность ESP32", state=self._state)
                continue

            if topic == self._topics.status:
                try:
                    self._last_status = Esp32Status.model_validate_json(text)
                    self._state = DeviceState.ONLINE
                except ValueError as exc:
                    log.warning("некорректный статус от ESP32", error=str(exc))
                continue

            if topic == self._topics.reply:
                try:
                    reply = Esp32Reply.model_validate_json(text)
                except ValueError as exc:
                    log.warning("некорректный ответ от ESP32", error=str(exc))
                    continue
                future = self._pending.pop(reply.command_id, None)
                if future is not None and not future.done():
                    future.set_result(reply)
                self._state = DeviceState.ONLINE

    def _fail_pending(self, reason: str) -> None:
        for future in self._pending.values():
            if not future.done():
                future.set_exception(DeviceUnreachableError(reason))
        self._pending.clear()

    async def send(self, command: Esp32Command, *, timeout: float) -> Esp32Reply:
        if self._client is None:
            raise DeviceUnreachableError("нет соединения с MQTT-брокером")

        loop = asyncio.get_running_loop()
        future: asyncio.Future[Esp32Reply] = loop.create_future()
        self._pending[command.id] = future
        try:
            await self._client.publish(
                self._topics.command, command.model_dump_json().encode(), qos=1
            )
            return await asyncio.wait_for(future, timeout=timeout)
        except TimeoutError as exc:
            raise DeviceTimeoutError(
                f"ESP32 не ответил за {timeout} с", command_id=command.id
            ) from exc
        finally:
            self._pending.pop(command.id, None)
