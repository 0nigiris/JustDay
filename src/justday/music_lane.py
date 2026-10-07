"""Музыка демона: «включи …», библиотека, кэш скачанного, плеер и его цвета.

Вынесено из daemon.py (Р-80). Методы ходят в `self.player`, `self.music`, `self.publish` демона, поэтому миксин."""
from __future__ import annotations

import asyncio
import logging
import re
import subprocess
import time
from pathlib import Path

from . import (
    events,
    island,
    media,
    palette,
)
from .aio import spawn
from .i18n import t

log = logging.getLogger("justday.daemon")


class MusicMixin:
    # A query is "sure" when the words asked for are actually in the title of the first hit and nothing
    # else looks just as likely. "Flower Man" is sure — there is one. "No name" is not.
    SURE_GAP = 0.22          # how much better the first hit must be than the second
    SURE_HIT = 0.72          # how much of the query the first title must actually contain
    SURE_LOCAL = 0.95        # a downloaded track this close to the words asked for is *the* one

    # ---------------- music and video ----------------
    def _on_player(self, state: dict | None) -> None:
        self._player_state = state
        self.publish(player=state)
        if state and self.cfg["media"].get("color", "theme") == "theme":
            self._ask_colors(state)

    def _ask_colors(self, state: dict) -> None:
        """What colour is this music about? A cover is not an answer: a black sleeve can hold a yellow
        character's theme. The model is asked once per track, in the background, for the whole queue at
        once, and the island re-tints when the answer lands."""
        if (self._colors and not self._colors.done()) or time.monotonic() < self._colors_after:
            return
        here = [{"title": state.get("title", ""), "artist": state.get("artist", ""), "source": state.get("source", ""),
                 "cover": state.get("cover", "")}]
        ahead = [{"title": q.get("title", ""), "artist": q.get("artist", ""), "source": state.get("source", ""),
                  "cover": q.get("cover", "")}
                 for q in state.get("queue", []) if q.get("i", 0) >= state.get("index", 0)]
        want = palette.unknown(here + ahead)
        if want:
            self._colors = spawn(self._resolve_colors(want))

    async def _resolve_colors(self, want: list[dict]) -> None:
        web = bool(self.cfg["media"].get("color_web", True))
        try:
            got = await asyncio.to_thread(palette.resolve, want, web=web)
        except (OSError, ValueError, RuntimeError, subprocess.SubprocessError) as e:
            log.warning("track colours: %s", e)
            self._colors_after = time.monotonic() + 600  # do not ask again on every tick
            return
        log.info("track colours: %d of %d tracks", len(got), len(want))
        if got:
            self.music.refresh()

    async def media_fast(self, text: str) -> bool:
        """"пауза" / "следующая" for our player and "включи песню …" / "включи видео …" — without the brain."""
        move = media.video_word(text)
        if move:
            r = await (self.video_popin() if move == "popin" else self.resume_video())
            if r.get("ok"):
                events.emit("fast", text=text, desc=r.get("done", ""))
                self.brain.note(f"[Уже выполнено мгновенно, без тебя: «{text}» → {r.get('done', '')}. Не повторяй.]")
                await self.earcon("done")
                return True
            self.publish(kind="error", detail=t("Нечего вернуть"))
            return True
        act = media.control_word(text)
        if act and (self.music.active or self.island_video):
            r = await self.media_control(act)
            if r.get("ok"):
                events.emit("fast", text=text, desc=r.get("done", act))
                self.brain.note(f"[Уже выполнено мгновенно, без тебя: «{text}» → {r.get('done', act)}. Не повторяй.]")
                await self.earcon("done")
                return True
        req = media.parse(text)
        if not req:
            return False
        kind, query = req

        async def go():
            if kind == "music" and not media.is_url(query):
                near = media.find_local(query, limit=1)
                if not (near and near[0]["score"] >= 0.82):  # молча искать и молча не найти — как раз его жалоба
                    await self.say(t("В фонотеке нет, ищу на ютубе."))
            r = await (self.play_library(shuffle=True) if kind == "library"
                       else self.play_music(query) if kind == "music"
                       else self.play_video(query, random=kind == "video_random"))
            if r.get("ok"):
                self.brain.note(f"[Уже выполнено мгновенно, без тебя: «{text}» → {r.get('done', '')}. Не повторяй.]")
            elif r.get("error") != "cancelled":
                self.publish(kind="error", detail=t("Не нашёл «{q}»", q=query))
                await self.say(t("Не получилось включить: {e}", e=r.get("error", "")[:120]))

        spawn(go())
        return True

    async def play_library(self, query: str = "", shuffle: bool = False, count: int = 1) -> dict:
        """Play what is already downloaded. No network, no tokens, no waiting — the file is on disk."""
        tracks = media.find_local(query, limit=max(1, count)) if query else media.library()
        if not tracks:
            return {"ok": False, "error": "nothing is downloaded yet"}
        if shuffle:
            import random

            tracks = random.sample(tracks, len(tracks))
        await self.music.ensure()
        self._music_started = time.monotonic()
        await self.music.load(tracks, "replace")
        self.music.source = "" if query else t("моя фонотека")
        self.music.remember()
        await self.music.set_repeat("off")
        self.music.shuffle = shuffle
        self._pause_videos()
        first = tracks[0]
        name = f"{first['artist']} — {first['title']}" if first.get("artist") else first["title"]
        events.emit("media_play", title=name, file=first.get("file", ""), source="library")
        return {"ok": True, "title": first["title"], "artist": first.get("artist", ""), "file": first.get("file", ""),
                "queued": len(tracks) - 1, "done": t("играет {what}", what=name)}

    @staticmethod
    def _title_hit(entry: dict, query: str) -> float:
        """How much of what was asked for is in this title (0…1)."""
        words = [w for w in re.split(r"[^\w]+", query.lower().replace("ё", "е")) if len(w) > 1]
        if not words:
            return 0.0
        hay = f"{entry.get('title', '')} {entry.get('channel', '')}".lower().replace("ё", "е")
        return sum(1 for w in words if w in hay) / len(words)

    async def _ask_which_song(self, entries: list[dict], query: str) -> dict | None:
        """Several songs match — show them and ask.

        Спрашиваем не всегда: когда попадание очевидное («Flower Man» — он один),
        вопрос только мешает. Ответ — нажатием на обложку или голосом; молчание
        через две минуты означает «первый», то есть прежнее поведение.
        """
        best = self._title_hit(entries[0], query)
        second = self._title_hit(entries[1], query) if len(entries) > 1 else 0.0
        if best >= self.SURE_HIT and best - second >= self.SURE_GAP:
            return entries[0]
        if self.silent():
            # Голос выключен или идёт игра: вопрос вслух задавать некому, а
            # карточка поверх игры — худшее, что можно сделать. Берём лучшее.
            return entries[0]

        shown = entries[:3]
        opts = []
        for e in shown:
            dur = f"{e['duration'] // 60}:{e['duration'] % 60:02d}" if e.get("duration") else ""
            note = t("в фонотеке") if e.get("mine") else ""
            opts.append({"label": e["title"][:42], "icon": "media-playback-start",
                         "description": " · ".join(x for x in (e.get("channel", ""), dur, note) if x),
                         # своё — картинкой с диска, чужое — по ссылке
                         "thumb": e.get("thumb") if e.get("mine") else e.get("thumb_url", "")})
        self.publish(kind="card", card={"type": "question", "header": t("Какую включить?"),
                                        "question": t("Нашёл несколько — «{what}»", what=query),
                                        "options": opts})
        try:
            ans = await self._ask(t("Нашёл несколько. Какую включить?"),
                                  choices=[o["label"] for o in opts], free_text=True)
        finally:
            self.publish(kind="card_close")
        if ans == "deny":
            return None
        if ans in (None, "allow"):
            return shown[0]
        for e, o in zip(shown, opts, strict=True):
            if ans == o["label"]:
                return e
        # Ответили своими словами: «вторую», «последнюю», «ту, что с клипом».
        norm = ans.lower().replace("ё", "е")
        for i, word in enumerate((("перв", "1"), ("втор", "2"), ("трет", "3"))):
            if i < len(shown) and any(w in norm for w in word):
                return shown[i]
        best_by_words = max(shown, key=lambda e: self._title_hit(e, ans))
        return best_by_words if self._title_hit(best_by_words, ans) > 0 else shown[0]

    async def _ask_with_library(self, local: dict, query: str, loop) -> dict | None:
        """Похоже нашлось и на диске, и снаружи — показываем и то, и другое.

        Фонотека идёт первой: она играет мгновенно и без сети. Если сети нет
        или поиск не удался, вопроса не будет — молча берём своё.
        """
        try:
            outside = await loop.run_in_executor(None, media.find, query, "music", 2)
        except Exception as e:
            log.info("search for the choice failed (%s), playing what is downloaded", e)
            return local
        seen = local.get("url", "")
        outside = [e for e in outside if e.get("url") != seen][:2]
        if not outside:
            return local
        return await self._ask_which_song([{**local, "channel": local.get("artist", ""), "mine": True}, *outside], query)

    async def _ask_whole_list(self, yt: dict) -> bool:
        """Ссылка из микса или плейлиста: «только эту песню» (по умолчанию) или весь список?

        Кнопками в островке; тишина, игра и любой сбой означают «только эту» — безопаснее, чем
        запустить бесконечный микс, которого человек не просил."""
        if self.silent():
            return False
        what = t("микс") if "mix" in yt["kind"] else t("плейлист")
        one, whole = t("Только эту песню"), t("Весь {what}", what=what)
        self.publish(kind="card", card={"type": "question", "header": t("Ссылка из списка"),
                                        "question": t("В ссылке песня и {what}", what=what),
                                        "options": [{"label": one, "icon": "media-playback-start", "description": ""},
                                                    {"label": whole, "icon": "view-media-playlist",
                                                     "description": t("первые 50") if "mix" in yt["kind"] else ""}]})
        try:
            ans = await self._ask(t("Только эту песню или весь {what}?", what=what), choices=[one, whole], free_text=True)
        finally:
            self.publish(kind="card_close")
        return ans == whole or (isinstance(ans, str) and ans.lower().startswith(("весь", "всё", "все")))

    async def play_music(self, query: str, count: int = 1, mode: str = "replace", playlist: bool = False,
                         shuffle: bool = False) -> dict:
        """Find the song on YouTube, download its audio, play it. `count` > 1: the rest follow in the background."""
        loop = asyncio.get_running_loop()
        query = query.strip()
        if not query:
            if self.music.active:
                await self.music.resume()
                return {"ok": True, "done": t("музыка продолжается")}
            return {"ok": False, "error": "what to play?"}
        path = Path(query).expanduser()
        try:
            await self.music.ensure()
            if query.startswith(("/", "~", "./")) and path.exists():  # a file or a folder of music
                files = sorted(p for p in (path.rglob("*") if path.is_dir() else [path])
                               if p.suffix.lower() in (".mp3", ".m4a", ".opus", ".ogg", ".flac", ".wav", ".webm", ".aac"))
                if not files:
                    return {"ok": False, "error": "no music files there"}
                tracks = [media.local_track(str(p)) for p in files[:500]]
                if shuffle:
                    import random
                    random.shuffle(tracks)
                await self.music.load(tracks, mode)
                if mode == "replace":
                    self.music.source = path.name if path.is_dir() else ""
                    self.music.remember()
                    self.music.shuffle = shuffle
                self._pause_videos()
                return {"ok": True, "title": tracks[0]["title"], "queued": len(tracks) - 1,
                        "done": t("играет {what}", what=tracks[0]["title"])}
            # already in the library: starts from disk in a moment, and works with no network at all
            if not playlist and count == 1 and mode == "replace" and not media.is_url(query):
                near = media.find_local(query, limit=1)
                if near and near[0]["score"] >= 0.82:
                    # Точное попадание — играем молча. Похожее, но не точное —
                    # спрашиваем, и в варианты кладём и то, что лежит на диске,
                    # и то, что нашлось снаружи: «включи No Name» может значить
                    # и скачанное когда-то, и совсем другую песню.
                    if near[0]["score"] >= self.SURE_LOCAL or self.silent():
                        return await self.play_library(query, count=1)
                    chosen = await self._ask_with_library(near[0], query, loop)
                    if chosen is None:
                        return {"ok": True, "done": t("хорошо, не включаю")}
                    # Своё узнаём по пометке, а не по ссылке: у скачанного трека
                    # в фонотеке ссылка на ютуб как раз есть — оттуда его и взяли.
                    if chosen.get("mine"):
                        return await self.play_library(chosen["title"], count=1)
                    entries = [chosen]
                    self.music.set_loading({"title": chosen["title"], "progress": 0})
                    first = await loop.run_in_executor(None, media.cached_track, chosen)
                    if not first:
                        first = await loop.run_in_executor(None, media.stream_track, chosen)
                        spawn(self._cache_track(chosen))
                    self.music.set_loading(None)
                    await self.music.load([first], mode)
                    self.music.source = ""
                    self.music.remember()
                    self._music_started = time.monotonic()
                    self._pause_videos()
                    events.emit("media_play", title=first["title"], file=first.get("file", ""), source="choice")
                    return {"ok": True, "title": first["title"], "artist": first.get("artist", ""),
                            "done": t("играет {what}", what=first["title"])}
            yt = media.parse_youtube(query) if media.is_url(query) else None
            if yt and yt["video"] and yt["list"] and not playlist:
                playlist = await self._ask_whole_list(yt)
                if not playlist:  # «только эту»: список из ссылки выкидываем, иначе yt-dlp всё равно потянет его
                    query = f"https://www.youtube.com/watch?v={yt['video']}"
            self.music.set_loading({"title": query, "progress": 0})
            source = ""
            if playlist or (media.is_url(query) and "list=" in query):  # an album / playlist / "best of"
                source, entries = await loop.run_in_executor(None, media.playlist, query, 50 if yt and "mix" in yt["kind"] else 100)
            else:
                entries = await loop.run_in_executor(None, media.find, query, "music", max(1, min(25, count)))
                if count > 1:
                    source = query
            if not entries:
                raise RuntimeError("nothing found")
            # Одну песню и по названию — уточняем, если название подходит сразу
            # нескольким. Списки, «включи пять песен» и ссылки не трогаем.
            if count == 1 and not playlist and not shuffle and not media.is_url(query) and len(entries) > 1:
                self.music.set_loading(None)
                chosen = await self._ask_which_song(entries, query)
                if chosen is None:
                    return {"ok": True, "done": t("хорошо, не включаю")}
                entries = [chosen]
            if shuffle:
                import random
                random.shuffle(entries)
            self.music.set_loading({"title": entries[0]["title"], "progress": 0})
            # Play from YouTube right away (one yt-dlp call for the audio link, a couple of seconds) instead of
            # waiting out the whole download; the file itself lands in the library a moment later, in the
            # background, and the next time the same song is asked for it starts from disk.
            first = await loop.run_in_executor(None, media.cached_track, entries[0])
            if not first:
                first = await loop.run_in_executor(None, media.stream_track, entries[0])
                spawn(self._cache_track(entries[0]))
        except Exception as e:
            self.music.set_loading(None)
            log.warning("play failed: %s", e)
            return {"ok": False, "error": str(e)}
        self.music.set_loading(None)
        self._music_started = time.monotonic()
        await self.music.load([first], mode)
        if mode == "replace":
            self.music.source = source
            self.music.remember()
            await self.music.set_repeat("off")
        if shuffle:
            self.music.shuffle = True
        self._pause_videos()
        if len(entries) > 1:
            spawn(self._queue_rest(entries[1:]))
        name = f"{first['artist']} — {first['title']}" if first.get("artist") else first["title"]
        events.emit("media_play", title=name, file=first["file"])
        return {"ok": True, "title": first["title"], "artist": first.get("artist", ""), "file": first["file"],
                "queued": len(entries) - 1, "done": t("играет {what}", what=name)}

    def _progress(self, setter, title: str):
        """A yt-dlp progress callback (worker thread) → the island, in 5 % steps."""
        loop, last = asyncio.get_running_loop(), [-1]

        def cb(p: float) -> None:
            step = int(p * 20)
            if step != last[0]:
                last[0] = step
                loop.call_soon_threadsafe(setter, {"title": title, "progress": round(p, 2)})
        return cb

    async def _cache_track(self, entry: dict) -> None:
        """Put a song in the download queue: it plays from the stream now and lives in the library afterwards."""
        self._cache_q.append(entry)
        if self._cache_task is None or self._cache_task.done():
            self._cache_task = spawn(self._cache_worker())

    async def _cache_worker(self) -> None:
        """One download at a time, so the library fills up without stealing bandwidth from what is playing."""
        loop = asyncio.get_running_loop()
        while self._cache_q:
            entry = self._cache_q.pop(0)
            try:
                await loop.run_in_executor(None, media.download_audio, entry, None)
            except Exception as e:
                log.info("background download of %s failed: %s", entry.get("title"), e)

    async def _queue_rest(self, entries: list[dict]) -> None:
        """The rest of an album or an artist: queued from the stream (seconds), downloaded afterwards."""
        loop = asyncio.get_running_loop()
        for e in entries:
            try:
                track = await loop.run_in_executor(None, media.cached_track, e)
                if not track:
                    track = await loop.run_in_executor(None, media.stream_track, e)
                    await self._cache_track(e)
            except Exception as ex:
                log.info("skip %s: %s", e.get("title"), ex)
                continue
            if not self.music.active:  # stopped meanwhile
                return
            await self.music.load([track], "append")

    async def media_control(self, action: str, value=None) -> dict:
        """pause | resume | toggle | next | prev | restart | stop | seek SECONDS | volume 0-130 | color NAME | status"""
        m = self.music
        if action == "status":
            # window: видео в отдельном окне mpv — им телефон тоже управляет, но состояние
            # у окна спрашивают отдельно: оно живёт само по себе.
            return {"ok": True, "music": m.state(), "island_video": self.island_video,
                    "window": await asyncio.to_thread(media.window_state)}  # сокет mpv, до секунды (Р-33)
        if action == "library":  # кнопка «Моя музыка» на телефоне: файлы уже на диске, модель тут не нужна
            return await self.play_library(shuffle=True)
        if action == "volume":  # works with nothing playing too: it is the level the next song starts at
            v = max(0, min(130, int(value if value is not None else m.volume)))
            await m.set_volume(v)
            self._save_later("media", "volume", v)
            self.cfg["media"]["volume"] = v
            if not m.state():
                self.publish(settings=island.settings_snapshot(self.cfg))
            return {"ok": True, "done": t("громкость {n}%", n=v)}
        if self.island_video and action in ("pause", "resume", "toggle", "stop", "restart"):
            if action == "stop":
                self.island_video = None
                self.publish(video=None)
            else:
                self.publish(kind="video_cmd", action=action)
            return {"ok": True, "done": {"pause": t("пауза"), "resume": t("воспроизведение"), "toggle": t("пауза"),
                                         "stop": t("видео закрыто"), "restart": t("сначала")}[action]}
        if not m.alive or not m.state():
            args = ["cycle", "pause"] if action == "toggle" else ["set_property", "pause", action == "pause"]
            if action in ("pause", "resume", "toggle") and media.window_command(*args):  # the video window
                return {"ok": True, "done": t("пауза") if action == "pause" else t("воспроизведение")}
            return {"ok": False, "error": "nothing is playing"}
        if action == "seek":
            await m.seek(float(value or 0))
        elif action == "color":  # `justday player color жёлтый` — when the model got the theme wrong
            st = m.state() or {}
            if not st.get("title"):
                return {"ok": False, "error": "nothing is playing"}
            want = str(value or "").strip().lower()
            if want in ("cover", "обложка", "off", "выкл"):   # this one track keeps the colour of its artwork
                palette.put(st["title"], st.get("artist", ""), "", why=t("выбрано вручную"))
                done = t("цвет из обложки")
            elif want in ("auto", "сброс", "reset", ""):      # forget it and let the model answer again
                palette.forget(st["title"], st.get("artist", ""))
                done = t("цвет выбирается сам")
            else:
                hexa = palette.normalize(want)
                if not hexa:
                    return {"ok": False, "error": f"unknown colour {value!r}"}
                palette.put(st["title"], st.get("artist", ""), hexa, why=t("выбрано вручную"))
                done = t("цвет обновлён")
            m.refresh()
            return {"ok": True, "done": done, "color": (m.state() or {}).get("color", "")}
        elif action == "restart":
            await m.seek(0)
        elif action in ("pause", "resume", "toggle", "next", "prev", "stop"):
            await getattr(m, action)()
            if action == "toggle":
                # Ответ должен говорить, что получилось, а не как называлась кнопка:
                # телефон показывал «пауза» и когда музыка как раз поехала дальше.
                await asyncio.sleep(0.05)
                action = "pause" if (m.state() or {}).get("paused") else "resume"
        elif action == "jump":
            await m.jump(int(value or 0))
        elif action in ("repeat", "repeat_off", "repeat_all", "repeat_one"):
            await m.set_repeat(action[7:] if "_" in action else (value or "cycle"))
            await asyncio.sleep(0.05)
            action = "repeat_" + m.repeat
        elif action in ("shuffle", "shuffle_on", "shuffle_off"):
            await m.set_shuffle(None if action == "shuffle" and value in (None, "toggle") else
                                action == "shuffle_on" or value in ("on", "1", "true", True))
            action = "shuffle_on" if m.shuffle else "shuffle_off"
        else:
            return {"ok": False, "error": f"unknown action {action}"}
        return {"ok": True, "done": {"pause": t("пауза"), "resume": t("воспроизведение"), "toggle": t("пауза"),
                                     "next": t("следующий трек"), "prev": t("предыдущий трек"), "stop": t("музыка выключена"),
                                     "restart": t("сначала"), "seek": t("перемотал"), "volume": t("громкость {n}%", n=m.volume),
                                     "jump": t("переключил"), "repeat_off": t("повтор выключен"), "repeat_all": t("повтор всего"),
                                     "repeat_one": t("повтор песни"), "shuffle_on": t("вперемешку"), "shuffle_off": t("по порядку")}[action]}
