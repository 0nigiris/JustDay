"""Видео демона: куда включить (островок, окно, YouTube), продолжить закрытое, вернуть окно в островок.

Вынесено из daemon.py (Р-80). Миксин: ходит в `self.island_video`, `self.last_video`, `self.publish` демона."""
from __future__ import annotations

import asyncio
import logging
import re
import secrets
import time
from pathlib import Path
from typing import ClassVar

from . import (
    events,
    media,
)
from .i18n import t

log = logging.getLogger("justday.daemon")


class VideoMixin:
    WHERE_WORDS: ClassVar = [("browser", re.compile(r"ютуб|youtube|браузер|browser|сайт", re.I)),
                             ("window", re.compile(r"окн|окош|отдельн|плеер|window|весь экран|fullscreen", re.I)),
                             ("island", re.compile(r"остров|здесь|тут|сверху|island|here", re.I))]
    AUDIO_SUFFIXES: ClassVar = (".mp3", ".flac", ".ogg", ".opus", ".wav", ".m4a", ".aac", ".wma")

    def _pause_videos(self) -> None:
        if self.island_video:
            self.publish(kind="video_cmd", action="pause")
        media.window_command("set_property", "pause", True)

    async def _ask_where(self, e: dict) -> str | None:
        opts = [{"label": t("В острове"), "description": t("прямо здесь, поверх окон"), "icon": "go-top"},
                {"label": t("В окне"), "description": t("отдельный плеер, есть весь экран"), "icon": "window-new"},
                {"label": "YouTube", "description": t("в браузере, с комментариями"), "icon": "internet-web-browser"}]
        dur = f" · {e['duration'] // 60}:{e['duration'] % 60:02d}" if e.get("duration") else ""
        self.publish(kind="card", card={"type": "question", "header": t("Где включить видео?"), "options": opts,
                                        "question": e["title"] + (f"\n{e['channel']}{dur}" if e.get("channel") else ""),
                                        "thumb": e.get("thumb_url", "")})
        try:
            ans = await self._ask(t("Где включить: в острове, в окне или на ютубе?"), choices=[o["label"] for o in opts],
                                  free_text=True)
        finally:
            self.publish(kind="card_close")
        if ans in (None, "deny"):
            return None
        if ans == "allow":
            return "island"
        return next((w for w, rx in self.WHERE_WORDS if rx.search(ans)), None)

    async def play_video(self, query: str, where: str = "", random: bool = False, start: float = 0.0,
                         title: str = "") -> dict:
        loop = asyncio.get_running_loop()
        query = query.strip()
        # «включи видео про котов в островке»: место названо в самой просьбе. Оно сильнее настройки —
        # настройка говорит, что делать, когда не сказано ничего (запретить это можно video_where_strict).
        asked = ""
        if not query.startswith(("/", "~", "./")):
            asked, rest = media.where_asked(query)
            if asked and rest:
                query = rest
        path = Path(query).expanduser()
        try:
            if query.startswith(("/", "~", "./")) and path.exists():
                e = {"id": "", "title": title or path.stem, "channel": "", "duration": 0, "url": str(path),
                     "thumb_url": "", "file": str(path)}
            else:
                self.publish(kind="tool", detail=t("Ищу видео: {q}", q=query), icon="youtube")
                # «рандомное видео от …»: the daemon picks one out of the first results itself, which is
                # both instant and honest — no model writing a script to roll a die.
                found = await loop.run_in_executor(None, media.find, query, "video", 10 if random else 1)
                if not found:
                    return {"ok": False, "error": "nothing found"}
                e = secrets.choice(found) if random else found[0]
        except Exception as ex:
            return {"ok": False, "error": str(ex)}
        if not where and asked and not self.cfg["media"].get("video_where_strict"):
            where = asked
        where = where or self.cfg["media"]["video_where"]
        if where not in media.WHERE:
            where = await self._ask_where(e)
            if where is None:
                return {"ok": False, "error": "cancelled", "result": "the user did not choose where to play it"}
        if self.music.playing:
            await self.music.pause()
        done = {"island": t("видео в острове"), "window": t("видео в окне"), "browser": t("видео на YouTube")}[where]
        if where == "browser" and not e.get("file"):
            media.open_browser(e["url"], start)
        elif where == "window" or (where == "browser" and e.get("file")):
            media.open_window(e.get("file") or e["url"], start=start, title=e["title"])
        else:
            self.island_video = {"title": e["title"], "channel": e.get("channel", ""), "url": e["url"],
                                 "thumb": e.get("thumb_url", ""), "file": e.get("file", ""), "progress": 0.0,
                                 "start": max(0.0, start)}
            self.publish(video=self.island_video)
            if not e.get("file"):
                def progress(v: dict) -> None:
                    if self.island_video and self.island_video.get("url") == e["url"]:
                        self.island_video["progress"] = v["progress"]
                        self.publish(video=self.island_video)
                try:
                    got = await loop.run_in_executor(None, media.download_video, e, self._progress(progress, e["title"]))
                except Exception as ex:
                    self.island_video = None
                    self.publish(video=None)
                    return {"ok": False, "error": str(ex)}
                if not self.island_video or self.island_video.get("url") != e["url"]:
                    return {"ok": False, "error": "cancelled", "result": "the user closed the video while it loaded"}
                self.island_video.update(file=got["file"], thumb=got.get("thumb") or self.island_video["thumb"], progress=1.0)
                self.publish(video=self.island_video)
        events.emit("media_video", title=e["title"], where=where)
        return {"ok": True, "title": e["title"], "where": where, "url": e["url"], "done": done + ": " + e["title"]}

    def remember_video(self, pos: float = 0.0, in_window: bool = False) -> None:
        """Закрытый ролик остаётся в памяти — как песня остаётся в очереди плеера.

        in_window: ролик не закрыт, а уехал в отдельное окно — его можно вернуть назад."""
        v = self.island_video
        if not v or not (v.get("file") or v.get("url")):
            return
        self.last_video = {"title": v.get("title", ""), "channel": v.get("channel", ""), "url": v.get("url", ""),
                           "file": v.get("file", ""), "thumb": v.get("thumb", ""),
                           "pos": max(0.0, pos or float(v.get("pos") or 0)), "at": time.time(),
                           "in_window": in_window}

    async def play_dropped(self, target: str) -> dict:
        """Файл или ссылка, брошенные на остров: песня уходит в плеер, всё остальное — в кадр."""
        target = (target or "").strip()
        if not target:
            return {"ok": False, "error": "nothing was dropped"}
        if target.lower().endswith(self.AUDIO_SUFFIXES):
            return await self.play_music(target)
        return await self.play_video(target, where="island")

    async def resume_video(self, where: str = "island") -> dict:
        """Продолжить последний закрытый ролик с того же места."""
        v = self.last_video
        if not v:
            return {"ok": False, "error": "nothing to resume"}
        target = v.get("file") or v.get("url")
        if v.get("file") and not Path(v["file"]).exists():
            target = v.get("url") or ""
        if not target:
            return {"ok": False, "error": "the video is gone"}
        return await self.play_video(target, where=where, start=float(v.get("pos") or 0), title=v.get("title", ""))

    async def video_popin(self) -> dict:
        """Отдельное окно mpv → обратно в островок, с той же секунды."""
        loop = asyncio.get_running_loop()
        st = await loop.run_in_executor(None, media.window_state)
        if not st:
            return {"ok": False, "error": "no video window"}
        target = st.get("path") or st.get("url") or ""
        if not target:
            return {"ok": False, "error": "the window does not say what it plays"}
        pos = float(st.get("pos") or 0)
        await loop.run_in_executor(None, media.window_close)
        r = await self.play_video(target, where="island", start=pos, title=st.get("title", ""))
        if r.get("ok") and self.last_video:
            self.last_video["in_window"] = False
            self.publish(video_last=self.last_video)
        return r
