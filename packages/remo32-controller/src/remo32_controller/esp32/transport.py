"""Контракт транспорта к аппаратному контроллеру.

Ради этого интерфейса всё и затевалось: контроллер посылает
:class:`~remo32_core.protocol.Esp32Command` и получает
:class:`~remo32_core.protocol.Esp32Reply`, не зная, кто на другом конце —
симулятор в этом же процессе, реальная плата по HTTP в домашней сети или
она же через MQTT-брокер из другого города.

Заменить симулятор на железо = поменять одну строку в конфигурации.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from remo32_core.models import DeviceState
from remo32_core.protocol import Esp32Command, Esp32Reply


@runtime_checkable
class Esp32Transport(Protocol):
    """Транспорт до устройства."""

    name: str
    """Человекочитаемое имя транспорта: mock / http / mqtt."""

    @property
    def simulated(self) -> bool:
        """True, если на другом конце не настоящее железо.

        Интерфейс обязан показывать это пользователю: иначе легко решить,
        что GPIO проверен, хотя проверен был симулятор.
        """
        ...

    async def start(self) -> None:
        """Устанавливает соединение. Не должен бросать при недоступности."""
        ...

    async def stop(self) -> None: ...

    async def send(self, command: Esp32Command, *, timeout: float) -> Esp32Reply:
        """Отправляет команду и ждёт ответ.

        Бросает :class:`~remo32_core.errors.DeviceUnreachableError`,
        если устройство недоступно.
        """
        ...

    @property
    def state(self) -> DeviceState:
        """Состояние связи с точки зрения транспорта."""
        ...
