"""Управляющий сокет демона: одна строка JSON на запрос, один обработчик `_cmd_<имя>` на команду.

Вынесено из daemon.py (Р-80): `_client` был цепочкой из ~90 `elif cmd == …` на 460 строк. Теперь
`COMMANDS` — таблица «команда → метод», а `_client` только читает запрос, находит обработчик и
пишет ответ. Новая команда — это новый метод с именем `_cmd_<команда>`, больше ничего.

Сокет доступен только владельцу (0600), наружу не смотрит.
"""
from __future__ import annotations

import asyncio
import json
import logging
import subprocess
import time
from typing import ClassVar

from . import (
    clipboard,
    config,
    desktop,
    dock,
    events,
    glyphs,
    inbox,
    island,
    launcher,
    mascot,
    media,
    notifications,
    reminders,
    scenes,
    session,
    sysload,
    voiceprint,
)
from .aio import spawn
from .i18n import t

log = logging.getLogger("justday.daemon")


class CommandsMixin:
    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            req = json.loads((await reader.readline()).decode() or "{}")
            cmd = req.get("cmd")
            if cmd == "subscribe":
                await self._serve_subscriber(reader, writer)
                return
            handler = self.COMMANDS.get(cmd)
            resp = await getattr(self, handler)(req, writer) if handler else {"ok": False, "error": f"unknown command {cmd}"}
        except Exception as e:
            log.exception("control request failed")
            resp = {"ok": False, "error": repr(e)}
        try:
            writer.write((json.dumps(resp, ensure_ascii=False) + "\n").encode())
            await writer.drain()
        except ConnectionError:
            pass  # the asker gave up (timeout, Ctrl+C): nobody to answer
        writer.close()

    async def _serve_subscriber(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        """Островок подписался: первый кадр — всё состояние, дальше держим соединение, пока он жив."""
        self._subs.add(writer)
        # dock from disk cache so the first UI paint has real icon paths (not empty slots)
        try:
            dock_hello = dock.catalog_cached()
        except Exception:
            dock_hello = {}
        # Prefer last in-memory dock if cache somehow has no items (race during rebuild).
        if (not isinstance(dock_hello, dict) or not (dock_hello.get("items") or [])) and getattr(self, "_dock", None):
            dock_hello = self._dock
        elif isinstance(dock_hello, dict) and (dock_hello.get("items") or []):
            self._dock = dock_hello
        hello = {"state": self.state, "workers": self._workers_active, "settings": island.settings_snapshot(self.cfg),
                 "history": island.recent_history(), "weather": self.weather, "update": self.update_info,
                 "player": self._player_state, "video": self.island_video, "video_last": self.last_video,
                 "reminders": self._reminders_state(), "jobs": self.jobs.state(),
                 "dock": dock_hello or {}, "windows": self._windows, "focus": self._focus_now()}
        try:
            writer.write((json.dumps(hello, ensure_ascii=False) + "\n").encode())
            await writer.drain()
            await reader.read()  # hold the connection until the client goes away
        except ConnectionError:
            pass  # the island restarted while we greeted it
        self._subs.discard(writer)
        writer.close()

    async def _cmd_toggle(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        return {"ok": True, "result": await self.toggle()}

    async def _cmd_listen(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        self.stop_speaking()
        self.listen()
        return {"ok": True}

    async def _cmd_stop(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        await self.cancel_all()
        return {"ok": True}

    async def _cmd_ask(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """Просьба текстом: местная команда, вброс в идущую задачу или полный ход мозга."""
        if (local := await self.handle_local(req["text"], "cli")) is not None:
            return {"ok": True, "result": local or t("сделано")}  # «пауза» works while the brain is busy too
        if self.brain.busy and not req.get("wait"):
            await self.brain.inject(req["text"], source="cli")
            return {"ok": True, "result": "(передано в текущую задачу)"}
        if req.get("silent"):
            reply = await self.brain.ask(req["text"], source="cli")
        else:
            reply = await self.run_turn(req["text"], source="cli")
        return {"ok": True, "result": reply}

    async def _cmd_say(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        self.stop_speaking()
        await self.say(req["text"], force=True)  # `justday say` and voice previews are heard even when muted
        await self.wait_speech_done()
        return {"ok": True}

    async def _cmd_status(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        return {"ok": True, "state": self.state, "brain_busy": self.brain.busy,
                "session": self.brain.session_id, "wakeword": bool(self._wake), "silent": self.silent(),
                "scenes": [{"id": s["id"], "name": s["name"], "icon": s["icon"]}
                           for s in scenes.all_scenes()],
                "mic_source": self.mic.source, "model": self.cfg["brain"]["model"],
                # Громкость самого ассистента: телефону она нужна, чтобы
                # показать ползунок там же, где ползунок музыки.
                "volume": self.player.volume}

    async def _cmd_new_session(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        await self.brain.new_session()
        return {"ok": True}

    async def _cmd_compose(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """Keyboard shortcut: open the text field (with the selected text, if any)"""
        self.stop_speaking()
        self.publish(kind="compose", text=req.get("text", ""), context=req.get("context") or {})
        return {"ok": True}

    async def _cmd_type(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """Text typed into the Dynamic Island: same routing as speech"""
        events.emit("heard", text=req["text"], seconds=0)
        text, ctx = req["text"], req.get("context") or {}
        if ctx.get("selection"):  # "explain this", "translate this" about the text selected on screen
            text += ("\n\n[Текст, выделенный пользователем" + (f" в окне «{ctx['window']}»" if ctx.get("window") else "")
                     + f":]\n{ctx['selection'][:6000]}")
        spawn(self.handle_utterance(text, source="island"))
        return {"ok": True}

    async def _cmd_answer(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """A question card button: the option label"""
        if self._peer_is_ai(writer):
            return self._ai_cannot_approve()
        pending = self._approval is not None and not self._approval.done()
        if pending:
            self._approval.set_result(str(req.get("value", "")))
        return {"ok": pending}

    async def _cmd_confirm_message(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        return await self.confirm_message(req.get("to", ""), req.get("via", ""), req.get("text", ""))

    async def _cmd_mail_compose(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """From the brain: draft locally, confirm by voice / island, never echo the address"""
        result = await asyncio.get_running_loop().run_in_executor(
            None, self.mail.compose, req["to"], req.get("about", ""), req.get("attach") or [])
        if result is None:
            resp = {"ok": False, "error": f"адрес для «{req['to']}» неизвестен: спроси пользователя и сохрани "
                                          f"через `justday contacts set`"}
        else:
            reply, expects = result
            card = self.mail.card(reply)
            if card:
                self.publish(kind="card", card=card)
            spawn(self._speak_and_listen(reply, expects))
            resp = {"ok": True, "result": "черновик показан пользователю и ждёт его подтверждения голосом или кнопкой"}
        return resp

    async def _cmd_enroll_record(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        return await self.enroll_record(req.get("kind", "phrase"), int(req.get("index", 0)), float(req.get("seconds", 4)))

    async def _cmd_enroll_finish(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        resp = await asyncio.get_running_loop().run_in_executor(None, voiceprint.enroll_finish)
        if resp.get("ok"):
            config.set_value("audio", "silence_seconds", resp["silence_seconds"])
            if self.cfg["voiceprint"]["mode"] == "off":
                config.set_value("voiceprint", "mode", "wake")
            self.reload_settings()
        return resp

    async def _cmd_voiceprint_status(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        p = voiceprint.profile()
        return {"ok": True, "enrolled": bool(p), "created": (p or {}).get("created", ""), "threshold": (p or {}).get("threshold"),
                "wake_verifier": bool((p or {}).get("wake_verifier")), "mode": self.cfg["voiceprint"]["mode"],
                "phrases": voiceprint.phrases(), "wake_phrases": voiceprint.WAKE_PHRASES}

    async def _cmd_voiceprint_reset(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        voiceprint.reset()
        config.set_value("voiceprint", "mode", "off")
        self.reload_settings()
        return {"ok": True}

    async def _cmd_record_sample(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """Voice cloning sample: record N seconds, transcribe locally"""
        return await self.record_sample(float(req.get("seconds", 12)))

    async def _cmd_studio_done(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """A studio file is ready (or failed): card on the island; background jobs are reported"""
        return await self.studio_done(req.get("job") or {}, req.get("kind", ""), req.get("what", ""),
                                      bool(req.get("quiet")))

    async def _cmd_media_play(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """Justday play: YouTube → file → our player"""
        return await self.play_music(req.get("query", ""), int(req.get("count", 1)), req.get("mode", "replace"),
                                     bool(req.get("playlist")), bool(req.get("shuffle")))

    async def _cmd_media_video(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """Justday video: asks where (island / window / YouTube) unless told"""
        return await self.play_video(req.get("query", ""), req.get("where", ""))

    async def _cmd_volume(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """The island's slider: how loud JustDay itself is"""
        resp = {"ok": True, "volume": self.set_volume(int(req.get("value", 100)))}
        self.publish(settings=island.settings_snapshot(self.cfg))
        return resp

    async def _cmd_job_start(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """`justday job start "Обновление системы" -- jii update --json`"""
        return await self.start_job(req.get("title", ""), req["command"], req.get("cwd", ""))

    async def _cmd_job_list(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        return {"ok": True, "jobs": [dict(j, tail=self.jobs.tail(j["id"], 3)) for j in self.jobs.state()]}

    async def _cmd_job_log(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        return {"ok": True, "log": self.jobs.tail(req.get("id", ""), int(req.get("lines", 40)))}

    async def _cmd_job_stop(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        return {"ok": self.jobs.stop(req.get("id", ""))}

    async def _cmd_dictate(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """Звук с телефона: распознаём здесь и выполняем как обычную просьбу"""
        return await self.dictate(req.get("path", ""), bool(req.get("inbox")),
                                  float(req.get("created") or 0))

    async def _cmd_session(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """«я ушёл» from the island, the phone or the command line"""
        from . import session as session_mod

        loop = asyncio.get_running_loop()
        act = req.get("action", "list")
        if act == "close":
            resp = {"ok": True, **await loop.run_in_executor(None, session_mod.close, req.get("keep"))}
        elif act == "restore":
            resp = await loop.run_in_executor(None, session_mod.restore)
        elif act == "save":
            resp = {"ok": True, **await loop.run_in_executor(None, session_mod.save)}
        else:
            resp = {"ok": True, **(await loop.run_in_executor(None, session_mod.saved) or {"apps": []})}
        return resp

    async def _cmd_inbox_add(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """Сообщение с телефона: компьютера могло не быть рядом"""
        rec = inbox.add(req.get("text", ""), req.get("source", "phone"), float(req.get("created") or 0))
        events.emit("inbox_add", source=rec["source"], text=rec["text"][:200])
        self._inbox_soon()
        return {"ok": True, "id": rec["id"], "pending": len(inbox.pending())}

    async def _cmd_scene_list(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        return {"ok": True, "scenes": [{"id": s["id"], "name": s["name"], "icon": s["icon"],
                                        "phrases": s["phrases"]} for s in scenes.all_scenes()]}

    async def _cmd_scene_run(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        scene = scenes.by_id(req.get("id", "")) or scenes.match(req.get("id", ""))
        if scene is None:
            resp = {"ok": False, "error": "нет такого сценария"}
        else:
            resp = {"ok": True, "done": await self.run_scene(scene)}
        return resp

    async def _cmd_plan_list(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """Планы лежат в Obsidian; телефон и остров читают их отсюда"""
        from . import notes

        return {"ok": True, "items": notes.items(only_open=bool(req.get("open", True))),
                "file": str(notes.plans_path())}

    async def _cmd_plan_add(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        from . import notes

        return notes.add(req.get("text", ""), req.get("note", ""))

    async def _cmd_claude_terminal(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """«открыть терминал» со страницы сессий"""
        from . import workers as workers_mod

        await asyncio.get_running_loop().run_in_executor(
            None, workers_mod.open_terminal, str(req.get("id") or "") or None, None)
        return {"ok": True}

    async def _cmd_sessions(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """Что делает каждая живая сессия Claude Code"""
        from . import sessions as sessions_mod

        got = await asyncio.get_running_loop().run_in_executor(
            None, sessions_mod.live, self.cfg["brain"].get("claude_cli", "claude"))
        return {"ok": True, "sessions": got}

    async def _cmd_plan_open(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """«показать в Obsidian» со страницы планов"""
        from . import notes

        await asyncio.get_running_loop().run_in_executor(None, notes.open_in_obsidian, "")
        return {"ok": True}

    async def _cmd_plan_done(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        from . import notes

        return notes.mark_done(req.get("which", ""))

    async def _cmd_inbox_list(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        return {"ok": True, "items": inbox.recent(int(req.get("limit") or 20)),
                "pending": len(inbox.pending())}

    async def _cmd_media(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """Player buttons and `justday player ACTION`"""
        return await self.media_control(req.get("action", "status"), req.get("value"))

    async def _cmd_reminder_set(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """`justday timer 10m` and the island's own buttons"""
        at = float(req.get("at") or 0) or time.time() + float(req.get("seconds") or 0)
        rec = reminders.add(req.get("kind", "timer"), at, req.get("label", ""), req.get("repeat", ""))
        self._reschedule()
        return {"ok": True, "reminder": rec}

    async def _cmd_reminder_cancel(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        gone = reminders.cancel(req.get("which", ""))
        self._reschedule()
        return {"ok": True, "cancelled": len(gone)}

    async def _cmd_reminders(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        return {"ok": True, "reminders": self._reminders_state(), "said": self._reminders_line()}

    async def _cmd_alarm_dismiss(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """The button on the island while it rings"""
        self.dismiss_alarm(req.get("id", ""))
        return {"ok": True}

    async def _cmd_notification_open(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """A tap on a notification: its app comes forward"""
        return {"ok": True, "result": await asyncio.get_running_loop().run_in_executor(
            None, notifications.open_notification_app, req.get("app", ""), req.get("desktop", ""))}

    async def _cmd_video_state(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """The island reports its video (playing / position / closed)"""
        if req.get("closed"):
            self.remember_video(float(req.get("pos") or 0))
            self.island_video = None
            self.publish(video=None, video_last=self.last_video)
        elif self.island_video:
            self.island_video.update(playing=bool(req.get("playing")), pos=float(req.get("pos") or 0))
        return {"ok": True}

    async def _cmd_video_resume(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """Продолжить закрытый ролик с той же секунды"""
        return await self.resume_video()

    async def _cmd_video_popin(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """Окно mpv → обратно в островок, с того же места"""
        return await self.video_popin()

    async def _cmd_video_drop(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """Файл или ссылку бросили на остров"""
        return await self.play_dropped(req.get("target", ""))

    async def _cmd_video_popout(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """Island video → its own window, from the same second"""
        v = self.island_video or {}
        if v.get("file"):
            media.open_window(v["file"], float(req.get("pos") or 0), v.get("title", ""), bool(req.get("fullscreen")))
        self.remember_video(float(req.get("pos") or 0), in_window=True)
        self.island_video = None
        self.publish(video=None, video_last=self.last_video)
        return {"ok": True}

    async def _cmd_emoji(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """Сетка и поиск; ассистент ищет в том же наборе"""
        found = glyphs.search(req.get("query", ""), int(req.get("limit") or 400),
                              req.get("group", ""))
        # Ключ «emoji», а не «items»: ответы приходят островку тем же путём, что и всё
        # остальное, и общее имя столкнулось бы со списком входящих.
        return {"ok": True, "emoji": found, "groups": glyphs.load()["groups"]}

    async def _cmd_emoji_use(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """Выбрали символ: в буфер и в то окно, где курсор"""
        def _use() -> dict:
            return glyphs.use(req.get("char", ""), paste=req.get("paste", True), ready=self._focus_back,
                              app=self._last_active_app())
        return await asyncio.get_running_loop().run_in_executor(None, _use)

    async def _cmd_apps(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """Лаунчер: программы, игры, открытые окна"""
        found = await asyncio.get_running_loop().run_in_executor(
            None, lambda: launcher.items(req.get("query", ""), int(req.get("limit") or 40)))
        return {"ok": True, "apps": found}

    async def _cmd_apps_run(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        drop = [str(f) for f in (req.get("files") or [])]
        return await asyncio.get_running_loop().run_in_executor(
            None, lambda: launcher.run(req.get("kind", "app"), str(req.get("id", "")), drop))

    async def _cmd_layout(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """Островок спрашивает при подключении: публикуем только смены"""
        got = await asyncio.get_running_loop().run_in_executor(None, desktop.layout_now)
        if got:
            self._layout = got
        return {"ok": True, "layout": got}

    async def _cmd_layout_next(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """Нажали на раскладку в полосе лотка"""
        await asyncio.get_running_loop().run_in_executor(None, desktop.layout_switch)
        await asyncio.sleep(0.08)   # плазме нужен миг: спрошенная сразу раскладка ещё прежняя
        got = await asyncio.get_running_loop().run_in_executor(None, desktop.layout_now)
        if got:
            self._layout = got
            self.publish(layout=got)
        return {"ok": True, "layout": got}

    async def _cmd_notify_watch(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """Островок сам стал сервером — подслушивать больше незачем"""
        want = bool(req.get("on", True))
        if want != self._notify_watch:
            self._notify_watch = want
            if not want and self._notify_proc and self._notify_proc.returncode is None:
                self._notify_proc.kill()
            log.info("уведомления: %s", "слушаем шину" if want else "их показывает островок")
        return {"ok": True, "watch": self._notify_watch}

    async def _cmd_trash_put(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """Бросили файлы на корзину"""
        paths = [str(f) for f in (req.get("files") or []) if str(f).strip()]
        got = await asyncio.get_running_loop().run_in_executor(None, dock.trash_put, paths)
        self._trash_full = bool(got.get("trash_full"))
        self.publish(trash_full=self._trash_full)
        return got

    async def _cmd_models(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """Что сейчас держит память и сколько"""
        loop = asyncio.get_running_loop()
        free = bool(req.get("free"))
        if free:
            freed_stt = await loop.run_in_executor(None, self.stt.unload)
            await loop.run_in_executor(None, self.tts.nudge, "sleep")
        else:
            freed_stt = False
        voice = await loop.run_in_executor(None, self._voice_ping)
        return {"ok": True, "freed": free, "stt": {
            "loaded": self.stt._model is not None, "freed": freed_stt,
            "idle_minutes": round((time.monotonic() - self.stt.last_use) / 60, 1),
            "unload_after": self.cfg["stt"].get("idle_unload_minutes", 15),
        }, "tts": voice, "memory": sysload.memory(), "gpu": sysload.gpu()}

    async def _cmd_apps_catalog(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """Меню приложений: разделы, значки, закреплённое — одним куском"""
        got = await asyncio.get_running_loop().run_in_executor(None, launcher.catalog)
        return {"ok": True, "catalog": got | {"user": session.user(), "session": session.actions()}}

    async def _cmd_apps_pin(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        return launcher.pin(str(req.get("kind", "app")), str(req.get("id", "")), req.get("on"))

    async def _cmd_dock(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """Что закреплено в доке и чем ловить открытые окна"""
        got = await asyncio.get_running_loop().run_in_executor(None, dock.catalog)
        if isinstance(got, dict) and (got.get("items") or []):
            self._dock = got
        return {"ok": True, "dock": got, "windows": self._windows}

    async def _cmd_window_do(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """Поднять, свернуть или закрыть окно по его номеру"""
        what, wid = str(req.get("action", "focus")), str(req.get("id", ""))
        if what not in ("focus", "minimize", "close"):
            resp = {"ok": False, "error": f"нет такого действия: {what}"}
        else:
            await asyncio.get_running_loop().run_in_executor(None, desktop.windows, what, "", wid)
            resp = {"ok": True}
        return resp

    async def _cmd_window_thumb(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """JPEG preview of one window for dock hover cards"""
        wid = str(req.get("id", ""))
        try:
            got = await asyncio.get_running_loop().run_in_executor(
                None, desktop.window_thumb, wid)
            if not isinstance(got, dict):
                got = {"ok": False, "error": "bad thumb result"}
        except Exception as e:
            log.warning("window_thumb failed: %s", e)
            got = {"ok": False, "error": str(e)[:200]}
        return {"cmd": "window_thumb", "id": wid, **got}

    async def _cmd_dock_icons(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """Screen rects of dock icons → genie minimize target"""
        icons = req.get("icons") or {}
        if not isinstance(icons, dict):
            resp = {"ok": False, "error": "icons must be an object"}
        else:
            replace = req.get("replace", True)
            # reconfigure=True only when the island needs a fresh genie map now
            # (minimize); default None = debounced, avoids Plasma thrash.
            recon = req.get("reconfigure")
            got = await asyncio.get_running_loop().run_in_executor(
                None, lambda: desktop.publish_dock_icons(
                    icons, replace=bool(replace),
                    reconfigure=None if recon is None else bool(recon)))
            resp = got
        return resp

    async def _cmd_dock_pin(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        # Пустой id — программа активного окна (горячая клавиша Meta+P).
        ident = str(req.get("id", ""))
        kind = str(req.get("kind", "app"))
        on = req.get("on")
        loop = asyncio.get_running_loop()
        if ident:
            got = await loop.run_in_executor(None, dock.pin, kind, ident, on)
        else:
            got = await loop.run_in_executor(None, dock.pin_focused, on)
        if got.get("ok"):
            # pin/unpin returns catalog fields; keep last good dock
            if isinstance(got, dict) and got.get("items"):
                self._dock = got
            self.publish(dock=got)
        return got

    async def _cmd_tray_hide(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """Убрать значок из полосы лотка или вернуть его"""
        aliases = req.get("aliases") or []
        if not isinstance(aliases, list):
            aliases = []
        got = await asyncio.get_running_loop().run_in_executor(
            None, lambda: dock.hide_tray(str(req.get("id", "")), req.get("on"),
                                         [str(a) for a in aliases]))
        if got.get("ok"):
            self._adopt(config.load())
            self.publish(settings=island.settings_snapshot(self.cfg))
        return got

    async def _cmd_mascots(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """Какие маскоты есть и какой выбран"""
        got = await asyncio.get_running_loop().run_in_executor(None, mascot.catalog)
        return {"ok": True, "mascots": got}

    async def _cmd_folder_list(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """Что внутри закреплённой папки"""
        got = await asyncio.get_running_loop().run_in_executor(
            None, dock.folder_items, str(req.get("path", "")))
        return got

    async def _cmd_folder_open(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """Открыть файл или папку из стопки"""
        path = str(req.get("path", "")).strip()
        if path:
            await asyncio.get_running_loop().run_in_executor(
                None, lambda: subprocess.Popen(["xdg-open", path], start_new_session=True,
                                               stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL))
        return {"ok": bool(path)}

    async def _cmd_trash_empty(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """Очистить корзину: подтверждение спрашивает тот, кто просит"""
        got = await asyncio.get_running_loop().run_in_executor(None, dock.trash_empty)
        self._trash_full = bool(got.get("trash_full"))
        self.publish(trash_full=self._trash_full)
        return got

    async def _cmd_dock_arrange(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """Новый порядок после перетаскивания"""
        keys = [str(k) for k in (req.get("keys") or [])]
        got = await asyncio.get_running_loop().run_in_executor(None, dock.arrange, keys)
        if isinstance(got, dict) and (got.get("items") or []):
            self._dock = got
        self.publish(dock=got)
        return {"ok": True, "dock": got}

    async def _cmd_session_do(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """Выход, перезагрузка, выключение — опасное только с подтверждением"""
        return session.run(str(req.get("what", "")), confirm=bool(req.get("confirm")))

    async def _cmd_menu(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """Открыть меню приложений (клавиша Windows, `justday menu`)"""
        self.publish(menu="toggle" if req.get("toggle") else bool(req.get("open", True)))
        return {"ok": True}

    async def _cmd_clip_list(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        return {"ok": True, "clip": clipboard.items(int(req.get("limit") or 60),
                                                    req.get("query", "")),
                "paused": clipboard.paused(), "skipped": clipboard.skipped()["count"]}

    async def _cmd_history(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """Что сказано и что ответили, с поиском — страница истории"""
        from . import history

        return {"ok": True, "talk": history.items(req.get("query", ""), int(req.get("limit") or 80))}

    async def _cmd_clip_use(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        return await asyncio.get_running_loop().run_in_executor(
            None, lambda: clipboard.put_back(str(req.get("which", "")), paste=req.get("paste", True),
                                             ready=self._focus_back, app=self._last_active_app()))

    async def _cmd_clip_forget(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        return {"ok": clipboard.forget(str(req.get("which", "")))}

    async def _cmd_clip_wipe(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        return {"ok": True, "forgotten": clipboard.wipe()}

    async def _cmd_clip_pause(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        return {"ok": True, "paused": clipboard.pause(bool(req.get("on", True)))}

    async def _cmd_clip_pin(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        on = req.get("on")
        return {"cmd": "clip_pin", **clipboard.pin(str(req.get("which", "")),
                                                   None if on is None else bool(on))}

    async def _cmd_clip_edit(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        return {"cmd": "clip_edit", **clipboard.edit(str(req.get("which", "")),
                                                     str(req.get("text", "")))}

    async def _cmd_clip_text(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        return {"cmd": "clip_text", **clipboard.text_of(str(req.get("which", "")))}

    async def _cmd_voice_mute(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """Кнопка «молчи» на островке — то же, что `justday voice mute`"""
        # «on» здесь значит «пусть говорит», как его и посылает островок. Раньше тут стояло
        # отрицание, и кнопка работала наоборот: человек нажимал «говорить», голос
        # выключался, кнопка возвращалась в «молчит» — и так сколько ни нажимай.
        await self.set_voice(bool(req.get("on", True)))
        return {"ok": True, "muted": bool(self.cfg["tts"].get("muted"))}

    async def _cmd_panel(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """Открыть на островке нужную панель (горячая клавиша, `justday emoji`)"""
        which = str(req.get("which", ""))
        if which not in ("emoji", "clip", "mixer", "plans", "claude", "load", "apps", ""):
            resp = {"ok": False, "error": f"нет такой панели: {which}"}
        elif which == "apps":     # Alt+Space → Spotlight-поиск, не полное меню
            self.publish(menu="search")
            resp = {"ok": True, "panel": "search"}
        else:
            self.publish(panel=which)
            resp = {"ok": True, "panel": which}
        return resp

    async def _cmd_qr(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """Код ссылкой или Wi-Fi для панели «QR»; пароль сети нигде не остаётся"""
        from . import qr

        try:
            text = (qr.wifi_payload(str(req["wifi"]), str(req.get("password", "")), hidden=bool(req.get("hidden")))
                    if req.get("wifi") else str(req.get("text", "")))
            resp = {"ok": True, "qr": qr.matrix(text)}
        except ValueError:
            resp = {"ok": True, "qr": []}   # пустое поле — не ошибка, а пустой экран
        return resp

    async def _cmd_load(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """Нагрузка машины одним взглядом"""
        return {"ok": True, "load": await self.load_snapshot(), }

    async def _cmd_load_watch(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """Островок открыл монитор: присылать раз в секунду"""
        self.load_watchers = max(0, self.load_watchers + (1 if req.get("on", True) else -1))
        return {"ok": True, "watching": self.load_watchers > 0}

    async def _cmd_reload_settings(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        """After `justday config set`: hot-apply what can be"""
        return {"ok": True, "restart_needed": self.reload_settings()}

    async def _cmd_approve(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        if self._peer_is_ai(writer):
            return self._ai_cannot_approve()
        return self._settle_approval("approve")

    async def _cmd_deny(self, req: dict, writer: asyncio.StreamWriter) -> dict:
        return self._settle_approval("deny")

    @staticmethod
    def _ai_cannot_approve() -> dict:
        return {"ok": False, "error": "подтверждает только человек: кнопкой, голосом или в Telegram"}

    def _settle_approval(self, cmd: str) -> dict:
        pending = self._approval is not None and not self._approval.done()
        if pending:
            self._approval.set_result((cmd == "approve" and (self._ask_choices or ["allow"])[0]) or "deny")
        return {"ok": pending, "error": None if pending else "nothing awaits approval"}

    # «команда» → имя метода. Собирается из имён `_cmd_*` выше, чтобы список не приходилось вести руками.
    COMMANDS: ClassVar[dict[str, str]] = {k[5:]: k for k in list(locals()) if k.startswith("_cmd_")}
