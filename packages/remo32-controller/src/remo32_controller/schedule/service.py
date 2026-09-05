"""Планировщик: хранение расписаний и их исполнение.

Три решения, которые стоит объяснить.

**Файл, а не память.** Расписания живут в JSON рядом с остальными данными
контроллера. ПК перезагружается раз в неделю — расписание обязано это
пережить, иначе им нельзя пользоваться.

**Догон пропущенного.** Если контроллер лежал в момент срабатывания
(перезагрузка, обновление), правило выполняется с опозданием, но только
в пределах окна догона. Иначе после ребута в полдень внезапно сработало бы
ночное гашение света.

**Защита от повторов.** У каждой записи хранится метка последнего
сработавшего слота. Тик планировщика чаще одной минуты, и без такой метки
одно правило выстрелило бы несколько раз подряд.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from datetime import datetime, timedelta
from pathlib import Path
from typing import TYPE_CHECKING

from remo32_controller.schedule.models import ScheduleCreate, ScheduleEntry, ScheduleUpdate
from remo32_core.errors import ConfigurationError, NotFoundError, PcNotFoundError, Remo32Error
from remo32_core.log import get_logger

if TYPE_CHECKING:
    from remo32_controller.devices import DeviceRegistry

log = get_logger("controller.schedule")

TICK_SECONDS = 20.0
CATCH_UP_MINUTES = 15


class ScheduleNotFoundError(NotFoundError):
    code = "schedule_not_found"

    def __init__(self, schedule_id: str) -> None:
        super().__init__(f"расписание «{schedule_id}» не найдено")


class ScheduleExistsError(Remo32Error):
    code = "schedule_exists"
    http_status = 409

    def __init__(self, schedule_id: str) -> None:
        super().__init__(f"расписание «{schedule_id}» уже существует")


class ScheduleService:
    def __init__(
        self,
        registry: DeviceRegistry,
        data_dir: Path,
        *,
        tick_seconds: float = TICK_SECONDS,
        catch_up_minutes: int = CATCH_UP_MINUTES,
    ) -> None:
        self._registry = registry
        self._path = data_dir / "schedules.json"
        self._tick = tick_seconds
        self._catch_up = timedelta(minutes=catch_up_minutes)
        self._entries: dict[str, ScheduleEntry] = {}
        self._task: asyncio.Task[None] | None = None
        self._lock = asyncio.Lock()
        self._load()

    # ------------------------------------------------------------------
    # Хранилище
    # ------------------------------------------------------------------

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise ConfigurationError(f"не читается {self._path}: {exc}") from exc

        for item in raw.get("schedules", []):
            try:
                entry = ScheduleEntry.model_validate(item)
            except ValueError as exc:
                # Одна битая запись не должна ронять контроллер целиком:
                # остальные расписания продолжат работать.
                log.error("расписание пропущено из-за ошибки", item=item, error=str(exc))
                continue
            self._entries[entry.id] = entry
        log.info("расписания загружены", count=len(self._entries), path=str(self._path))

    def _save(self) -> None:
        payload = {"schedules": [e.model_dump(mode="json") for e in self._entries.values()]}
        self._path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self._path.with_suffix(".json.tmp")
        # Пишем во временный файл и переименовываем: при отключении питания
        # на диске останется либо старая версия, либо новая, но не обрубок.
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self._path)

    # ------------------------------------------------------------------
    # Операции
    # ------------------------------------------------------------------

    def list_entries(self) -> list[ScheduleEntry]:
        """Все правила, отсортированные по времени.

        Метод намеренно не называется ``list``: такое имя внутри класса
        затеняет встроенный тип в аннотациях остальных методов.
        """
        return sorted(self._entries.values(), key=lambda e: (e.at, e.id))

    def get(self, schedule_id: str) -> ScheduleEntry:
        entry = self._entries.get(schedule_id)
        if entry is None:
            raise ScheduleNotFoundError(schedule_id)
        return entry

    def create(self, data: ScheduleCreate) -> ScheduleEntry:
        if data.id in self._entries:
            raise ScheduleExistsError(data.id)
        self._check_pc(data.pc_id)
        entry = ScheduleEntry.model_validate(data.model_dump())
        self._entries[entry.id] = entry
        self._save()
        log.info("расписание создано", id=entry.id, at=entry.at, action=entry.action_id)
        return entry

    def update(self, schedule_id: str, data: ScheduleUpdate) -> ScheduleEntry:
        entry = self.get(schedule_id)
        patch = data.model_dump(exclude_unset=True)
        if "pc_id" in patch:
            self._check_pc(patch["pc_id"])
        updated = entry.model_copy(update=patch)
        # Прогоняем через валидатор ещё раз: model_copy его не вызывает,
        # а через API сюда может приехать «25:99».
        updated = ScheduleEntry.model_validate(updated.model_dump())
        self._entries[schedule_id] = updated
        self._save()
        log.info("расписание изменено", id=schedule_id, changed=sorted(patch))
        return updated

    def delete(self, schedule_id: str) -> None:
        self.get(schedule_id)
        del self._entries[schedule_id]
        self._save()
        log.info("расписание удалено", id=schedule_id)

    def _check_pc(self, pc_id: str) -> None:
        # 404, а не 500: правило ссылается на несуществующий ПК по вине
        # того, кто его создаёт, а не из-за поломки контроллера.
        if pc_id not in self._registry.ids():
            raise PcNotFoundError(f"ПК «{pc_id}» нет в конфигурации контроллера")

    # ------------------------------------------------------------------
    # Исполнение
    # ------------------------------------------------------------------

    async def run_now(self, schedule_id: str) -> ScheduleEntry:
        """Выполнить правило немедленно, не трогая его расписание.

        Метка слота при этом не ставится: ручной запуск в 20:00 не должен
        отменять плановое срабатывание в 23:00.
        """
        entry = self.get(schedule_id)
        return await self._execute(entry, mark_slot=None)

    async def _execute(self, entry: ScheduleEntry, *, mark_slot: str | None) -> ScheduleEntry:
        ok = True
        message: str | None = None
        try:
            result = await self._registry.run_action(entry.pc_id, entry.action_id)
            ok = result.success
            message = (
                result.message
                or (result.stderr or "").strip()
                or (result.stdout or "").strip()
                or None
            )
            if message is not None:
                message = message[:200]
        except Remo32Error as exc:
            # Выключенный ПК — обычное дело, а не авария контроллера.
            ok = False
            message = str(exc)
        except Exception as exc:
            ok = False
            message = f"неожиданная ошибка: {exc}"

        patch = {
            "last_run_at": datetime.now(),
            "last_ok": ok,
            "last_message": message,
        }
        if mark_slot is not None:
            patch["last_fired_slot"] = mark_slot

        updated = entry.model_copy(update=patch)
        self._entries[entry.id] = updated
        self._save()

        log.info(
            "расписание выполнено",
            id=entry.id,
            pc=entry.pc_id,
            action=entry.action_id,
            success=ok,
            planned=mark_slot is not None,
            message=message,
        )
        return updated

    def due(self, now: datetime) -> list[ScheduleEntry]:
        """Правила, которым пора сработать в момент ``now``."""
        result = []
        for entry in self._entries.values():
            if not entry.enabled:
                continue
            planned = now.replace(hour=entry.hour, minute=entry.minute, second=0, microsecond=0)
            if planned > now:
                continue
            if not entry.matches_day(planned):
                continue
            if now - planned > self._catch_up:
                continue
            if entry.last_fired_slot == entry.slot_key(planned):
                continue
            result.append(entry)
        return result

    async def tick(self, now: datetime | None = None) -> list[ScheduleEntry]:
        now = now or datetime.now()
        fired = []
        async with self._lock:
            for entry in self.due(now):
                planned = now.replace(hour=entry.hour, minute=entry.minute, second=0, microsecond=0)
                fired.append(await self._execute(entry, mark_slot=entry.slot_key(planned)))
        return fired

    # ------------------------------------------------------------------
    # Фоновый цикл
    # ------------------------------------------------------------------

    async def start(self) -> None:
        if self._task is None:
            self._task = asyncio.create_task(self._loop(), name="remo32-schedule")
            log.info("планировщик запущен", entries=len(self._entries), tick=self._tick)

    async def stop(self) -> None:
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    async def _loop(self) -> None:
        while True:
            try:
                await self.tick()
            except Exception as exc:
                # Цикл обязан пережить любую ошибку: иначе одно кривое
                # правило навсегда останавливает всё расписание.
                log.error("сбой в цикле планировщика", error=str(exc))
            await asyncio.sleep(self._tick)
