"""Наблюдатели за рабочим столом: уведомления, яркость, раскладка, окна (D-Bus и KWin).

Вынесено из daemon.py (Р-80). Каждый — долгая задача, которую `run()` запускает один раз; все
читают и пишут состояние демона (`self._windows`, `self._notify_watch`, `self.publish`), поэтому
миксин."""
from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import time

from . import (
    desktop,
    notifications,
)

log = logging.getLogger("justday.daemon")



class WatchersMixin:
    async def _watch_notifications(self) -> None:
        """Mirror desktop notifications onto the island (read-only eavesdrop; Plasma still shows and owns them).
        They stay on this computer: nothing is passed to the brain."""
        rule = "type='method_call',interface='org.freedesktop.Notifications',member='Notify'"
        while True:
            if not self._notify_watch:
                await asyncio.sleep(1)
                continue
            try:
                proc = self._notify_proc = await asyncio.create_subprocess_exec(
                    "dbus-monitor", "--session", rule, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
                buf: list[str] = []
                async for raw in proc.stdout:
                    line = raw.decode("utf-8", "replace")
                    if line.startswith(("method call", "signal")):
                        self._emit_notification("".join(buf))
                        buf = [] if line.startswith("signal") else [line]
                    elif buf:
                        buf.append(line)
                        if line.strip().startswith("int32"):  # expire timeout = last argument
                            self._emit_notification("".join(buf))
                            buf = []
                await proc.wait()
            except (OSError, asyncio.CancelledError):
                return
            await asyncio.sleep(5)

    async def _watch_brightness(self) -> None:
        """Brightness changes → island OSD (separate from app notifications)."""
        loop = asyncio.get_running_loop()
        bin = desktop.qdbus_bin()
        if not bin:
            return

        def _read() -> tuple[int, int] | None:
            try:
                cur = subprocess.run(
                    [bin, "org.kde.Solid.PowerManagement",
                     "/org/kde/Solid/PowerManagement/Actions/BrightnessControl",
                     "org.kde.Solid.PowerManagement.Actions.BrightnessControl.brightness"],
                    capture_output=True, text=True, timeout=3).stdout.strip()
                mx = subprocess.run(
                    [bin, "org.kde.Solid.PowerManagement",
                     "/org/kde/Solid/PowerManagement/Actions/BrightnessControl",
                     "org.kde.Solid.PowerManagement.Actions.BrightnessControl.brightnessMax"],
                    capture_output=True, text=True, timeout=3).stdout.strip()
                return int(cur or 0), int(mx or 0)
            except (OSError, subprocess.SubprocessError, ValueError):
                return None

        last: tuple[int, int] | None = await loop.run_in_executor(None, _read)
        if last and last[1] > 0:
            self.publish(brightness=last[0], brightness_max=last[1])
        rule = ("type='signal',interface='org.kde.Solid.PowerManagement.Actions.BrightnessControl',"
                "member='brightnessChanged'")
        while True:
            try:
                proc = await asyncio.create_subprocess_exec(
                    "dbus-monitor", "--session", rule,
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
                async for raw in proc.stdout:
                    if b"brightnessChanged" not in raw and b"int32" not in raw:
                        continue
                    got = await loop.run_in_executor(None, _read)
                    if not got or got[1] <= 0:
                        continue
                    if got != last:
                        last = got
                        self.publish(brightness=got[0], brightness_max=got[1])
                await proc.wait()
            except (OSError, asyncio.CancelledError):
                return
            await asyncio.sleep(5)

    async def _watch_layout(self) -> None:
        """Раскладка клавиатуры — для полосы лотка.

        Опрос тут не нужен: плазма сама кричит на шине, когда раскладку сменили. Опрашивать раз в
        секунду значило бы будить демона восемьдесят шесть тысяч раз в сутки ради события, которое
        случается десятки раз.
        """
        loop = asyncio.get_running_loop()
        if desktop.backend() != "kwin":
            return
        self._layout = await loop.run_in_executor(None, desktop.layout_now)
        if self._layout:
            self.publish(layout=self._layout)
        rule = "type='signal',interface='org.kde.KeyboardLayouts'"
        while True:
            try:
                proc = self._layout_proc = await asyncio.create_subprocess_exec(
                    "dbus-monitor", "--session", rule, stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL)
                async for raw in proc.stdout:
                    if b"layoutChanged" not in raw and b"layoutListChanged" not in raw:
                        continue
                    got = await loop.run_in_executor(None, desktop.layout_now)
                    if got and got != self._layout:
                        self._layout = got
                        self.publish(layout=got)
                await proc.wait()
            except (OSError, asyncio.CancelledError):
                return
            await asyncio.sleep(5)

    def _publish_windows_now(self) -> bool:
        """Отправить накопленный список окон. True — отправили."""
        got = self._windows_pending
        self._windows_pending = None
        if got is None or got == self._windows:
            return False
        # Empty flash during KWin script reload blanked the dock; keep last list
        # for ~1s, then accept a real empty desktop.
        if isinstance(got, list) and len(got) == 0 and self._windows:
            started = getattr(self, "_empty_windows_since", None)
            now = time.monotonic()
            if started is None:
                self._empty_windows_since = now
                return False
            if now - started < 1.0:
                return False
            self._empty_windows_since = None
        else:
            self._empty_windows_since = None
        self._windows = got
        # Окно, где человек печатал: когда он кликнет по панели эмодзи, фокус на миг уйдёт к ней,
        # и вставке нужно знать, куда возвращаться.
        for w in got or []:
            if isinstance(w, dict) and w.get("active") and w.get("id"):
                self._last_active_id = w["id"]
        self._windows_sent = time.monotonic()
        self.publish(windows=got)
        return True

    def _last_active_app(self) -> str:
        """Класс окна, где человек печатал: терминалу вставка нужна другим сочетанием (glyphs.is_terminal)."""
        for w in self._windows or []:
            if isinstance(w, dict) and w.get("id") == self._last_active_id:
                return str(w.get("app") or "")
        return ""

    def _focus_back(self) -> bool:
        """Дождаться, пока окно, где человек печатал, снова станет активным (из потока, не из цикла).

        После клика по панели эмодзи фокус на миг уходит к ней, и Ctrl+V, пришедший раньше времени,
        пропадал. Фиксированные паузы (0,4 с) это лечили, но были заметны; список окон же обновляется
        событием KWin, так что смотрим в него. Не вернулся за 0,15 с — просим KWin явно."""
        want = self._last_active_id
        if not want:
            return False

        def back() -> bool:
            return any(w.get("id") == want and w.get("active") for w in self._windows or [] if isinstance(w, dict))

        time.sleep(0.04)  # событие о смене фокуса идёт чуть позже щелчка
        for step in range(30):
            if back():
                return True
            if step == 7:
                desktop.windows("focus", wid=want)
            time.sleep(0.02)
        return False

    async def _publish_windows_debounced(self) -> None:
        await asyncio.sleep(self.WINDOWS_QUIET)
        self._publish_windows_now()

    async def _watch_windows(self) -> None:
        """Живой список окон — для дока.

        KWin не отдаёт список окон обычным клиентам вовсе: в реестре вейланда нет ни
        wlr-foreign-toplevel, ни org_kde_plasma_window_management — их видит одна плазма. Поэтому в
        самом KWin живёт маленький скрипт, который просыпается на событиях окон и пишет строку в
        журнал, а демон эту строку читает. Опрос раз в секунду стоил бы десятой доли ядра круглые
        сутки; здесь в покое не тратится ничего.
        """
        loop = asyncio.get_running_loop()
        if desktop.backend() != "kwin":
            log.info("окна: KWin недоступен, док покажет только закреплённое")
            return
        while True:
            try:
                proc = self._windows_proc = await asyncio.create_subprocess_exec(
                    "journalctl", "-f", "-n", "0", "--no-pager", "-o", "cat", "-g", desktop.WATCH_TAG.strip(),
                    stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
                # Скрипт селится после того, как журнал уже читают: он говорит первое слово сразу
                # при загрузке, и сказанное до подписки не догнать ничем.
                await asyncio.sleep(0.4)
                if not await loop.run_in_executor(None, desktop.watch_start):
                    log.warning("окна: KWin не принял скрипт")
                async for raw in proc.stdout:
                    line = raw.decode("utf-8", "replace")
                    _, _, payload = line.partition(desktop.WATCH_TAG)
                    if not payload.strip().startswith("["):
                        continue
                    try:
                        got = json.loads(payload)
                    except ValueError:
                        continue
                    if got == self._windows or got == self._windows_pending:
                        continue
                    # Бурю геометрии (окно тянут за угол) надо сглаживать, иначе док
                    # перерисовывается десятки раз в секунду. Но платить этой паузой за каждое
                    # нажатие нельзя: человек свернул окно значком, тут же жмёт снова — и док всё
                    # ещё думает, что окно открыто. Поэтому первое изменение уходит сразу, а
                    # сглаживается только то, что пришло следом.
                    self._windows_pending = got
                    quiet = time.monotonic() - self._windows_sent >= self.WINDOWS_QUIET
                    waiting = self._windows_debounce is not None and not self._windows_debounce.done()
                    if quiet and not waiting:
                        self._publish_windows_now()
                        continue
                    if waiting:
                        continue
                    self._windows_debounce = asyncio.create_task(self._publish_windows_debounced())
                await proc.wait()
            except (OSError, asyncio.CancelledError):
                return
            # KWin перезапустили — скрипт ушёл вместе с ним; следующий круг поселит его заново.
            await asyncio.sleep(5)

    def _emit_notification(self, raw: str) -> None:
        if "member=Notify" not in raw or not self.cfg["island"].get("show_notifications", True):
            return
        n = notifications.parse_notification(raw)
        if not n or n["app"] == "JustDay":  # our own approval / status notifications
            return
        self.publish(kind="notification", notification=n)
