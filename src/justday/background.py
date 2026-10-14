"""Фоновые петли демона: нагрузка машины, сессии, процессор, индекс файлов, буфер обмена.

Вынесено из daemon.py (Р-80). Миксин: тела методов не менялись, `self` — демон."""
from __future__ import annotations

import asyncio
import logging
import subprocess
import time

from . import (
    clipboard,
    dock,
    filesearch,
    media,
    sysload,
)
from .aio import die_with_daemon, spawn
from .i18n import t

log = logging.getLogger("justday.daemon")


class BackgroundMixin:
    # ---------------- нагрузка машины и буфер обмена ----------------

    async def load_snapshot(self) -> dict:
        """Взгляд на машину. Чтение /proc и nvidia-smi — в отдельном потоке: обход /proc стоит
        десятки миллисекунд, и в цикле событий это слышно в голосе."""
        return await asyncio.get_running_loop().run_in_executor(None, self.load.snapshot)

    async def _load_loop(self) -> None:
        """Пока островок показывает монитор — раз в секунду присылать новые цифры.

        Ровно раз в секунду и ровно пока смотрят: графики требуют равного шага, а в покое опрашивать
        машину незачем. Первый взгляд после долгого перерыва сравнивать не с чем, поэтому счётчик
        обновляется дважды, и наружу идёт второй."""
        while True:
            if self.load_watchers <= 0:
                # Без зрителей — не просыпаться раз в секунду впустую: ждём, пока `load_watch` нас разбудит.
                # Между проверкой и ожиданием нет await, поэтому разбудить «мимо» не может.
                self._load_wake.clear()
                await self._load_wake.wait()
                continue
            try:
                self.publish(load=await self.load_snapshot())
            except Exception:
                log.debug("не смог прочитать нагрузку", exc_info=True)
            await asyncio.sleep(1.0)

    async def _play_from_clipboard(self) -> str:
        """«Включи из буфера»: читаем буфер только по этой просьбе и берём из него одну ссылку YouTube — остальное не трогаем."""
        got = await asyncio.to_thread(subprocess.run, ["wl-paste", "--no-newline", "--type", "text"],
                                      capture_output=True, text=True, timeout=3)
        link = (got.stdout or "").strip()[:500] if got.returncode == 0 else ""
        if not media.parse_youtube(link):
            return t("В буфере нет ссылки на YouTube.")
        spawn(self.play_music(link))
        return ""

    def _game_slowdown(self) -> float:
        """Фоновые опросы в игре реже в десять раз: кадры игры дороже наших цифр (Р2-46)."""
        return 10.0 if getattr(self, "_game_seen", None) else 1.0

    SESSIONS_TICK = 1.0         # как часто смотреть, не изменились ли стенограммы (это только `stat`)
    SESSIONS_HEARTBEAT = 10.0   # а список перечитывать в любом случае не реже: ушедшая сессия стенограмму не меняет

    async def _sessions_loop(self) -> None:
        """Список живых сессий — только пока страницу смотрят и только когда что-то изменилось (Р-45).

        Раньше страница каждые две секунды просила список, и каждый раз запускался `claude agents --json`
        и читались хвосты всех стенограмм. Теперь дёшево смотрим отпечаток стенограмм (`stat`), а дорогой
        список собираем, когда он сменился или прошло `SESSIONS_HEARTBEAT`. Смотрят ли, решает QML: пока страница
        открыта, раз в полминуты он подтверждает это (`sessions_watch`), а не считает +1/−1 — тогда упавший
        островок не оставит демон «смотреть» навсегда."""
        from . import sessions as sessions_mod

        loop = asyncio.get_running_loop()
        seen, at = None, 0.0
        while True:
            if time.monotonic() > self._sessions_until:
                self._sessions_wake.clear()
                await self._sessions_wake.wait()
                seen = None                              # смотрели мимо: первое чтение — полное
                continue
            fingerprint = await loop.run_in_executor(None, sessions_mod.fingerprint)
            if fingerprint != seen or time.monotonic() - at >= self.SESSIONS_HEARTBEAT:
                try:
                    got = await loop.run_in_executor(None, sessions_mod.live, self.cfg["brain"].get("claude_cli", "claude"))
                    self.publish(sessions=got, claudeLimits=sessions_mod.limits())
                except Exception:
                    log.debug("не смог прочитать сессии", exc_info=True)
                seen, at = fingerprint, time.monotonic()
            await asyncio.sleep(self.SESSIONS_TICK * BackgroundMixin._game_slowdown(self))

    async def _cpu_loop(self) -> None:
        """Одно число для кошки в доке: насколько занят процессор.

        Свой счётчик, а не общий с монитором нагрузки: `Load.cpu()` считает разницу с прошлым
        взглядом, и два потребителя на одном экземпляре растащили бы эту разницу пополам.

        /proc/stat стоит микросекунды, поэтому читаем всегда, а отправляем — только когда есть кому
        смотреть и кошка включена. Раз в две секунды: кошка бежит от числа, а не от точности.
        """
        meter = sysload.Load()
        meter.cpu()                      # первый взгляд сравнивать не с чем
        last, last_mem = -1.0, -1.0
        while True:
            await asyncio.sleep(2.0 * BackgroundMixin._game_slowdown(self))
            try:
                pct = meter.cpu()["percent"]
                mem = sysload.memory()["percent"]
            except OSError:
                continue
            # Кошка на полосе включается отдельно от кошки в доке. Раньше смотрели только на док,
            # и с выключенной кошкой в доке кошка на полосе стояла на месте при любой нагрузке.
            if not self._subs or not (self.cfg["dock"].get("cat", True) or self.cfg["island"].get("cat")):
                continue
            if abs(pct - last) >= 1.5 or (pct < 1.5) != (last < 1.5) or abs(mem - last_mem) >= 1:
                last, last_mem = pct, mem
                self.publish(cpu=pct, mem=mem)  # память — для подсказки при наведении на кошку
            # Заодно корзина: один взгляд в каталог до первой записи, вопрос двоичный. Значок,
            # говорящий «пусто» при сорока файлах внутри, — это ложь о состоянии машины.
            full = dock.trash_full()
            if full != self._trash_full:
                self._trash_full = full
                self.publish(trash_full=full)

    async def _file_index_loop(self) -> None:
        """Keep the lightweight home-file index warm for menu Spotlight search.

        Rebuilds in a worker thread every few minutes. First pass runs soon after
        start so the first typed query already has Documents/Downloads indexed.
        Skips while a fullscreen window is up (games / video) — the walk + 1.8MB
        rewrite was a visible hitch on an already busy machine.
        """
        await asyncio.sleep(8.0)
        loop = asyncio.get_running_loop()
        while True:
            try:
                busy = any(w.get("full") for w in (self._windows or []) if isinstance(w, dict))
                if busy:
                    await asyncio.sleep(30.0)
                    continue
                got = await loop.run_in_executor(None, filesearch.ensure_fresh)
                log.info("file index: %s entries", got.get("n") or len(got.get("items") or []))
            except Exception:
                log.debug("file index refresh failed", exc_info=True)
            await asyncio.sleep(float(filesearch.INDEX_TTL))

    async def _clip_watch(self) -> None:

        """Следить за буфером обмена.

        На Wayland работу делает `wl-paste --watch`: он запускает `justday clip store` на каждое
        изменение. Процессы переживают демон не дольше самого демона — при остановке они гасятся
        вместе с ним.

        На X11 постоянного наблюдателя не существует, поэтому там демон сам заглядывает в буфер
        раз в секунду. Это дешевле, чем звучит: `xclip -o` не читает ничего, кроме самого буфера."""
        if not self.cfg.get("clipboard", {}).get("history", True):
            log.info("история буфера обмена выключена (clipboard.history)")
            return
        argv = clipboard.watch_argv()
        if argv:
            for cmd in argv:
                piped = cmd is clipboard.WATCH_TEXT      # текст приходит по трубе, картинки — своим процессом
                try:
                    proc = await asyncio.create_subprocess_exec(
                        *cmd, stdout=asyncio.subprocess.PIPE if piped else asyncio.subprocess.DEVNULL,
                        stderr=asyncio.subprocess.DEVNULL, preexec_fn=die_with_daemon)
                except OSError as e:
                    log.warning("не удалось следить за буфером: %s", e)
                    continue
                self._clip_procs.append(proc)
                if piped:
                    spawn(self._clip_text_stream(proc))
            log.info("история буфера обмена: wl-paste, %d наблюдателя", len(self._clip_procs))
            return
        log.info("история буфера обмена: опрос xclip")
        loop = asyncio.get_running_loop()
        while True:
            await asyncio.sleep(1.0)
            try:
                await loop.run_in_executor(None, clipboard.poll_once, self._clip_seen)
            except Exception:
                log.debug("опрос буфера не вышел", exc_info=True)

    async def _clip_text_stream(self, proc) -> None:
        """Каждое текстовое копирование приходит сюда по трубе; запоминается в потоке, чтобы не держать цикл."""
        loop = asyncio.get_running_loop()
        async for rec in clipboard.records(proc.stdout):
            try:
                await loop.run_in_executor(None, clipboard.store_watched, rec)
            except Exception:
                log.debug("не вышло запомнить копирование", exc_info=True)
