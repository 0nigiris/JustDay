"""Транспорт к реальному устройству по HTTP в домашней сети.

Простейший путь, пока телефон и плата в одной сети. Наружу интернета
устройство при этом не смотрит — что и хорошо.
"""

from __future__ import annotations

import httpx

from remo32_core.errors import DeviceTimeoutError, DeviceUnreachableError
from remo32_core.log import get_logger
from remo32_core.models import DeviceState
from remo32_core.protocol import HEADER_AGENT_TOKEN, Esp32Command, Esp32Reply

log = get_logger("controller.esp32.http")


class HttpEsp32Transport:
    name = "http"

    def __init__(self, base_url: str, token: str | None, *, timeout: float = 5.0) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._timeout = timeout
        self._state = DeviceState.UNKNOWN
        self._client: httpx.AsyncClient | None = None

    @property
    def simulated(self) -> bool:
        return False

    @property
    def state(self) -> DeviceState:
        return self._state

    async def start(self) -> None:
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(self._timeout, connect=min(self._timeout, 2.0)),
            limits=httpx.Limits(max_connections=2, max_keepalive_connections=1),
        )
        self._state = DeviceState.CONNECTING
        log.info("HTTP-транспорт ESP32 готов", base_url=self._base_url)

    async def stop(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self._state = DeviceState.UNKNOWN

    async def send(self, command: Esp32Command, *, timeout: float) -> Esp32Reply:
        if self._client is None:
            raise DeviceUnreachableError("транспорт ESP32 не запущен")

        headers = {HEADER_AGENT_TOKEN: self._token} if self._token else {}
        try:
            response = await self._client.post(
                f"{self._base_url}/command",
                json=command.model_dump(mode="json"),
                headers=headers,
                timeout=timeout,
            )
        except httpx.TimeoutException as exc:
            self._state = DeviceState.OFFLINE
            raise DeviceTimeoutError(f"ESP32 не ответил за {timeout} с") from exc
        except httpx.HTTPError as exc:
            self._state = DeviceState.OFFLINE
            raise DeviceUnreachableError(f"ESP32 недоступен: {exc}") from exc

        if response.status_code == 401:
            self._state = DeviceState.ERROR
            raise DeviceUnreachableError("ESP32 отверг токен")
        if response.status_code >= 400:
            self._state = DeviceState.ERROR
            raise DeviceUnreachableError(f"ESP32 вернул HTTP {response.status_code}")

        try:
            reply = Esp32Reply.model_validate(response.json())
        except ValueError as exc:
            self._state = DeviceState.ERROR
            raise DeviceUnreachableError(f"ESP32 вернул некорректный ответ: {exc}") from exc

        self._state = DeviceState.ONLINE
        return reply
