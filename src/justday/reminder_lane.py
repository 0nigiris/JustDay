"""Напоминания демона: таймеры, будильники, «разбуди через …», звонок и его выключение.

Вынесено из daemon.py (Р-80). Миксин: ходит в `self._reminder_task`, `self.say`, `self.publish` демона."""
from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime

from . import (
    audio,
    events,
    reminders,
)
from .aio import spawn
from .i18n import t

log = logging.getLogger("justday.daemon")


class ReminderMixin:
    # ---------------- timers, alarms, reminders ----------------
    async def reminder_fast(self, text: str) -> bool:
        """«поставь таймер на 10 минут», «разбуди в 7:30», «отмени будильник» — answered here, in one step."""
        req = reminders.parse(text)
        if not req:
            return False
        if req["action"] == "cancel":
            gone = await asyncio.get_running_loop().run_in_executor(None, reminders.cancel, req["which"])
            self._reschedule()
            await self.say(t("Отменил.") if gone else t("Нечего отменять."))
            self.brain.note(f"[Уже выполнено мгновенно: «{text}» → отменено {len(gone)}. Не повторяй.]")
            return True
        if req["action"] == "list":
            await self.say(self._reminders_line())
            return True
        rec = reminders.add(req["kind"], req["at"], req["label"], req["repeat"])
        self._reschedule()
        self.publish(reminders=self._reminders_state())
        when = datetime.fromtimestamp(rec["at"])
        if rec["kind"] == "timer":
            said = t("Таймер на {span}.", span=reminders.left(rec))
        else:
            said = t("Разбужу в {time}.", time=when.strftime("%H:%M")) if rec["kind"] == "alarm" \
                else t("Напомню в {time}.", time=when.strftime("%H:%M"))
        await self.earcon("done")
        await self.say(said)
        self.brain.note(f"[Уже выполнено мгновенно: «{text}» → {said}. Не повторяй.]")
        events.emit("reminder_set", what=rec["kind"], at=rec["at"], label=rec["label"])
        return True

    def _reminders_state(self) -> list[dict]:
        """What the island shows: what it is, when it rings, and how long is left."""
        return [{"id": r["id"], "kind": r["kind"], "at": r["at"], "label": r["label"], "repeat": r.get("repeat", "")}
                for r in reminders.items()[:5]]

    def _reminders_line(self) -> str:
        got = reminders.items()
        if not got:
            return t("Ничего не заведено.")
        parts = []
        for r in got[:3]:
            when = datetime.fromtimestamp(r["at"])
            name = r["label"] or {"timer": t("таймер"), "alarm": t("будильник")}.get(r["kind"], t("напоминание"))
            parts.append(t("{what}: {left}", what=name, left=reminders.left(r)) if r["kind"] == "timer"
                         else t("{what} в {time}", what=name, time=when.strftime("%H:%M")))
        return "; ".join(parts) + "."

    def _reschedule(self) -> None:
        """One sleeping task for whichever reminder is due first."""
        if self._reminder_task and not self._reminder_task.done():
            self._reminder_task.cancel()
        self._reminder_task = spawn(self._reminder_loop())

    async def _reminder_loop(self) -> None:
        while True:
            nxt = reminders.next_due()
            self.publish(reminders=self._reminders_state())
            if not nxt:
                return
            delay = nxt["at"] - time.time()
            if delay > 0:
                await asyncio.sleep(min(delay, 3600))   # wake at least hourly: the clock may have jumped
                if nxt["at"] - time.time() > 1:
                    continue
            await self._ring(nxt)

    async def _ring(self, rec: dict) -> None:
        """A timer or an alarm going off: the island shows it, the chime repeats until it is dismissed."""
        reminders.mark_done(rec["id"])
        said = reminders.phrase(rec)
        self._ringing = rec["id"]
        when = datetime.fromtimestamp(rec["at"])
        self.publish(kind="card", card={"type": "alarm", "kind": rec["kind"], "label": rec.get("label", ""),
                                        "time": when.strftime("%H:%M"), "id": rec["id"]})
        await self.music.duck(True)
        try:
            for i in range(20):  # ~1 minute of ringing, or until it is dismissed
                if self._ringing != rec["id"]:
                    break
                await self.player.play(audio.earcon("alarm"), 48000)
                if i == 0:
                    await self.say(t("{what}", what=said) if said else t("Таймер."))
                await asyncio.sleep(2.5)
        finally:
            if self._ringing == rec["id"]:
                self.dismiss_alarm(rec["id"])

    def dismiss_alarm(self, rec_id: str = "") -> None:
        if rec_id and self._ringing != rec_id:
            return
        self._ringing = ""
        spawn(self.music.duck(False))
        self.publish(kind="card_close")
        self.publish(reminders=self._reminders_state())
