"""Высокоуровневая работа с аппаратным контроллером.

Слой между API и транспортом. Он:

* держит последний известный статус и понимает, когда тот протух;
* никогда не даёт недоступному устройству уронить запрос — вместо
  исключения наружу уходит состояние ``OFFLINE``;
* реализует абстракцию переключения KVM, честно сообщая, что физического
  переключателя пока нет.
"""

from __future__ import annotations

import asyncio
import contextlib
import time

from remo32_controller.config import Esp32Settings
from remo32_controller.esp32.transport import Esp32Transport
from remo32_core.errors import (
    CapabilityUnavailableError,
    DeviceUnreachableError,
    Remo32Error,
)
from remo32_core.log import get_logger
from remo32_core.models import DeviceState, Esp32Status, utcnow
from remo32_core.protocol import (
    Esp32Command,
    Esp32CommandType,
    Esp32Reply,
    GpioWritePayload,
    GuardSnoozePayload,
    KvmSwitchPayload,
    WakeOnLanPayload,
)

log = get_logger("controller.esp32")


class Esp32Controller:
    def __init__(self, transport: Esp32Transport, settings: Esp32Settings) -> None:
        self._transport = transport
        self._settings = settings
        self._status: Esp32Status | None = None
        self._last_ok: float | None = None
        self._last_error: str | None = None
        self._poll_task: asyncio.Task[None] | None = None

    @property
    def transport_name(self) -> str:
        return self._transport.name

    @property
    def simulated(self) -> bool:
        return self._transport.simulated

    async def start(self) -> None:
        await self._transport.start()
        self._poll_task = asyncio.create_task(self._poll_loop(), name="esp32-poll")

    async def stop(self) -> None:
        if self._poll_task is not None:
            self._poll_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._poll_task
            self._poll_task = None
        await self._transport.stop()

    async def _poll_loop(self) -> None:
        """Периодический опрос. Сбои не прекращают цикл."""
        while True:
            try:
                await self.refresh()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                log.debug("опрос ESP32 не удался", error=str(exc))
            await asyncio.sleep(self._settings.poll_interval_seconds)

    async def refresh(self) -> Esp32Status:
        """Запрашивает статус устройства и запоминает результат."""
        try:
            reply = await self._send(Esp32Command(type=Esp32CommandType.STATUS))
        except Remo32Error as exc:
            self._last_error = exc.message
            return self.status()

        if reply.status is not None:
            self._status = reply.status
            self._last_ok = time.monotonic()
            self._last_error = None
        return self.status()

    def status(self) -> Esp32Status:
        """Текущее представление об устройстве. Никогда не бросает.

        Если статус устарел — состояние становится ``OFFLINE``, но данные
        сохраняются: пользователю полезно видеть, что было в последний раз.
        """
        if not self._settings.enabled:
            return Esp32Status(
                state=DeviceState.UNKNOWN, last_error="ESP32 выключен в конфигурации"
            )

        if self._status is None:
            return Esp32Status(
                state=self._transport.state,
                device_id=self._settings.device_id,
                simulated=self._transport.simulated,
                last_error=self._last_error,
            )

        status = self._status.model_copy(deep=True)
        # Симулятором считаем и мок-транспорт, и устройство, которое само
        # объявило себя симулятором. Занизить эту метку нельзя: интерфейс
        # обязан показывать, что железо не задействовано.
        status.simulated = self._transport.simulated or status.simulated
        status.last_error = self._last_error

        # Транспорт узнаёт об обрыве раньше, чем протухнет кэш статуса,
        # поэтому его мнение об отсутствии связи важнее возраста данных.
        transport_state = self._transport.state
        age = time.monotonic() - self._last_ok if self._last_ok is not None else None
        if transport_state in (DeviceState.OFFLINE, DeviceState.ERROR):
            status.state = transport_state
        elif age is None or age > self._settings.offline_after_seconds:
            status.state = DeviceState.OFFLINE
        else:
            status.state = DeviceState.ONLINE
        return status

    async def _send(self, command: Esp32Command) -> Esp32Reply:
        if not self._settings.enabled:
            raise CapabilityUnavailableError("ESP32 выключен в конфигурации")
        return await self._transport.send(command, timeout=self._settings.timeout_seconds)

    # --- прикладные операции ---------------------------------------------

    async def wake_on_lan(
        self, mac: str, *, broadcast: str = "255.255.255.255", port: int = 9, repeat: int = 3
    ) -> Esp32Reply:
        """Просит устройство отправить magic packet.

        Нужно, когда контроллер не в одной сети с целевым ПК: ESP32 стоит
        дома и широковещательный пакет отправить может, а контроллер снаружи — нет.
        """
        reply = await self._send(
            Esp32Command(
                type=Esp32CommandType.WAKE_ON_LAN,
                payload=WakeOnLanPayload(
                    mac_address=mac, broadcast_address=broadcast, port=port, repeat=repeat
                ),
            )
        )
        if not reply.ok:
            raise DeviceUnreachableError(reply.error or "ESP32 не смог отправить magic packet")
        return reply

    async def gpio_write(self, pin: int, level: bool, *, pulse_ms: int | None = None) -> Esp32Reply:
        reply = await self._send(
            Esp32Command(
                type=Esp32CommandType.GPIO_WRITE,
                payload=GpioWritePayload(pin=pin, level=level, pulse_ms=pulse_ms),
            )
        )
        if not reply.ok:
            raise DeviceUnreachableError(reply.error or "не удалось записать в GPIO")
        return reply

    async def switch_kvm(self, port: int) -> Esp32Reply:
        """Переключение входа KVM.

        Абстракция готова, но программа не может переключить монитор,
        клавиатуру и мышь без физического переключателя. Пока такой не
        подключён к ESP32, вызов честно сообщает об этом.
        """
        status = self.status()
        if "kvm" not in status.capabilities:
            raise CapabilityUnavailableError(
                "физический KVM не подключён к ESP32: программно переключить "
                "монитор и клавиатуру невозможно",
                port=port,
                device_capabilities=status.capabilities,
            )
        reply = await self._send(
            Esp32Command(type=Esp32CommandType.KVM_SWITCH, payload=KvmSwitchPayload(port=port))
        )
        if not reply.ok:
            raise DeviceUnreachableError(reply.error or "KVM не переключился")
        return reply

    async def guard_snooze(self, minutes: int) -> Esp32Reply | None:
        """Предупредить плату о плановом выключении ПК.

        Плата умеет сама поднимать основной ПК, когда тот пропал: контроллер
        живёт на этом же ПК и себя разбудить не может. Но для платы плановое
        выключение неотличимо от аварии, поэтому перед ним её просят
        помолчать. Без этого система включала бы ПК, который пользователь
        только что выключил.

        Возвращает ``None``, если прошивка сторожа не умеет: это не ошибка,
        а старая или чужая прошивка.
        """
        capabilities = self.status().capabilities
        # Пропускаем, только если ТОЧНО знаем, что прошивка не умеет сторожить.
        # Пустой список — это «плата сейчас молчит», а не «не умеет»: в этом
        # случае команду всё равно шлём. Не предупредить плату опаснее, чем
        # послать ей лишнюю команду — иначе она включит ПК обратно.
        if capabilities and "guard" not in capabilities:
            log.debug("прошивка не поддерживает сторожа, предупреждать некого")
            return None
        return await self._send(
            Esp32Command(
                type=Esp32CommandType.GUARD_SNOOZE,
                payload=GuardSnoozePayload(minutes=minutes),
            )
        )

    async def reboot_device(self) -> Esp32Reply:
        return await self._send(Esp32Command(type=Esp32CommandType.REBOOT))


def build_transport(settings: Esp32Settings, *, token: str | None = None) -> Esp32Transport:
    """Создаёт транспорт по конфигурации.

    Единственное место в системе, где принимается решение «симулятор или
    железо». Всё остальное работает через общий интерфейс.
    """
    from remo32_controller.esp32.http_transport import HttpEsp32Transport
    from remo32_controller.esp32.mock import MockEsp32Transport
    from remo32_controller.esp32.mqtt_transport import MqttEsp32Transport

    match settings.transport:
        case "mock":
            log.warning(
                "ESP32 работает В РЕЖИМЕ СИМУЛЯЦИИ: железо не задействовано",
                device_id=settings.device_id,
            )
            return MockEsp32Transport(settings.device_id)
        case "http":
            if settings.base_url is None:  # pragma: no cover — проверено валидатором
                raise ValueError('для transport = "http" требуется base_url')
            return HttpEsp32Transport(settings.base_url, token, timeout=settings.timeout_seconds)
        case "mqtt":
            import os

            if settings.mqtt_host is None:  # pragma: no cover — проверено валидатором
                raise ValueError('для transport = "mqtt" требуется mqtt_host')
            return MqttEsp32Transport(
                host=settings.mqtt_host,
                port=settings.mqtt_port,
                device_id=settings.device_id,
                username=settings.mqtt_username,
                password=os.environ.get(settings.mqtt_password_env),
                use_tls=settings.mqtt_tls,
                topic_prefix=settings.mqtt_topic_prefix,
                keepalive=settings.mqtt_keepalive,
            )
        case _:  # pragma: no cover
            raise ValueError(f"неизвестный транспорт: {settings.transport}")


__all__ = ["Esp32Controller", "build_transport", "utcnow"]
