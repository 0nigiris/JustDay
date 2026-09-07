"""Реестр управляемых ПК и слежение за их состоянием.

Каждый ПК опрашивается независимо: недоступный ПК не задерживает и не
ломает остальные. Состояние переходит в ``OFFLINE`` не с первой неудачи,
а после нескольких подряд — иначе одна потерянная датаграмма рисовала бы
в интерфейсе мигание «онлайн/офлайн».
"""

from __future__ import annotations

import asyncio
import contextlib
import time
from dataclasses import dataclass, field
from typing import Any

from remo32_controller.agent_client import AgentClient
from remo32_controller.config import ControllerSettings, PcConfig, PollerSettings
from remo32_controller.esp32.controller import Esp32Controller
from remo32_controller.wol import send_magic_packet
from remo32_core.errors import (
    DeviceUnreachableError,
    PcNotFoundError,
    Remo32Error,
    TerminalDisabledError,
    WakeFailedError,
)
from remo32_core.log import get_logger
from remo32_core.models import (
    ActionDescriptor,
    ActionEditorState,
    ActionResult,
    DeviceState,
    PcSummary,
    PowerState,
    SystemStats,
    utcnow,
)

log = get_logger("controller.devices")


@dataclass
class PcRuntime:
    """Изменяемое состояние одного ПК."""

    config: PcConfig
    client: AgentClient
    state: DeviceState = DeviceState.UNKNOWN
    power_state: PowerState = PowerState.UNKNOWN
    last_seen_monotonic: float | None = None
    last_seen_wall: object = None
    last_error: str | None = None
    consecutive_failures: int = 0
    stats: SystemStats | None = None
    stats_at: float | None = None
    actions: list[ActionDescriptor] = field(default_factory=list)
    agent_terminal_enabled: bool = False

    def age_seconds(self) -> float | None:
        if self.stats_at is None:
            return None
        return time.monotonic() - self.stats_at


class DeviceRegistry:
    """Все ПК контроллера плюс фоновый опрос."""

    def __init__(
        self,
        settings: ControllerSettings,
        esp32: Esp32Controller | None = None,
        *,
        clients: dict[str, AgentClient] | None = None,
    ) -> None:
        self._settings = settings
        self._poller: PollerSettings = settings.poller
        self._esp32 = esp32
        self._pcs: dict[str, PcRuntime] = {}
        self._task: asyncio.Task[None] | None = None
        self._subscribers: set[asyncio.Queue[str]] = set()

        for pc in settings.pcs:
            client = (clients or {}).get(pc.id) or AgentClient(
                pc.agent_url, pc.resolve_token(), timeout=self._poller.timeout_seconds
            )
            self._pcs[pc.id] = PcRuntime(config=pc, client=client)

    # --- жизненный цикл ---------------------------------------------------

    async def start(self) -> None:
        if self._pcs:
            self._task = asyncio.create_task(self._poll_loop(), name="pc-poller")
        log.info("реестр ПК запущен", count=len(self._pcs))

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None
        for pc in self._pcs.values():
            await pc.client.aclose()

    # --- уведомления интерфейса ------------------------------------------

    def subscribe(self) -> asyncio.Queue[str]:
        """Очередь для потока событий: интерфейс обновляется без опроса."""
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=8)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[str]) -> None:
        self._subscribers.discard(queue)

    def _notify(self, event: str) -> None:
        for queue in list(self._subscribers):
            # Медленный клиент пропустит событие; следующее всё равно придёт.
            with contextlib.suppress(asyncio.QueueFull):
                queue.put_nowait(event)

    # --- доступ -----------------------------------------------------------

    def ids(self) -> list[str]:
        return list(self._pcs)

    def get(self, pc_id: str) -> PcRuntime:
        try:
            return self._pcs[pc_id]
        except KeyError:
            raise PcNotFoundError(f"ПК не найден: {pc_id}", pc_id=pc_id) from None

    def summaries(self) -> list[PcSummary]:
        return [self._summary(pc) for pc in self._pcs.values()]

    def summary(self, pc_id: str) -> PcSummary:
        return self._summary(self.get(pc_id))

    def _summary(self, pc: PcRuntime) -> PcSummary:
        age = pc.age_seconds()
        stale = age is not None and age > self._poller.stale_after_seconds
        return PcSummary(
            id=pc.config.id,
            name=pc.config.name,
            description=pc.config.description,
            state=pc.state,
            power_state=pc.power_state,
            last_seen=pc.last_seen_wall,
            last_error=pc.last_error,
            address=pc.config.agent_url,
            mac_address=pc.config.mac_address,
            wake_supported=pc.config.mac_address is not None,
            terminal_supported=pc.config.terminal_enabled and pc.agent_terminal_enabled,
            stats=pc.stats,
            stats_age_seconds=age,
            stale=stale,
            actions=pc.actions,
        )

    # --- опрос ------------------------------------------------------------

    async def _poll_loop(self) -> None:
        while True:
            try:
                await self.poll_all()
            except asyncio.CancelledError:
                raise
            except Exception:
                log.exception("сбой цикла опроса")
            await asyncio.sleep(self._poller.interval_seconds)

    async def poll_all(self) -> None:
        """Опрашивает все ПК параллельно."""
        results = await asyncio.gather(
            *(self.poll_one(pc_id) for pc_id in self._pcs), return_exceptions=True
        )
        for pc_id, result in zip(self._pcs, results, strict=True):
            if isinstance(result, BaseException) and not isinstance(result, Exception):
                raise result
            if isinstance(result, Exception):
                log.warning("опрос ПК завершился ошибкой", pc=pc_id, error=str(result))

    async def poll_one(self, pc_id: str) -> None:
        pc = self.get(pc_id)
        previous = pc.state
        try:
            health = await pc.client.health(timeout=self._poller.timeout_seconds)
        except DeviceUnreachableError as exc:
            self._mark_failure(pc, exc.message)
        except Exception as exc:
            self._mark_failure(pc, f"неожиданная ошибка: {exc}")
        else:
            pc.consecutive_failures = 0
            pc.state = DeviceState.ONLINE
            pc.power_state = PowerState.ON
            pc.last_seen_monotonic = time.monotonic()
            pc.last_seen_wall = utcnow()
            pc.last_error = None
            pc.agent_terminal_enabled = health.terminal_enabled
            await self._refresh_details(pc)

        if pc.state != previous:
            log.info("ПК сменил состояние", pc=pc.config.id, was=previous, now=pc.state)
            self._notify("state")

    def _mark_failure(self, pc: PcRuntime, message: str) -> None:
        pc.consecutive_failures += 1
        pc.last_error = message
        if pc.consecutive_failures >= self._poller.offline_after_failures:
            pc.state = DeviceState.OFFLINE
            pc.power_state = PowerState.UNKNOWN
            # Статистику не стираем: пусть в интерфейсе останется последнее
            # известное состояние, помеченное как устаревшее.
        elif pc.state == DeviceState.ONLINE:
            pc.state = DeviceState.CONNECTING

    async def _refresh_details(self, pc: PcRuntime) -> None:
        """Догружает статистику и список действий.

        Сбой здесь не переводит ПК в офлайн: health уже ответил, машина жива.
        """
        try:
            pc.stats = await pc.client.stats()
            pc.stats_at = time.monotonic()
        except Exception as exc:
            log.debug("не удалось получить статистику", pc=pc.config.id, error=str(exc))

        if not pc.actions:
            try:
                pc.actions = await pc.client.actions()
            except Exception as exc:
                log.debug("не удалось получить список действий", pc=pc.config.id, error=str(exc))

    # --- операции ---------------------------------------------------------

    async def wake(self, pc_id: str) -> dict[str, object]:
        """Пробуждение ПК.

        Два независимых пути: собственный magic packet (работает, если
        контроллер в одной сети с ПК) и команда ESP32 (работает, если
        контроллер снаружи, а плата дома). Пробуем оба — успех хотя бы
        одного считается успехом.
        """
        pc = self.get(pc_id)
        if pc.config.mac_address is None:
            raise WakeFailedError("для этого ПК не задан MAC-адрес: разбудить нечем", pc_id=pc_id)

        attempts: list[dict[str, object]] = []
        order = ["esp32", "direct"] if self._settings.wol.prefer_esp32 else ["direct", "esp32"]

        for method in order:
            if method == "direct" and self._settings.wol.enabled:
                try:
                    await send_magic_packet(
                        pc.config.mac_address,
                        broadcast=pc.config.broadcast_address,
                        port=pc.config.wol_port,
                        repeat=self._settings.wol.repeat,
                    )
                except Exception as exc:
                    attempts.append({"method": "direct", "ok": False, "error": str(exc)})
                else:
                    attempts.append({"method": "direct", "ok": True})
            elif method == "esp32" and self._esp32 is not None:
                try:
                    reply = await self._esp32.wake_on_lan(
                        pc.config.mac_address,
                        broadcast=pc.config.broadcast_address,
                        port=pc.config.wol_port,
                        repeat=self._settings.wol.repeat,
                    )
                except Exception as exc:
                    attempts.append({"method": "esp32", "ok": False, "error": str(exc)})
                else:
                    attempts.append(
                        {
                            "method": "esp32",
                            "ok": True,
                            "simulated": reply.result.get("simulated", False),
                        }
                    )

        if not any(a["ok"] for a in attempts):
            raise WakeFailedError(
                "не удалось отправить magic packet ни одним способом",
                pc_id=pc_id,
                attempts=attempts,
            )

        pc.state = DeviceState.CONNECTING
        pc.consecutive_failures = 0
        self._notify("wake")
        log.info("отправлено пробуждение", pc=pc_id, attempts=attempts)
        return {"mac_address": pc.config.mac_address, "attempts": attempts}

    async def shutdown(self, pc_id: str) -> ActionResult:
        pc = self.get(pc_id)
        # Предупреждаем ДО выключения: после него ПК уже не сможет ничего
        # отправить, а сторож на плате увидит пропажу и включит машину обратно.
        await self._snooze_guard(pc)
        result = await pc.client.shutdown()
        if result.success:
            pc.state = DeviceState.CONNECTING
            self._notify("power")
        return result

    async def restart(self, pc_id: str) -> ActionResult:
        pc = self.get(pc_id)
        result = await pc.client.restart()
        if result.success:
            pc.state = DeviceState.CONNECTING
            self._notify("power")
        return result

    async def _snooze_guard(self, pc: PcRuntime) -> None:
        """Просит плату не будить этот ПК: выключение плановое.

        Любая неудача здесь не должна мешать выключению — в худшем случае
        плата поднимет ПК обратно, и это заметно, но не опасно.
        """
        if not pc.config.guarded_by_esp32 or self._esp32 is None:
            return
        try:
            reply = await self._esp32.guard_snooze(pc.config.guard_snooze_minutes)
        except Remo32Error as exc:
            log.warning(
                "не удалось предупредить плату о выключении",
                pc=pc.config.id,
                error=str(exc),
            )
            return
        if reply is None:
            log.warning(
                "прошивка платы не умеет сторожить: она может включить ПК обратно",
                pc=pc.config.id,
            )
        else:
            log.info(
                "плата предупреждена о плановом выключении",
                pc=pc.config.id,
                minutes=pc.config.guard_snooze_minutes,
            )

    async def run_action(self, pc_id: str, action_id: str) -> ActionResult:
        pc = self.get(pc_id)
        return await pc.client.run_action(action_id)

    async def stats(self, pc_id: str) -> SystemStats:
        pc = self.get(pc_id)
        stats = await pc.client.stats()
        pc.stats = stats
        pc.stats_at = time.monotonic()
        return stats

    async def actions(self, pc_id: str) -> list[ActionDescriptor]:
        pc = self.get(pc_id)
        pc.actions = await pc.client.actions()
        return pc.actions

    async def action_editor(self, pc_id: str) -> ActionEditorState:
        return await self.get(pc_id).client.action_editor()

    async def save_action(
        self, pc_id: str, action_id: str, payload: dict[str, Any]
    ) -> ActionDescriptor:
        pc = self.get(pc_id)
        descriptor = await pc.client.save_action(action_id, payload)
        # Кэш действий устарел: следующий запрос списка должен увидеть новую
        # кнопку, а не то, что лежало здесь до правки.
        pc.actions = await pc.client.actions()
        return descriptor

    async def delete_action(self, pc_id: str, action_id: str) -> ActionEditorState:
        pc = self.get(pc_id)
        state = await pc.client.delete_action(action_id)
        pc.actions = await pc.client.actions()
        return state

    def terminal_target(self, pc_id: str, session: str | None, cols: int, rows: int) -> str:
        """Адрес WebSocket терминала агента.

        Терминал должен быть разрешён и в контроллере, и в агенте: два
        независимых выключателя, чтобы случайная правка одного конфига не
        открывала оболочку.
        """
        pc = self.get(pc_id)
        if not pc.config.terminal_enabled:
            raise TerminalDisabledError(
                f"терминал для «{pc.config.name}» выключен в конфигурации контроллера",
                pc_id=pc_id,
            )
        if not pc.agent_terminal_enabled:
            raise TerminalDisabledError(
                f"агент на «{pc.config.name}» не разрешает терминал", pc_id=pc_id
            )
        return pc.client.terminal_ws_url(session, cols, rows)
