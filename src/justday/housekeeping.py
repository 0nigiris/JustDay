"""Хозяйство демона: опрос работников, перезагрузка, память, цикл, страница дня.

Вынесено из daemon.py (Р-80). Миксин: тела методов не менялись, `self` — демон."""
from __future__ import annotations

import asyncio
import logging
import time

from . import (
    calendar_lane,
    desktop,
    events,
    island,
    memory,
    sysload,
    workers,
)
from . import weather as weather_mod
from .aio import spawn
from .i18n import t

log = logging.getLogger("justday.daemon")


class HousekeepingMixin:
    async def _housekeeping(self) -> None:
        poll = self.cfg["workers"]["poll_seconds"]
        last_poll = last_mail = last_ping = last_weather = 0.0
        last_update_check = time.monotonic() - self.cfg["updates"]["interval_hours"] * 3600 + 120  # first check 2 min after start
        m = self.cfg["mail"]
        while True:
            await asyncio.sleep(self.HOUSEKEEPING_EVERY)
            # Одно исключение в круге убивало навсегда почту, воркеров, выгрузку слуха и очередь
            # событий (Р-14): задача умирала молча. Круг, который упал, — просто пропущенный круг.
            try:
                upd = self.cfg["updates"]
                if upd["check"] and time.monotonic() - last_update_check > upd["interval_hours"] * 3600:
                    last_update_check = time.monotonic()
                    from . import manage

                    try:
                        st = await asyncio.get_running_loop().run_in_executor(None, manage.update_status)
                        self.update_info = st if st.get("ok") and st.get("behind") else None
                        self.publish(update=self.update_info)
                    except Exception as e:
                        log.info("update check failed: %s", type(e).__name__)
                self._publish_focus()
                await self._reboot_maybe()
                await self._memory_maybe()
                await self._welcome_back()
                # Подняться обратно по лестнице можно и молча, не дожидаясь следующей просьбы: лимит
                # возвращается сам по себе, и ждать с ним до разговора незачем.
                await self._try_home()
                await self._diary_maybe()
                await self._cycle_maybe()
                if time.monotonic() - getattr(self, "_last_cal", 0) > 300 and calendar_lane.urls():
                    self._last_cal = time.monotonic()
                    try:
                        nxt = await asyncio.get_running_loop().run_in_executor(None, calendar_lane.upcoming, 2)
                    except Exception:
                        nxt = None
                    self.publish(next_event=nxt)
                if time.monotonic() - getattr(self, "_last_observe", 0) > 60 and calendar_lane.urls():
                    self._last_observe = time.monotonic()
                    spawn(self._observe())
                isl = self.cfg["island"]
                if isl["show_weather"] and isl["city"] and (time.monotonic() - last_weather > 900 or self._weather_city != isl["city"]):
                    last_weather, self._weather_city = time.monotonic(), isl["city"]
                    try:
                        self.weather = await asyncio.get_running_loop().run_in_executor(None, weather_mod.fetch_weather, isl["city"])
                    except Exception as e:
                        log.info("weather unavailable: %s", type(e).__name__)
                    self.publish(weather=self.weather)
                # Игра началась — видеопамять её. Голос и так молчит в играх (tts.mute_in_games), но
                # молчащая модель занимала столько же, сколько говорящая.
                game = desktop.running_game()
                if game != getattr(self, "_game_seen", None):
                    self._game_seen = game
                    self.publish(game=game)    # оболочка в играх не анимирует (JD.gameMode)
                in_game = bool(self.cfg["tts"].get("mute_in_games", True)) and bool(game)
                if in_game and not self._gave_up_vram:
                    self._gave_up_vram = True
                    self.stt.unload()
                    await asyncio.get_running_loop().run_in_executor(None, self.tts.nudge, "sleep")
                    log.info("игра запущена — видеопамять отпущена")
                elif not in_game:
                    self._gave_up_vram = False
                    mins = float(self.cfg["stt"].get("idle_unload_minutes", 15) or 0)
                    if await asyncio.get_running_loop().run_in_executor(None, self.stt.idle_unload, mins):
                        log.info("слух молчал %g мин — видеопамять отпущена", mins)
                if time.monotonic() - last_ping > 5:
                    last_ping = time.monotonic()
                    self.stt.vocabulary = island.vocabulary(self.cfg)  # contacts learned meanwhile
                if m["address"] and m["announce"] and time.monotonic() - last_mail > m["poll_seconds"]:
                    last_mail = time.monotonic()
                    try:
                        news = await asyncio.get_running_loop().run_in_executor(None, self.mail.check_new)
                    except Exception as e:
                        log.warning("mail poll failed: %s", type(e).__name__)
                        news = ""
                    if news:
                        events.emit("mail_new")
                        card = self.mail.card(news)
                        if card:
                            self.publish(kind="card", card=card)
                        await self.say(news + " " + t("Сказать, о чём?"))
                if not self._wake and self.state != "listening" and time.monotonic() - self._last_mic_use > 20:
                    self.mic.stop()
                if self.cfg["workers"]["auto_review"] and time.monotonic() - last_poll > poll:
                    last_poll = time.monotonic()
                    try:
                        reports, active = await asyncio.get_running_loop().run_in_executor(None, workers.pending_reports)
                        if active != self._workers_active:
                            self._workers_active = active
                            self.publish(workers=active)
                    except Exception:
                        log.exception("worker poll failed")
                        reports = []
                    for r in reports:
                        msg = (f"[Событие JustDay] Фоновая сессия Claude Code {r['id']} в {r.get('cwd')} перешла в состояние "
                               f"«{r['state']}»" + (f" (ждёт: {r['waiting_for']})" if r.get("waiting_for") else "") +
                               f". Её задача: {r.get('task', '')[:500]}\nПроверь результат (`justday claude result {r['id']}`, "
                               "git diff, тесты) и действуй по исходной цели пользователя: если нужно — отправь Claude "
                               "уточнение через `justday claude send`; если всё готово или нужен пользователь — кратко доложи голосом.")
                        self._event_queue.put_nowait(msg)
                if not self._event_queue.empty() and not self.brain.busy and self.state == "idle":
                    spawn(self.run_turn(self._event_queue.get_nowait(), source="event"))
            except Exception:
                log.exception("housekeeping round failed")

    async def _reboot_maybe(self) -> None:
        """Раз в неделю напомнить перезагрузиться. Напомнить, а не перезагрузить.

        Машина, которая не выключается месяцами, копит обновления ядра, утёкшую память драйверов и
        службы, пережившие три своих обновления. Это не катастрофа, но однажды становится ею — и
        всегда не вовремя.
        Перезагружаться сам ассистент не станет: за компьютером может идти работа, которой он не
        видит, и выбирать за человека момент потерять несохранённое — не его дело.
        """
        days = float(self.cfg["ui"].get("reboot_reminder_days") or 0)
        if not days:
            return
        now = time.time()
        state = events.load_state()
        said = float(state.get("reboot_said") or 0)
        if now - said < 20 * 3600:          # не чаще раза в сутки, даже если он не перезагрузился
            return
        try:
            up = await asyncio.get_running_loop().run_in_executor(None, sysload.uptime)
        except Exception:
            return
        if up < days * 86400:
            return
        events.save_state(reboot_said=now)
        weeks = up / 86400
        self.notify(t("Компьютер работает без перезагрузки {days} дней — стоит перезагрузить.")
                    .format(days=int(weeks)), icon="system-reboot")
        events.emit("reboot_reminder", days=round(weeks, 1))

    async def _memory_maybe(self) -> None:
        """Указатель памяти читается в каждом разговоре; когда он разросся, сказать об этом — раз в неделю."""
        state = events.load_state()
        if time.time() - float(state.get("memory_said") or 0) < 7 * 86400:
            return
        warn = int((self.cfg.get("memory") or {}).get("warn_lines", memory.BUSY_LINES) or 0)
        st = await asyncio.get_running_loop().run_in_executor(None, memory.state, warn)
        if not st["busy"]:
            return
        events.save_state(memory_said=time.time())
        self.notify(t("Память разрослась: {n} строк в указателе. Загляни в настройки и убери лишнее.")
                    .format(n=st["index_lines"]), icon="dialog-information")

    async def _cycle_maybe(self) -> None:
        """Цикл ассистента: следующий созревший шаг — отдельной службой, и только когда он свободен.

        Свободен — не разговор, не игра; шаг с away ещё и ждёт, пока человек отойдёт от машины."""
        if not (self.cfg.get("cycle") or {}).get("enabled") or self.state != "idle" or getattr(self, "_game_seen", None):
            return
        from . import cycle, server

        loop = asyncio.get_running_loop()
        step = cycle.next_due(self.cfg, server.here())
        if step and not await loop.run_in_executor(None, cycle.running):
            ok = await loop.run_in_executor(None, cycle.launch, step["name"])
            log.info("цикл: %s — %s", step["name"], "запущен" if ok else "не запустился")

    async def _diary_maybe(self) -> None:
        """Страница дня в Obsidian, вечером и сама.

        Собирается из фактов — журнала и планов, — поэтому ничего не стоит.
        Ассистенту достаточно дописать к ней пару слов, если его попросят."""
        hour = int(self.cfg["notes"].get("diary_hour") or 0)
        if not hour:
            return
        today = time.strftime("%Y-%m-%d")
        if time.localtime().tm_hour < hour or events.load_state().get("diary_day") == today:
            return
        events.save_state(diary_day=today)  # даже если не выйдет: второй раз за вечер не пробуем
        try:
            from . import notes

            got = await asyncio.get_running_loop().run_in_executor(None, notes.diary)
            events.emit("diary", file=got["file"], asked=got["asked"], closed=got["closed"])
        except Exception as e:
            log.info("страница дня не записалась: %s", e)
