"""justdayd — the voice loop: hotkey/wake word → record → transcribe → brain → speak.

Control API: newline-delimited JSON over a user-only Unix socket ($XDG_RUNTIME_DIR/justday.sock).
Never exposed on the network.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import secrets
import shutil
import signal
import subprocess
import time
from datetime import datetime
from pathlib import Path
from typing import ClassVar

import numpy as np

from . import audio, briefing, calendar_lane, config, desktop, events, fastpath, island, jobs, mail, media, namespot, notifications, numerals, offline, palette, reminders, voiceprint, workers
from . import brain as brain_mod
from . import tts as tts_mod
from . import weather as weather_mod
from .aio import spawn
from .brain import Brain
from .i18n import t
from .stt import STT
from .tts import TTS, normalize, split_sentences

log = logging.getLogger("justday.daemon")

# Bare acknowledgements ("Готово.", "Открыл терминал.") are replaced by the "done" earcon.
ACK = re.compile(r"^\W*(?:(?:готово|окей|ок|хорошо|done|ok)\W+)?(готово|сделано|сделал|есть|окей|ок|хорошо|выполнено|принято|done|"
                 r"(открыл|запустил|включил|закрыл|свернул|переключил|поставил|выключил|включаю|ставлю|запускаю|"
                 r"включено|играет|играю|вот|now playing|playing)[\w\s«»\"'.,:—–-]{0,70})\W*$", re.I)
# «Выпало "…". Включаю.» — an announcement of a start is not an answer either, wherever the verb sits
ACK_TAIL = re.compile(r"(включаю|ставлю|запускаю|показываю|ищу|сейчас будет|playing|now playing)\s*[.!…]*$", re.I)
STOP_WORDS = re.compile(r"\b(стоп|хватит|отмена|отмени|отменяй|замолчи|заткнись|stop|cancel|never ?mind|shut up|be quiet)\b", re.I)
YES = re.compile(r"\b(да|давай|разрешаю|разреши|подтверждаю|конечно|ок|окей|можно|делай|yes|yeah|sure|ok|okay|allow|go ahead|do it)\b", re.I)
NO = re.compile(r"\b(нет|не надо|отмена|отклон\w*|запрещаю|стоп|no|nope|don'?t|deny|cancel)\b", re.I)


SIDE_AFTER_S = 5.0   # a tool call this old means an injected request would sit and wait: use the side session


class Daemon:
    def __init__(self) -> None:
        self.cfg = config.load()
        a = self.cfg["audio"]
        self.mic = audio.Microphone(a["input"])
        self.player = audio.Player(a["output"], int(a.get("volume", 100)))
        self._saves: dict[tuple[str, str], asyncio.TimerHandle] = {}  # sliders: write the config once, not per pixel
        self._colors: asyncio.Task | None = None   # one background question about track colours at a time
        self._colors_after = 0.0                   # ... and a pause before asking again after a failure
        self.recorder = audio.UtteranceRecorder(self.mic, a["silence_seconds"], a["no_speech_timeout_seconds"],
                                                a["max_utterance_seconds"])
        self.stt = STT(self.cfg["stt"])
        self.tts = TTS(self.cfg["tts"])
        self.brain = Brain(self.cfg, on_text=self._on_brain_text, approver=self._approve, asker=self._answer_questions)
        self.side: Brain | None = None             # a second session, for what must not wait for the first one
        self._side_close: asyncio.TimerHandle | None = None
        self.jobs = jobs.Jobs(on_change=lambda: self.publish(jobs=self.jobs.state()), on_done=self._job_done)
        self._subs: set[asyncio.StreamWriter] = set()
        self._notify_proc: asyncio.subprocess.Process | None = None
        self._state = "idle"
        self._workers_active = 0
        self._listen_cancel: asyncio.Event | None = None
        self._listen_task: asyncio.Task | None = None
        self._speech_q: asyncio.Queue[str | None] = asyncio.Queue()
        self._speech_gen = 0
        self._approval: asyncio.Future | None = None
        self._ask_choices: list[str] = []
        self._ask_free = False
        self._preapproved_until = 0.0  # a message draft the user approved: its "send" needs no second question
        self._last_mic_use = time.monotonic()
        self._notify_id = 0
        self._wake = None
        self._wake_cooldown = 0.0
        self._names: list[str] = []  # spellings of the assistant's names, for trimming them off a woken phrase
        self._quiet_until = 0.0  # the assistant's own voice may still echo in the room
        self._event_queue: asyncio.Queue[str] = asyncio.Queue()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._spoken = 0
        self._discard_recording = False
        self._last_toggle = 0.0
        self._holding = False
        self._voice_warned = False
        self._music_started = 0.0   # music that just started speaks for itself: the reply after it stays silent
        self._offline_note = 0.0    # when the user was last told that the cloud is out
        self._cloud_down_until = 0.0  # the brain just failed: five minutes of going local without the wait
        self._cache_q: list[dict] = []      # songs playing from the stream, waiting to be downloaded
        self._cache_task: asyncio.Task | None = None
        self._reminder_task: asyncio.Task | None = None
        self._ringing = ""                  # the reminder currently making noise
        self._activation = "button"
        self._cancel_gen = 0  # bumped by cancel_all: anything started before it is dropped
        self.weather: dict | None = None
        self.update_info: dict | None = None
        self._weather_city = ""
        self.mail = mail.MailAssistant()
        self.stt.vocabulary = island.vocabulary(self.cfg)
        # our own music player (background mpv) and the video playing inside the island, if any
        self.music = media.MusicPlayer(self._on_player, int(self.cfg["media"]["volume"]))
        self._player_state: dict | None = None
        self.island_video: dict | None = None

    # ---------------- live status (overlay) ----------------
    @property
    def state(self) -> str:
        return self._state

    @state.setter
    def state(self, value: str) -> None:
        if value != self._state:
            if self._state == "speaking":
                self._quiet_until = time.monotonic() + 0.8
            self._state = value
            self.publish(state=value)
            if self.music.alive and self.cfg["media"]["duck"]:  # music steps back while we talk
                spawn(self.music.duck(value in ("listening", "speaking", "approval")))

    def publish(self, **msg) -> None:
        """Push a status update to every `subscribe` client (the on-screen indicator). Loop thread only."""
        if not self._subs:
            return
        line = (json.dumps(msg, ensure_ascii=False) + "\n").encode()
        for w in list(self._subs):
            if w.is_closing():
                self._subs.discard(w)
                continue
            w.write(line)

    def _on_event(self, kind: str, data: dict) -> None:
        """Journal event → Dynamic Island message (full texts, icons, cards)."""
        if kind == "turn_done":
            self._preapproved_until = 0.0  # an approved draft covers only the task it was made for
        if kind == "tool":  # one line, always: a pasted script must not stretch the island
            msg = {"kind": "tool", "detail": brain_mod.one_line(data.get("label") or data.get("desc", "")),
                   "icon": island.tool_icon(data.get("name", ""), data.get("input", ""))}
        elif kind == "fast":
            msg = {"kind": "fast", "detail": brain_mod.one_line(data.get("desc", "")), "icon": fastpath.last_icon}
        elif kind in ("heard", "say", "draft"):
            msg = {"kind": kind, "detail": data.get("text", "")}
        elif kind == "approval_request":
            msg = {"kind": "approval", "detail": data.get("desc", ""), "reason": data.get("reason", "")}
        elif kind in ("approval_result", "cancel", "turn_done", "listen_empty", "listen_cancelled"):
            msg = {"kind": kind}
        elif kind == "worker_start":
            msg = {"kind": "tool", "detail": t("Клод взялся за задачу"), "icon": "applications-development"}
        elif kind in ("brain_error", "turn_failed", "mail_error"):
            msg = {"kind": "error", "detail": t("Почта недоступна") if kind == "mail_error" else t("Ошибка мозга")}
        else:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None
        if loop is self._loop:
            self.publish(**msg)
        elif self._loop:
            self._loop.call_soon_threadsafe(lambda: self.publish(**msg))

    # ---------------- notifications ----------------
    def notify(self, body: str, icon: str = "audio-input-microphone", urgent: bool = False) -> None:
        if not self.cfg["ui"]["notifications"]:
            return
        cmd = ["notify-send", "-a", "JustDay", "-i", icon, "-p", "-t", "4000", "-h", "boolean:transient:true"]
        if self._notify_id:
            cmd += ["-r", str(self._notify_id)]
        if urgent:
            cmd += ["-u", "critical"]
        try:
            out = subprocess.run([*cmd, "JustDay", body[:300]], capture_output=True, text=True, timeout=5).stdout
            self._notify_id = int(out.strip() or 0)
        except Exception:
            pass

    # ---------------- speech output ----------------
    def silent(self) -> str:
        """Why the answer is only shown, not spoken: "off", "game", or "" when the voice is on."""
        t = self.cfg["tts"]
        if t["engine"] == "none" or t.get("muted"):
            return "off"
        if t.get("mute_in_games", True) and desktop.running_game():
            return "game"
        return ""

    async def morning(self) -> str:
        """The first «привет» of the day: the day itself, said before the model is even woken."""
        self.state = "thinking"
        loop = asyncio.get_running_loop()
        city = self.cfg["island"]["city"]
        if self.weather is None and city:  # the island polls it every 15 min, but not before the first hello
            try:
                self.weather = await loop.run_in_executor(None, weather_mod.fetch_weather, city)
            except Exception as e:
                log.info("briefing without weather: %s", type(e).__name__)
        try:
            text = await loop.run_in_executor(None, briefing.compose, self.cfg, self.weather)
        except Exception:
            log.exception("briefing failed")
            self.state = "idle"
            return ""
        events.emit("briefing", text=text)
        self.brain.note(f"[Утренний брифинг уже сказан: «{text}» Не повторяй его.]")
        await self.say(text)
        self.state = "thinking" if self.brain.busy else "idle"
        return text

    async def session_switch(self, what: str) -> str:
        """«Я ушёл» — remember the open applications and ask them to close; «я вернулся» — open them again.

        Closing is asked about first: the list is what the user will get back, and a window that has
        unsaved work in it is better mentioned before it is told to close."""
        from . import session

        loop = asyncio.get_running_loop()
        if what == "restore":
            r = await loop.run_in_executor(None, session.restore)
            if not r.get("ok"):
                said = t("Нечего возвращать — я ничего не закрывал.")
            else:
                said = (t("Вернул: {what}.", what=", ".join(r["started"])) if r["started"]
                        else t("Всё уже открыто."))
            await self.say(said)
            return said
        apps = await loop.run_in_executor(None, session.save)
        names = [a["name"] for a in apps["apps"]]
        if not names:
            said = t("Нечего закрывать.")
            await self.say(said)
            return said
        if not await self._approve(t("Закрыть: {what}", what=", ".join(names)), t("Верну по «я вернулся»")):
            return t("Отменено")
        r = await loop.run_in_executor(None, session.close, None)
        said = t("Закрыл: {what}. Скажите «я вернулся» — открою заново.", what=", ".join(r["closed"]) or "—")
        if r["still_open"]:
            said += " " + t("Не закрылись: {what}.", what=", ".join(r["still_open"]))
        await self.say(said)
        return said

    async def set_voice(self, on: bool) -> None:
        """«молчи» / «говори»: only the voice stops — the island still shows every answer."""
        config.set_value("tts", "muted", not on)
        self.cfg["tts"]["muted"] = not on
        said = t("голос включён") if on else t("голос выключен")
        events.emit("fast", text=said, desc=said)
        self.publish(detail=said, kind="tool")
        self.brain.note(f"[Уже выполнено: {said}. Не повторяй.]")
        if on:
            await self.say(said)
        self.state = "thinking" if self.brain.busy else "idle"

    async def _on_brain_text(self, text: str, force: bool = False) -> None:
        if not force and (why := self.silent()):
            events.emit("say_suppressed", text=text[:200], reason=why)
            return
        if ACK.match(text.strip()) and len(text) < 60:
            events.emit("ack_suppressed", text=text)
            return
        if ACK_TAIL.search(text.strip()) and len(text) < 140:
            events.emit("ack_suppressed", text=text)
            return
        # «включи…» is answered by the music itself. Whatever the model wants to add about the track
        # («это трек Тоби Фокса, включаю») answers nothing, so it is not spoken — unless it asks
        # something or is long enough to be a real answer.
        if time.monotonic() - self._music_started < 40 and "?" not in text and len(text) < 220:
            events.emit("ack_suppressed", text=text)
            return
        self._spoken += 1
        lang = self.cfg["user"].get("language", "ru")
        self.tts.cfg["lang"] = lang
        for s in split_sentences(normalize(text, lang, tts_mod.latin_mode(self.tts.cfg),
                                           bool(self.tts.cfg.get("numbers", True)))):
            self._speech_q.put_nowait(s)

    async def say(self, text: str, force: bool = False) -> None:
        await self._on_brain_text(text, force)

    def stop_speaking(self) -> None:
        self._speech_gen += 1
        while not self._speech_q.empty():
            self._speech_q.get_nowait()
        self.player.stop()

    async def _speech_worker(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            sentence = await self._speech_q.get()
            gen = self._speech_gen
            try:
                engine = self.tts.cfg["engine"]
                if engine == "elevenlabs" and await self._speak_stream(sentence, gen, "elevenlabs"):
                    continue
                if engine in ("qwen", "elevenlabs") and await self._speak_stream(sentence, gen, "qwen"):
                    continue
                pcm = await loop.run_in_executor(None, self.tts.synth, sentence)
                if gen != self._speech_gen or not len(pcm):
                    continue
                self.state = "speaking"
                await self.player.play(pcm, self.tts.rate)
                if self.state == "speaking":
                    self.state = "thinking" if self.brain.busy else "idle"
            except Exception:
                log.exception("speech failed")

    async def _speak_stream(self, sentence: str, gen: int, engine: str) -> bool:
        """Stream one sentence from a voice that generates as it speaks (the local neural service or ElevenLabs).

        False = this voice is unavailable, and the caller falls back to the next one."""
        if engine == "elevenlabs":
            stream, rate, native = self.tts.eleven_stream(sentence), self.tts.ELEVEN_RATE, max(0.7, min(1.2, self.tts.speed))
        else:
            stream, rate, native = self.tts.stream(sentence), self.tts.NEURAL_RATE, 1.0
        stretch = audio.Stretcher(self.tts.speed / native, rate)
        try:
            first = await stream.__anext__()
        except StopAsyncIteration:
            return True
        except OSError as e:
            if not self._voice_warned:
                self._voice_warned = True
                log.warning("%s voice unavailable (%s), falling back", engine, e)
            return False
        self._voice_warned = False
        if gen != self._speech_gen:
            await stream.aclose()
            return True

        # jitter buffer: start playing only with ~0.4 s in hand, so a busy GPU doesn't tear the voice apart
        head = [first]
        buffered = len(first)
        try:
            while buffered < rate * 2 * 0.4:
                data = await stream.__anext__()
                head.append(data)
                buffered += len(data)
        except StopAsyncIteration:
            pass
        except OSError:
            log.warning("%s stream broke while buffering", engine)

        def faster(data: bytes) -> bytes:
            """The voice speaks at its own pace; this is the pace the user set."""
            if stretch.passthrough:
                return data
            return stretch.feed(np.frombuffer(data, dtype=np.int16)).tobytes()

        async def chunks():
            for data in head:
                out = faster(data)
                if out:
                    yield out
            async for data in stream:
                if gen != self._speech_gen:
                    break
                out = faster(data)
                if out:
                    yield out
            rest = stretch.drain()
            if rest.size:
                yield rest.tobytes()

        self.state = "speaking"
        try:
            await self.player.play_stream(chunks(), rate)
        except OSError:
            log.warning("%s stream broke", engine)
        if self.state == "speaking":
            self.state = "thinking" if self.brain.busy else "idle"
        return True

    async def wait_speech_done(self) -> None:
        while not self._speech_q.empty() or self.player.playing:
            await asyncio.sleep(0.1)

    async def earcon(self, kind: str) -> None:
        if self.cfg["audio"]["earcons"]:
            await self.player.play(audio.earcon(kind), 48000)

    # ---------------- listening ----------------
    async def toggle(self, source: str = "button") -> str:
        """Hotkey handler. Tap (auto-stop on silence, tap again to finish), double tap (cancel all) and hold:
        a held key auto-repeats, so toggles arriving <1 s apart mean "still held"; when they stop,
        the key was released and the utterance ends."""
        now = time.monotonic()
        gap, self._last_toggle = now - self._last_toggle, now
        double = self.cfg["audio"]["double_tap_seconds"]
        # double press = cancel everything. Auto-repeat of a held key starts only after the repeat delay (~600 ms)
        # and then comes every ~40 ms, so a 60–350 ms gap is a real second press.
        if double and 0.06 < gap < double and not self._holding:
            self._last_toggle = 0.0
            await self.cancel_all()
            return "cancel"
        if self.state == "listening" and self._listen_cancel:
            if gap < 1.0:
                if not self._holding:
                    self._holding = True
                    spawn(self._watch_release())
                return "holding"
            self._listen_cancel.set()  # second tap: finish the utterance now
            return "stop-listening"
        self._holding = False
        self._activation = source
        self.stop_speaking()
        if not self.mic_on():  # keyboard mode: the talk key opens the text field
            self.publish(kind="compose")
            return "compose"
        self.listen()
        return "listening"

    async def _watch_release(self) -> None:
        while self._holding and self.state == "listening":
            await asyncio.sleep(0.1)
            if time.monotonic() - self._last_toggle > 0.4:  # auto-repeat stopped → key released
                self._holding = False
                if self._listen_cancel:
                    self._listen_cancel.set()

    def mic_on(self) -> bool:
        return self.cfg["audio"].get("microphone", True)

    def listen(self, followup: bool = False, prefill=None) -> bool:
        if not self.mic_on():  # no microphone: typed answers only (the island shows a reply field)
            if not followup and prefill is None:
                self.publish(kind="compose")
            return False
        if self._listen_task and not self._listen_task.done():
            return False
        self._listen_task = spawn(self._listen_once(followup, prefill))
        return True

    def _wake_by_name(self, prefill, take_tail) -> None:
        """«Джарвис, …» was heard. `prefill` is set when a command follows the name in the same breath."""
        if self.state in ("listening", "transcribing", "speaking") or not self.listen(prefill=prefill):
            take_tail()
            return
        self._holding = False
        self._activation = "wake"

    async def _listen_once(self, followup: bool, prefill=None) -> None:
        self.mic.start()
        self._last_mic_use = time.monotonic()
        self.state = "listening"
        self._listen_cancel = asyncio.Event()
        self._discard_recording = False
        if not followup and prefill is None:  # mid-phrase after the name: a beep would land in the recording
            await self.earcon("listen")
        events.emit("listen_start", followup=followup)
        rec = self.recorder
        if followup:
            rec = audio.UtteranceRecorder(self.mic, rec.silence_s, self.cfg["audio"]["followup_seconds"], rec.max_s)
        loop = asyncio.get_running_loop()

        def level(frame: np.ndarray) -> None:
            rms = float(np.sqrt((frame.astype(np.float32) ** 2).mean())) / 32768.0
            db = 20 * np.log10(rms + 1e-9)  # −50 dBFS (room) … −20 dBFS (loud speech) → 0…1, like a VU meter
            loop.call_soon_threadsafe(lambda: self.publish(level=round(min(1.0, max(0.0, (db + 50) / 30)), 3)))

        self.mic.subscribe(level)
        try:
            pcm = await rec.record(self._listen_cancel, prefill)
        finally:
            self.mic.unsubscribe(level)
        self._last_mic_use = time.monotonic()
        after = "thinking" if self.brain.busy else "idle"
        if self._discard_recording:
            events.emit("listen_cancelled")
            self.state = after
            return
        if pcm is None or len(pcm) < audio.RATE * 0.3:
            events.emit("listen_empty")
            self.state = after
            return
        mode = self.cfg["voiceprint"]["mode"]
        if mode == "always" or (mode == "wake" and (followup or self._activation == "wake")):
            prof = voiceprint.profile()
            if prof:
                sc = await asyncio.get_running_loop().run_in_executor(None, voiceprint.score, pcm)
                if sc is not None and sc < prof["threshold"]:
                    events.emit("listen_rejected", score=round(sc, 2))
                    self.publish(kind="error", detail=t("Голос не узнан"))
                    self.state = after
                    return
        self.state = "transcribing"
        gen = self._cancel_gen
        text = await asyncio.get_running_loop().run_in_executor(None, self.stt.transcribe, pcm)
        if gen != self._cancel_gen:  # cancelled while transcribing: forget what was said
            events.emit("listen_cancelled", text=text)
            return
        self.state = "thinking" if self.brain.busy else "idle"
        if self._activation == "wake" and self._names:
            text = namespot.strip_name(text, self._names)
        events.emit("heard", text=text, seconds=round(len(pcm) / audio.RATE, 1))
        if not text:
            await self.earcon("error")
            return
        await self.handle_utterance(text)

    async def handle_local(self, text: str, source: str = "voice") -> str | None:
        """Everything JustDay can do without the cloud, in the order it tries them: the morning briefing,
        the voice switch, the player, timers, instant desktop commands, the calendar, the mail.

        Returns what was done (sometimes an empty string — it has already been said), or None when this
        is a request only the brain can answer. Voice and keyboard take exactly the same road."""
        if briefing.wanted(text) and briefing.due() and (said := await self.morning()):
            return said
        if (on := fastpath.voice_switch(text)) is not None:
            await self.set_voice(on)
            return t("голос включён") if on else t("голос выключен")
        if (what := fastpath.session_switch(text)) is not None:
            return await self.session_switch(what)
        if await self.media_fast(text) or await self.reminder_fast(text):
            return ""
        gen = self._cancel_gen
        done = await asyncio.get_running_loop().run_in_executor(None, fastpath.try_handle, text)
        if gen != self._cancel_gen:
            return ""
        if done:
            events.emit("fast", text=text, desc=done)
            self.publish(detail=done, kind="tool")
            self.brain.note(f"[Уже выполнено мгновенно, без тебя: «{text}» → {done}. Не повторяй это действие.]")
            self.state = "thinking" if self.brain.busy else "idle"
            await self.earcon("done")
            return done
        if calendar_lane.CAL_WORDS.search(text):
            try:
                cal = await asyncio.get_running_loop().run_in_executor(None, calendar_lane.handle, text)
            except Exception as e:  # offline, or a calendar that moved
                log.warning("calendar failed: %s", e)
                cal = (t("Не получилось открыть календарь."), None)
            if cal and gen == self._cancel_gen:
                reply, card = cal
                if card:
                    self.publish(kind="card", card=card)
                await self.say(reply)
                return reply
        if self.cfg["mail"]["address"] and self.mail.wants(text) and (await self.handle_mail(text) or gen != self._cancel_gen):
            return ""
        return None

    async def handle_utterance(self, text: str, source: str = "voice") -> str | None:
        if self._approval and not self._approval.done():
            ans = self._match_answer(text)
            if ans is not None:
                self._approval.set_result(ans)
                return
        if STOP_WORDS.search(text) and len(text.split()) <= 6:
            if self.music.playing and not self.brain.busy and self._speech_q.empty():  # "стоп" over music: the music
                await self.music.pause()
                return
            await self.cancel_all()
            return
        if (local := await self.handle_local(text, source)) is not None:
            return local
        if self.brain.busy:
            if self.brain.waiting_on_tool() >= SIDE_AFTER_S:
                # the main session sits inside a long command (an upgrade, a build): an injected message would
                # wait for it to end, so a second session takes this one now
                spawn(self.run_side_turn(text, source))
            else:
                await self.brain.inject(text, source)  # it reads it at its next step, in a second or two
            return
        spawn(self.run_turn(text, source))

    async def run_side_turn(self, text: str, source: str = "voice") -> None:
        """The same assistant — persona, tools, memory — in a second session, told what the first is busy with.
        It is started on demand and closed after five idle minutes."""
        if self._side_close:
            self._side_close.cancel()
        if self.side is None:
            self.side = Brain(self.cfg, on_text=self._on_brain_text, approver=self._approve,
                              asker=self._answer_questions, persist=False)
        if self.side.busy:
            await self.side.inject(text, source)
            return
        busy_with = brain_mod.one_line(self.brain.request, 160) if self.brain.request else ""
        context = (f"[Параллельно. Основная сессия сейчас занята просьбой «{busy_with}» и ждёт долгую команду"
                   + (f" ({self.brain.tool_label})" if self.brain.tool_label else "") +
                   ". Ты — вторая сессия того же ассистента: те же инструменты, память и характер. Выполни только "
                   "эту новую просьбу; основную задачу не трогай и не повторяй. Если просьба о ней («как там "
                   "обновление?») — ответь по тому, что видно (`justday job list`, процессы), ничего не перезапуская.]\n")
        self.state = "thinking"
        spoken_before, gen = self._spoken, self._cancel_gen
        try:
            await self.side.ask(context + text, source=source)
        except Exception as e:
            events.emit("turn_failed", error=repr(e), lane="side")
            if gen == self._cancel_gen:
                await self.say(t("Не получилось связаться с мозгом. Подробности в логе."))
        if gen != self._cancel_gen:
            return
        await self.wait_speech_done()
        self.state = "thinking" if self.brain.busy else "idle"
        if self._spoken == spoken_before:
            await self.earcon("done")
        self._side_close = asyncio.get_running_loop().call_later(300, lambda: spawn(self._close_side()))

    async def _close_side(self) -> None:
        side, self.side = self.side, None
        if side and not side.busy:
            await side.stop()
        elif side:
            self.side = side   # busy again after all: keep it

    async def start_job(self, title: str, command: str, cwd: str = "") -> dict:
        """Wrapping a command in a job must not be a way around the approval rules: the command inside gets
        the same check a direct call would, and a risky one waits for the person's «да» first."""
        from . import providers

        if providers.risky("Bash", {"command": command}, Brain._ask_rules()):
            desc = f"{t('Фоновая задача')} «{title}»: {command[:300]}"
            events.emit("approval_request", tool="Bash", desc=desc, reason="background job")
            ok = await self._approve(desc, "", True)
            events.emit("approval_result", tool="Bash", allowed=ok)
            if not ok:
                return {"ok": False, "error": "the user declined this command; do not run it another way"}
        job = await self.jobs.start(title, command, cwd)
        return {"ok": True, "id": job["id"], "log": job["log"]}

    def _job_done(self, job: dict) -> None:
        """A background job ended: a sound now, and the brain reports it in its own words when it is free."""
        spawn(self.earcon("done" if job["state"] == "done" else "error"))
        if job["state"] == "stopped":
            return  # the person stopped it: nothing to report
        took = numerals.duration(int(job["ended"] - job["started"]))
        how = t("закончилась успешно") if job["state"] == "done" else t("закончилась с ошибкой (код {n})", n=job["code"])
        self._event_queue.put_nowait(
            f"[Событие JustDay] Фоновая задача «{job['title']}» {how} за {took}. Команда: `{job['command'][:300]}`.\n"
            f"Последние строки журнала:\n{self.jobs.tail(job['id'])}\n"
            f"Коротко, одной-двумя фразами, доложи пользователю итог; если ошибка — в чём она и что предлагаешь. "
            f"Весь журнал: `justday job log {job['id']}`.")

    async def _record_fixed(self, seconds: float) -> np.ndarray:
        self.stop_speaking()
        self.mic.start()
        frames: list[np.ndarray] = []
        self.mic.subscribe(frames.append)
        self.state = "listening"
        await self.earcon("listen")
        await asyncio.sleep(max(1.5, min(30.0, seconds)))
        self.mic.unsubscribe(frames.append)
        self.state = "idle"
        return np.concatenate(frames) if frames else np.zeros(0, dtype=np.int16)

    async def enroll_record(self, kind: str, index: int, seconds: float) -> dict:
        """One enrollment clip: "Hey Jarvis" (kind=wake) or a command phrase (kind=phrase)."""
        pcm = await self._record_fixed(seconds)
        await self.earcon("done")
        level = float(voiceprint.rms_frames(pcm).max()) if len(pcm) else 0.0
        if level < 0.02:
            return {"ok": False, "error": t("Слишком тихо — говорите ближе к микрофону"), "level": round(level, 3)}
        clip = voiceprint.trim_silence(pcm)
        voiceprint.save_wav(voiceprint.DIR / f"{kind}_{index}.wav", pcm)
        text = ""
        if kind == "phrase":
            text = await asyncio.get_running_loop().run_in_executor(None, self.stt.transcribe, pcm)
        return {"ok": True, "text": text, "level": round(level, 3), "seconds": round(len(clip) / audio.RATE, 1)}

    def transcribe_file(self, path: str) -> str:
        """Звук, записанный где-то ещё (телефон), — теми же ушами, что и микрофон на столе.

        Распознавание всё равно происходит здесь: с телефона приходит файл, а не текст,
        и дальше он идёт той же дорогой, что и сказанное вслух у компьютера."""
        if not path or not os.path.exists(path):
            raise FileNotFoundError(path)
        raw = subprocess.run(
            ["ffmpeg", "-nostdin", "-loglevel", "error", "-i", path,
             "-ac", "1", "-ar", str(audio.RATE), "-f", "s16le", "-"],
            capture_output=True, timeout=120).stdout
        if not raw:
            return ""
        return self.stt.transcribe(np.frombuffer(raw, dtype=np.int16))

    async def dictate(self, path: str) -> dict:
        """Надиктованное с телефона: распознать здесь и выполнить, как сказанное вслух."""
        loop = asyncio.get_running_loop()
        self.state = "transcribing"
        try:
            text = await loop.run_in_executor(None, self.transcribe_file, path)
        finally:
            self.state = "thinking" if self.brain.busy else "idle"
        if not text:
            events.emit("dictate_empty")
            return {"ok": False, "error": t("Не расслышал.")}
        events.emit("heard", text=text, source="phone")
        self.publish(kind="heard", detail=text)
        local = await self.handle_local(text, "phone")
        reply = local if local is not None else await self.run_turn(text, source="phone")
        return {"ok": True, "text": text, "result": reply or t("сделано")}

    async def record_sample(self, seconds: float) -> dict:
        import wave

        self.stop_speaking()
        self.mic.start()
        frames: list[np.ndarray] = []
        self.mic.subscribe(frames.append)
        self.state = "listening"
        await self.earcon("listen")
        await asyncio.sleep(max(3.0, min(30.0, seconds)))
        self.mic.unsubscribe(frames.append)
        self.state = "idle"
        await self.earcon("done")
        pcm = np.concatenate(frames) if frames else np.zeros(0, dtype=np.int16)
        path = config.DATA_DIR / "voices" / "sample.wav"
        path.parent.mkdir(parents=True, exist_ok=True)
        with wave.open(str(path), "wb") as w:
            w.setnchannels(1)
            w.setsampwidth(2)
            w.setframerate(audio.RATE)
            w.writeframes(pcm.astype(np.int16).tobytes())
        text = await asyncio.get_running_loop().run_in_executor(None, self.stt.transcribe, pcm)
        return {"ok": bool(text), "path": str(path), "text": text, "seconds": round(len(pcm) / audio.RATE, 1)}

    async def _speak_and_listen(self, text: str, expects: bool) -> None:
        await self.say(text)
        await self.wait_speech_done()
        if expects and self.cfg["audio"]["followup_seconds"] > 0:
            self.listen(followup=True)

    def reload_settings(self) -> list[str]:
        """Apply config changes without a restart where possible; returns the sections that still need one."""
        old, new = self.cfg, config.load()
        self.cfg = new
        restart: list[str] = []
        a = new["audio"]
        self.tts.cfg = new["tts"]
        self.recorder.silence_s = a["silence_seconds"]
        self.recorder.no_speech_timeout_s = a["no_speech_timeout_seconds"]
        self.recorder.max_s = a["max_utterance_seconds"]
        if a.get("microphone", True) != old["audio"].get("microphone", True):
            if not a.get("microphone", True):
                if self._listen_cancel:
                    self._listen_cancel.set()
                self.mic.stop()
            elif self._wake:
                self.mic.start()
            elif new["wakeword"]["enabled"]:
                restart.append("wakeword")  # it was never set up without a microphone
        if a["input"] != old["audio"]["input"] and a.get("microphone", True):
            self.mic.stop()  # listen() starts it again on the new device
            self.mic.source = audio.find_node(a["input"]) if a["input"] else None
            if self._wake:
                self.mic.start()
        if a["output"] != old["audio"]["output"]:
            self.player.sink = audio.find_node(a["output"], "sinks") if a["output"] else None
        self.player.volume = int(a.get("volume", 100))
        if new["media"]["volume"] != old["media"]["volume"]:
            spawn(self.music.set_volume(int(new["media"]["volume"])))
        # a new character or name is a new system prompt: the conversation goes on under it once the brain is free
        if (new["persona"] != old["persona"] or
                {k: new["user"].get(k) for k in ("assistant_name", "address_as", "assistant_aliases")} !=
                {k: old["user"].get(k) for k in ("assistant_name", "address_as", "assistant_aliases")}):
            self.brain.cfg["persona"] = new["persona"]
            self.brain.cfg["user"] = new["user"]
            spawn(self._reconnect_brain())
        self.brain.cfg["user"] = new["user"]
        self.stt.vocabulary = island.vocabulary(new)
        restart += [s for s in ("brain", "stt", "wakeword", "local_llm") if new[s] != old[s]]
        if new["user"].get("language") != old["user"].get("language"):
            restart.append("language")
        names = lambda c: (c["user"]["assistant_name"], c["user"].get("assistant_aliases"))  # noqa: E731
        if self._names and names(new) != names(old):  # the name spotter was built with the old names
            restart.append("wakeword")
        self.publish(settings=island.settings_snapshot(new))
        events.emit("settings_reloaded", restart_needed=restart)
        return restart

    def _cancelled_since(self, gen: int) -> bool:
        return gen != self._cancel_gen

    async def handle_mail(self, text: str) -> bool:
        """Private lane: mail is read, summarised and written by the local model; the cloud brain never sees it."""
        prev = self.state
        prev_gen = self._cancel_gen
        self.state = "thinking"
        self.publish(detail=t("Почта · локально"), kind="tool")
        try:
            result = await asyncio.get_running_loop().run_in_executor(None, self.mail.handle, text)
        except Exception as e:
            log.exception("mail lane failed")
            events.emit("mail_error", error=type(e).__name__)
            result = (t("Локальная модель для почты не отвечает."), False)
        if result is None:
            self.state = prev
            return False
        reply, expects = result
        if self._cancelled_since(prev_gen):
            self.state = "idle"
            return True
        card = self.mail.card(reply)
        if card:
            self.publish(kind="card", card=card)
        await self.say(reply)
        await self.wait_speech_done()
        self.state = "thinking" if self.brain.busy else "idle"
        if expects and self.cfg["audio"]["followup_seconds"] > 0:
            self.listen(followup=True)
        return True

    async def cancel_all(self) -> None:
        """The cancel button: stop listening, speaking, approvals and the current brain turn."""
        events.emit("cancel")
        self._cancel_gen += 1
        self.stop_speaking()
        if self._listen_cancel:
            self._discard_recording = True  # cancel ≠ "finish the phrase": drop what was recorded
            self._listen_cancel.set()
        self._preapproved_until = 0.0
        if self._approval and not self._approval.done():
            self._approval.set_result("deny")
        while not self._event_queue.empty():
            self._event_queue.get_nowait()
        await self.brain.interrupt()
        if self.side:
            await self.side.interrupt()
        self.state = "idle"
        self.publish(detail=t("Отменено"), kind="tool")
        await self.earcon("error")

    async def run_turn(self, text: str, source: str = "voice") -> str:
        self.state = "thinking"
        spoken_before = self._spoken
        gen = self._cancel_gen
        if time.monotonic() < self._cloud_down_until:  # it just failed: don't wait out the same timeout again
            return await self.offline_turn(text)
        try:
            reply = await self.brain.ask(text, source=source)
            self._cloud_down_until = 0.0
        except Exception as e:
            if gen != self._cancel_gen:
                return ""
            events.emit("turn_failed", error=repr(e))
            self._cloud_down_until = time.monotonic() + 300
            reply = await self.offline_turn(text)
        if gen != self._cancel_gen:  # cancelled: no "done" sound, no follow-up listening
            return ""
        await self.wait_speech_done()
        self.state = "thinking" if self.side and self.side.busy else "idle"
        if self._spoken == spoken_before and source != "event":
            await self.earcon("done")  # silent success
        if source == "voice" and reply.rstrip().endswith("?") and self.cfg["audio"]["followup_seconds"] > 0:
            self.listen(followup=True)
        return reply

    async def offline_turn(self, text: str) -> str:
        """The cloud is out — no tokens, no network. Do here what never needed it, and say so honestly.

        A local model turns the phrase into one of four things (a program, the downloaded music, the
        volume, a short answer); with no model at all, two regexes still cover «включи музыку» and
        «открой …». The point is that the button keeps doing something."""
        loop = asyncio.get_running_loop()
        got = await loop.run_in_executor(None, offline.decide, text)
        action, query = got["action"], got["query"]
        if action == "music":
            r = await self.play_library(query, shuffle=not query)
            said = r.get("done") or t("Из скачанного пока ничего нет.")
        elif action == "app":
            hits = await loop.run_in_executor(None, desktop.find_apps, query, 1)
            if hits:
                desktop.launch_app_id(hits[0]["id"])
                said = t("запустил {what}", what=hits[0]["name"])
            else:
                said = t("Не нашёл «{q}»", q=query)
        elif action == "volume":
            step = {"+": "10%+", "-": "10%-"}.get(query) or f"{max(0, min(100, int(query or 50)))}%"
            await loop.run_in_executor(None, lambda: subprocess.run(
                ["wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", step], capture_output=True, timeout=5))
            said = t("готово")
        else:
            said = got["answer"] or t("Облако сейчас недоступно.")
        if time.monotonic() - self._offline_note > 600:  # say it once, not before every sentence
            self._offline_note = time.monotonic()
            said = t("Облако не отвечает, работаю сам. ") + said
        events.emit("offline", text=text, action=action, said=said[:300])
        await self.say(said)
        return said

    # ---------------- approvals and questions ----------------
    async def _ask(self, speech: str, choices: list[str] | None = None, free_text: bool = False,
                   notify: tuple[str, str] | None = None) -> str | None:
        """Wait for the user's answer: an island button, the voice, or (no island running) a desktop notification.
        Returns "allow" / "deny", one of `choices`, the user's own words (`free_text`), or None after 120 s.
        A click counts at once — no waiting for the question to be read out."""
        loop = asyncio.get_running_loop()
        fut = self._approval = loop.create_future()
        self._ask_choices, self._ask_free = choices or [], free_text
        self.state = "approval"
        await self.say(speech)
        side: list[asyncio.Task] = []
        proc = None
        if notify and not self._subs:
            proc = await asyncio.create_subprocess_exec(
                "notify-send", "-a", "JustDay", "-u", "critical", "-i", "dialog-warning", "--wait",
                f"--action=allow={t('Разрешить')}", f"--action=deny={t('Отклонить')}",
                t("JustDay просит подтверждение"), f"{notify[0][:400]}\n{notify[1][:200]}",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)

            async def from_notification():
                out, _ = await proc.communicate()
                choice = out.decode().strip()
                if choice in ("allow", "deny") and not fut.done():
                    fut.set_result(choice)

            side.append(spawn(from_notification()))
        spoken = spawn(self.wait_speech_done())
        deadline = loop.time() + 120
        try:
            await asyncio.wait({fut, spoken}, timeout=120, return_when=asyncio.FIRST_COMPLETED)
            if not fut.done():
                self.listen(followup=True)  # the question has been read out: now a spoken answer is welcome too
                await asyncio.wait({fut}, timeout=max(0.0, deadline - loop.time()))
            return fut.result() if fut.done() else None
        finally:
            if not spoken.done():
                spoken.cancel()
                self.stop_speaking()
            if fut.done() and self.state == "listening" and self._listen_cancel:  # clicked while we listened
                self._discard_recording = True
                self._listen_cancel.set()
            self.state = "thinking" if self.brain.busy else "idle"
            for task in side:
                task.cancel()
            if proc and proc.returncode is None:
                proc.kill()
            self._approval = None
            self._ask_choices, self._ask_free = [], False

    def _match_answer(self, text: str) -> str | None:
        """A spoken reply to the pending question, or None if it is not an answer."""
        norm = re.sub(r"[^\w ]+", " ", text.lower().replace("ё", "е")).strip()
        for c in self._ask_choices:
            cn = re.sub(r"[^\w ]+", " ", c.lower().replace("ё", "е")).strip()
            if cn and (cn in norm or (len(norm) > 2 and norm in cn)):
                return c
        long = len(norm.split()) > 3  # "да, но добавь смайлик" is a correction, not a yes
        yes, no = bool(YES.search(text)) and not NO.search(text), bool(NO.search(text))
        if not (self._ask_free and long):
            if yes:
                return self._ask_choices[0] if self._ask_choices else "allow"
            if no and not self._ask_choices:
                return "deny"
        return text if self._ask_free else None

    async def _approve(self, desc: str, reason: str, hard: bool = True) -> bool:
        if not hard and time.monotonic() < self._preapproved_until:
            events.emit("approval_auto", desc=desc)  # the user already approved this in the draft card
            return True
        return await self._ask(t("Нужно подтверждение. Разрешить?"), notify=(desc, reason)) == "allow"

    async def _answer_questions(self, questions: list[dict]) -> dict | None:
        """The brain's AskUserQuestion, shown as a card with the options as buttons; answered by click or voice."""
        answers: dict[str, str] = {}
        try:
            for q in questions[:4]:
                labels = [o.get("label", "") for o in q.get("options", []) if o.get("label")]
                self.publish(kind="card", card={"type": "question", "question": q.get("question", ""),
                                                "header": q.get("header", ""), "options": q.get("options", [])})
                spoken = q.get("question", "")
                if labels:
                    spoken += " " + (t("{a} или {b}?", a=", ".join(labels[:-1]), b=labels[-1]) if len(labels) > 1 else labels[0])
                ans = await self._ask(spoken, choices=labels, free_text=True)
                if ans in (None, "deny"):
                    return None
                answers[q.get("question", "")] = labels[0] if ans == "allow" and labels else ans
            return answers
        finally:
            self.publish(kind="card_close")

    async def confirm_message(self, to: str, via: str, text: str) -> dict:
        """A message draft shown BEFORE the brain opens the messenger. Approved → sending is pre-approved."""
        self.publish(kind="card", card={"type": "message_draft", "to": to, "via": via, "body": text})
        where = f"{to} ({via})" if via else to
        ans = await self._ask(t("{to}: «{text}». Отправить?", to=where, text=text), free_text=True)
        self.publish(kind="card_close")
        if ans == "allow":
            self._preapproved_until = time.monotonic() + 180
            return {"ok": True, "result": "approved: the user approved exactly this text. Now open the app and send it; "
                                          "do not ask again (sending is pre-approved for 3 minutes)."}
        if ans in (None, "deny"):
            return {"ok": True, "result": "denied: do not send it" + (" (no answer)" if ans is None else "")}
        return {"ok": True, "result": f"edit: the user said «{ans}». Rewrite the text accordingly and run "
                                      f"confirm-message again before sending."}

    # ---------------- background: wake word, mic idle, worker reports ----------------
    def _setup_wakeword(self) -> None:
        w = self.cfg["wakeword"]
        if not w["enabled"] or not self.mic_on():
            return
        from openwakeword.model import Model

        path = audio.onnx_model(f"{w['model']}_v0.1.onnx")
        feature_models = {"melspec_model_path": audio.onnx_model("melspectrogram.onnx"),
                          "embedding_model_path": audio.onnx_model("embedding_model.onnx")}
        prof = voiceprint.profile() or {}
        verifier = prof.get("wake_verifier") or ""
        if verifier and os.path.exists(verifier):  # trained on the user's own "Hey Jarvis"
            self._wake = Model(wakeword_models=[path], inference_framework="onnx", **feature_models,
                               custom_verifier_models={os.path.basename(path).rsplit(".onnx", 1)[0]: verifier},
                               custom_verifier_threshold=0.3)
        else:
            self._wake = Model(wakeword_models=[path], inference_framework="onnx", **feature_models)
        loop = asyncio.get_running_loop()

        def on_frame(frame: np.ndarray) -> None:
            if self.state == "listening" or time.monotonic() < self._wake_cooldown:
                return
            score = max(self._wake.predict(frame).values())
            if score >= w["threshold"]:
                self._wake_cooldown = time.monotonic() + 2.5
                self._wake.reset()
                events.emit("wakeword", score=round(float(score), 2))
                loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self.toggle(source="wake")))

        self.mic.subscribe(on_frame)
        if w.get("names", True):
            u = self.cfg["user"]
            # only the main name wakes it («Джарвис»); the other names are for talking, not for waking
            names = [n for n in (w.get("wake_names") or [u["assistant_name"]]) if n]
            self._names = namespot.spellings([n for n in [u["assistant_name"], *u.get("assistant_aliases", [])] if n])

            def on_name(clip, continuing, take_tail) -> None:  # Whisper thread
                self._wake_cooldown = time.monotonic() + 2.5  # "Hey Jarvis" must not toggle it off again
                events.emit("wakeword", name=True, continuing=continuing)
                if continuing:
                    prefill = lambda: [(-1, clip), *take_tail()]  # noqa: E731
                else:
                    take_tail()
                    prefill = None
                loop.call_soon_threadsafe(self._wake_by_name, prefill, lambda: prefill and prefill())

            spotter = namespot.NameSpotter(self.stt.transcribe_head, names, lambda: self.mic.seq, on_name)
            self.mic.subscribe(lambda f: spotter.feed(
                f, self.state in ("idle", "thinking") and time.monotonic() > max(self._quiet_until, self._wake_cooldown)))
        self.mic.start()

    async def _watch_notifications(self) -> None:
        """Mirror desktop notifications onto the island (read-only eavesdrop; Plasma still shows and owns them).
        They stay on this computer: nothing is passed to the brain."""
        rule = "type='method_call',interface='org.freedesktop.Notifications',member='Notify'"
        while True:
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

    def _emit_notification(self, raw: str) -> None:
        if "member=Notify" not in raw or not self.cfg["island"].get("show_notifications", True):
            return
        n = notifications.parse_notification(raw)
        if not n or n["app"] == "JustDay":  # our own approval / status notifications
            return
        self.publish(kind="notification", notification=n)

    async def _housekeeping(self) -> None:
        poll = self.cfg["workers"]["poll_seconds"]
        last_poll = last_mail = last_ping = last_weather = 0.0
        last_update_check = time.monotonic() - self.cfg["updates"]["interval_hours"] * 3600 + 120  # first check 2 min after start
        m = self.cfg["mail"]
        while True:
            await asyncio.sleep(2)
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
            if time.monotonic() - getattr(self, "_last_cal", 0) > 300 and calendar_lane.urls():
                self._last_cal = time.monotonic()
                try:
                    nxt = await asyncio.get_running_loop().run_in_executor(None, calendar_lane.upcoming, 2)
                except Exception:
                    nxt = None
                self.publish(next_event=nxt)
            isl = self.cfg["island"]
            if isl["show_weather"] and isl["city"] and (time.monotonic() - last_weather > 900 or self._weather_city != isl["city"]):
                last_weather, self._weather_city = time.monotonic(), isl["city"]
                try:
                    self.weather = await asyncio.get_running_loop().run_in_executor(None, weather_mod.fetch_weather, isl["city"])
                except Exception as e:
                    log.info("weather unavailable: %s", type(e).__name__)
                self.publish(weather=self.weather)
            if time.monotonic() - last_ping > 5:  # heartbeat: lets the island notice a dead connection
                last_ping = time.monotonic()
                self.stt.vocabulary = island.vocabulary(self.cfg)  # contacts learned meanwhile
                self.publish(ping=1, state=self.state)
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

    # A query is "sure" when the words asked for are actually in the title of the first hit and nothing
    # else looks just as likely. "Flower Man" is sure — there is one. "No name" is not.
    SURE_GAP = 0.22          # how much better the first hit must be than the second
    SURE_HIT = 0.72          # how much of the query the first title must actually contain
    SURE_LOCAL = 0.95        # a downloaded track this close to the words asked for is *the* one

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
            self.music.set_loading({"title": query, "progress": 0})
            source = ""
            if playlist or (media.is_url(query) and "list=" in query):  # an album / playlist / "best of"
                source, entries = await loop.run_in_executor(None, media.playlist, query)
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

    def _pause_videos(self) -> None:
        if self.island_video:
            self.publish(kind="video_cmd", action="pause")
        media.window_command("set_property", "pause", True)

    WHERE_WORDS: ClassVar = [("browser", re.compile(r"ютуб|youtube|браузер|browser|сайт", re.I)),
                             ("window", re.compile(r"окн|окош|отдельн|плеер|window|весь экран|fullscreen", re.I)),
                             ("island", re.compile(r"остров|здесь|тут|сверху|island|here", re.I))]

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

    async def play_video(self, query: str, where: str = "", random: bool = False) -> dict:
        loop = asyncio.get_running_loop()
        query = query.strip()
        path = Path(query).expanduser()
        try:
            if query.startswith(("/", "~", "./")) and path.exists():
                e = {"id": "", "title": path.stem, "channel": "", "duration": 0, "url": str(path), "thumb_url": "", "file": str(path)}
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
        where = where or self.cfg["media"]["video_where"]
        if where not in media.WHERE:
            where = await self._ask_where(e)
            if where is None:
                return {"ok": False, "error": "cancelled", "result": "the user did not choose where to play it"}
        if self.music.playing:
            await self.music.pause()
        done = {"island": t("видео в острове"), "window": t("видео в окне"), "browser": t("видео на YouTube")}[where]
        if where == "browser" and not e.get("file"):
            media.open_browser(e["url"])
        elif where == "window" or (where == "browser" and e.get("file")):
            media.open_window(e.get("file") or e["url"], title=e["title"])
        else:
            self.island_video = {"title": e["title"], "channel": e.get("channel", ""), "url": e["url"],
                                 "thumb": e.get("thumb_url", ""), "file": e.get("file", ""), "progress": 0.0}
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

    async def _reconnect_brain(self) -> None:
        while self.brain.busy:
            await asyncio.sleep(1)
        try:
            await self.brain.reconnect()
            log.info("brain reconnected with the new character")
        except Exception:
            log.exception("brain reconnect failed")

    def _save_later(self, section: str, key: str, value) -> None:
        """A slider sends a value with every pixel: apply it at once, write the file when the dragging stops."""
        pending = self._saves.pop((section, key), None)
        if pending:
            pending.cancel()
        self._saves[(section, key)] = asyncio.get_running_loop().call_later(
            1.0, lambda: config.set_value(section, key, value))

    def set_volume(self, value: int) -> int:
        """JustDay's own loudness (voice and signals), 0–100. The system volume is not ours to move."""
        v = max(0, min(100, int(value)))
        self.player.volume = v
        self.cfg["audio"]["volume"] = v
        self._save_later("audio", "volume", v)
        return v

    async def media_control(self, action: str, value=None) -> dict:
        """pause | resume | toggle | next | prev | restart | stop | seek SECONDS | volume 0-130 | color NAME | status"""
        m = self.music
        if action == "status":
            return {"ok": True, "music": m.state(), "island_video": self.island_video}
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

    MEDIA_KIND: ClassVar = {"image": "image", "edit": "image", "upscale": "image", "nobg": "image", "gif": "image",
                            "music": "music", "speech": "speech", "3d": "3d", "subs": "text"}

    async def studio_done(self, job: dict, kind: str, what: str, quiet: bool) -> dict:
        from . import studio

        mk = self.MEDIA_KIND.get(kind, "video")
        file = job.get("file") or ""
        label = {"image": t("картинка"), "video": t("видео"), "music": t("звук"),
                 "speech": t("озвучка"), "3d": t("3D-модель"), "text": t("субтитры")}[mk]
        card = {"type": "media", "kind": mk, "label": label, "file": file, "name": Path(file).name,
                "failed": job.get("state") == "failed", "error": job.get("error", "")}
        if file and mk in ("image", "video"):
            thumb = config.RUNTIME_DIR / "justday-thumb" / (Path(file).stem + ".jpg")
            thumb.parent.mkdir(exist_ok=True)
            got = await asyncio.get_running_loop().run_in_executor(None, studio.thumbnail, file, thumb)
            card["thumb"] = str(got) if got else ""
        elif job.get("preview"):  # a 3D model: the picture it was made from
            card["thumb"] = job["preview"]
        self.publish(kind="card", card=card)
        if not quiet:  # a background job: the brain tells the user in its own words
            state = "готово: " + file if job.get("state") == "done" else "не получилось: " + str(job.get("error"))
            self._event_queue.put_nowait(
                f"[Событие JustDay] Фоновая задача студии ({kind}: «{what[:120]}») — {state}. Карточка с файлом уже "
                "на острове. Коротко скажи пользователю (одна фраза, без пути к файлу); если не получилось — предложи "
                "попробовать иначе.")
        return {"ok": True}

    # ---------------- control socket ----------------
    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            req = json.loads((await reader.readline()).decode() or "{}")
            cmd = req.get("cmd")
            if cmd == "subscribe":
                self._subs.add(writer)
                hello = {"state": self.state, "workers": self._workers_active, "settings": island.settings_snapshot(self.cfg),
                         "history": island.recent_history(), "weather": self.weather, "update": self.update_info,
                         "player": self._player_state, "video": self.island_video,
                         "reminders": self._reminders_state(), "jobs": self.jobs.state()}
                try:
                    writer.write((json.dumps(hello, ensure_ascii=False) + "\n").encode())
                    await writer.drain()
                    await reader.read()  # hold the connection until the client goes away
                except ConnectionError:
                    pass  # the island restarted while we greeted it
                self._subs.discard(writer)
                writer.close()
                return
            if cmd == "toggle":
                resp = {"ok": True, "result": await self.toggle()}
            elif cmd == "listen":
                self.stop_speaking()
                self.listen()
                resp = {"ok": True}
            elif cmd == "stop":
                await self.cancel_all()
                resp = {"ok": True}
            elif cmd == "ask" and (local := await self.handle_local(req["text"], "cli")) is not None:
                resp = {"ok": True, "result": local or t("сделано")}  # «пауза» works while the brain is busy too
            elif cmd == "ask" and self.brain.busy and not req.get("wait"):
                await self.brain.inject(req["text"], source="cli")
                resp = {"ok": True, "result": "(передано в текущую задачу)"}
            elif cmd == "ask":
                if req.get("silent"):
                    reply = await self.brain.ask(req["text"], source="cli")
                else:
                    reply = await self.run_turn(req["text"], source="cli")
                resp = {"ok": True, "result": reply}
            elif cmd == "say":
                self.stop_speaking()
                await self.say(req["text"], force=True)  # `justday say` and voice previews are heard even when muted
                await self.wait_speech_done()
                resp = {"ok": True}
            elif cmd == "status":
                resp = {"ok": True, "state": self.state, "brain_busy": self.brain.busy,
                        "session": self.brain.session_id, "wakeword": bool(self._wake), "silent": self.silent(),
                        "mic_source": self.mic.source, "model": self.cfg["brain"]["model"],
                        # Громкость самого ассистента: телефону она нужна, чтобы
                        # показать ползунок там же, где ползунок музыки.
                        "volume": self.player.volume}
            elif cmd in ("approve", "deny"):
                pending = self._approval is not None and not self._approval.done()
                if pending:
                    self._approval.set_result((cmd == "approve" and (self._ask_choices or ["allow"])[0]) or "deny")
                resp = {"ok": pending, "error": None if pending else "nothing awaits approval"}
            elif cmd == "new_session":
                await self.brain.new_session()
                resp = {"ok": True}
            elif cmd == "compose":  # keyboard shortcut: open the text field (with the selected text, if any)
                self.stop_speaking()
                self.publish(kind="compose", text=req.get("text", ""), context=req.get("context") or {})
                resp = {"ok": True}
            elif cmd == "type":  # text typed into the Dynamic Island: same routing as speech
                events.emit("heard", text=req["text"], seconds=0)
                text, ctx = req["text"], req.get("context") or {}
                if ctx.get("selection"):  # "explain this", "translate this" about the text selected on screen
                    text += ("\n\n[Текст, выделенный пользователем" + (f" в окне «{ctx['window']}»" if ctx.get("window") else "")
                             + f":]\n{ctx['selection'][:6000]}")
                spawn(self.handle_utterance(text, source="island"))
                resp = {"ok": True}
            elif cmd == "answer":  # a question card button: the option label
                pending = self._approval is not None and not self._approval.done()
                if pending:
                    self._approval.set_result(str(req.get("value", "")))
                resp = {"ok": pending}
            elif cmd == "confirm_message":
                resp = await self.confirm_message(req.get("to", ""), req.get("via", ""), req.get("text", ""))
            elif cmd == "mail_compose":  # from the brain: draft locally, confirm by voice / island, never echo the address
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
            elif cmd == "enroll_record":
                resp = await self.enroll_record(req.get("kind", "phrase"), int(req.get("index", 0)), float(req.get("seconds", 4)))
            elif cmd == "enroll_finish":
                resp = await asyncio.get_running_loop().run_in_executor(None, voiceprint.enroll_finish)
                if resp.get("ok"):
                    config.set_value("audio", "silence_seconds", resp["silence_seconds"])
                    if self.cfg["voiceprint"]["mode"] == "off":
                        config.set_value("voiceprint", "mode", "wake")
                    self.reload_settings()
            elif cmd == "voiceprint_status":
                p = voiceprint.profile()
                resp = {"ok": True, "enrolled": bool(p), "created": (p or {}).get("created", ""), "threshold": (p or {}).get("threshold"),
                        "wake_verifier": bool((p or {}).get("wake_verifier")), "mode": self.cfg["voiceprint"]["mode"],
                        "phrases": voiceprint.phrases(), "wake_phrases": voiceprint.WAKE_PHRASES}
            elif cmd == "voiceprint_reset":
                voiceprint.reset()
                config.set_value("voiceprint", "mode", "off")
                self.reload_settings()
                resp = {"ok": True}
            elif cmd == "record_sample":  # voice cloning sample: record N seconds, transcribe locally
                resp = await self.record_sample(float(req.get("seconds", 12)))
            elif cmd == "studio_done":  # a studio file is ready (or failed): card on the island; background jobs are reported
                resp = await self.studio_done(req.get("job") or {}, req.get("kind", ""), req.get("what", ""),
                                              bool(req.get("quiet")))
            elif cmd == "media_play":  # justday play: YouTube → file → our player
                resp = await self.play_music(req.get("query", ""), int(req.get("count", 1)), req.get("mode", "replace"),
                                             bool(req.get("playlist")), bool(req.get("shuffle")))
            elif cmd == "media_video":  # justday video: asks where (island / window / YouTube) unless told
                resp = await self.play_video(req.get("query", ""), req.get("where", ""))
            elif cmd == "volume":  # the island's slider: how loud JustDay itself is
                resp = {"ok": True, "volume": self.set_volume(int(req.get("value", 100)))}
                self.publish(settings=island.settings_snapshot(self.cfg))
            elif cmd == "job_start":  # `justday job start "Обновление системы" -- jii update --json`
                resp = await self.start_job(req.get("title", ""), req["command"], req.get("cwd", ""))
            elif cmd == "job_list":
                resp = {"ok": True, "jobs": [dict(j, tail=self.jobs.tail(j["id"], 3)) for j in self.jobs.state()]}
            elif cmd == "job_log":
                resp = {"ok": True, "log": self.jobs.tail(req.get("id", ""), int(req.get("lines", 40)))}
            elif cmd == "job_stop":
                resp = {"ok": self.jobs.stop(req.get("id", ""))}
            elif cmd == "dictate":  # звук с телефона: распознаём здесь и выполняем как обычную просьбу
                resp = await self.dictate(req.get("path", ""))
            elif cmd == "session":  # «я ушёл» from the island, the phone or the command line
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
            elif cmd == "media":  # player buttons and `justday player ACTION`
                resp = await self.media_control(req.get("action", "status"), req.get("value"))
            elif cmd == "reminder_set":  # `justday timer 10m` and the island's own buttons
                at = float(req.get("at") or 0) or time.time() + float(req.get("seconds") or 0)
                rec = reminders.add(req.get("kind", "timer"), at, req.get("label", ""), req.get("repeat", ""))
                self._reschedule()
                resp = {"ok": True, "reminder": rec}
            elif cmd == "reminder_cancel":
                gone = reminders.cancel(req.get("which", ""))
                self._reschedule()
                resp = {"ok": True, "cancelled": len(gone)}
            elif cmd == "reminders":
                resp = {"ok": True, "reminders": self._reminders_state(), "said": self._reminders_line()}
            elif cmd == "alarm_dismiss":  # the button on the island while it rings
                self.dismiss_alarm(req.get("id", ""))
                resp = {"ok": True}
            elif cmd == "notification_open":  # a tap on a notification: its app comes forward
                resp = {"ok": True, "result": await asyncio.get_running_loop().run_in_executor(
                    None, notifications.open_notification_app, req.get("app", ""), req.get("desktop", ""))}
            elif cmd == "video_state":  # the island reports its video (playing / position / closed)
                if req.get("closed"):
                    self.island_video = None
                    self.publish(video=None)
                elif self.island_video:
                    self.island_video.update(playing=bool(req.get("playing")), pos=float(req.get("pos") or 0))
                resp = {"ok": True}
            elif cmd == "video_popout":  # island video → its own window, from the same second
                v = self.island_video or {}
                if v.get("file"):
                    media.open_window(v["file"], float(req.get("pos") or 0), v.get("title", ""), bool(req.get("fullscreen")))
                self.island_video = None
                self.publish(video=None)
                resp = {"ok": True}
            elif cmd == "reload_settings":  # after `justday config set`: hot-apply what can be
                resp = {"ok": True, "restart_needed": self.reload_settings()}
            else:
                resp = {"ok": False, "error": f"unknown command {cmd}"}
        except Exception as e:
            log.exception("control request failed")
            resp = {"ok": False, "error": repr(e)}
        try:
            writer.write((json.dumps(resp, ensure_ascii=False) + "\n").encode())
            await writer.drain()
        except ConnectionError:
            pass  # the asker gave up (timeout, Ctrl+C): nobody to answer
        writer.close()

    async def run(self) -> None:
        config.ensure_dirs()
        if self.cfg["desktop"]["accessibility"]:
            # Qt/GTK apps then publish their widgets over AT-SPI (exact click targets for `look`/`act`)
            subprocess.run(["busctl", "--user", "set-property", "org.a11y.Bus", "/org/a11y/bus", "org.a11y.Status",
                            "IsEnabled", "b", "true"], capture_output=True, timeout=5)
        loop = asyncio.get_running_loop()
        self._loop = loop
        events.subscribe(self._on_event)
        if config.SOCKET_PATH.exists():
            config.SOCKET_PATH.unlink()
        server = await asyncio.start_unix_server(self._client, path=str(config.SOCKET_PATH))
        os.chmod(config.SOCKET_PATH, 0o600)
        spawn(self._speech_worker())
        # Warm up models in the background so the first command is fast.
        if self.mic_on():  # keyboard-only setups never load speech recognition
            loop.run_in_executor(None, self.stt.load)
        loop.run_in_executor(None, self.tts.load)
        await self.brain.start()
        if await self.music.attach():  # music that kept playing through a daemon restart
            log.info("music player reattached")
        self._reschedule()  # alarms survive a restart
        self._setup_wakeword()
        spawn(self._housekeeping())
        if shutil.which("dbus-monitor"):
            spawn(self._watch_notifications())
        events.emit("daemon_ready", socket=str(config.SOCKET_PATH), mic=self.mic.source, wakeword=bool(self._wake))
        stop = asyncio.Event()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)
        await stop.wait()
        # Python 3.12's Server.wait_closed() waits for every client, and the island never hangs up — close them first.
        server.close()
        for w in list(self._subs):
            w.close()
        if self._notify_proc and self._notify_proc.returncode is None:
            self._notify_proc.kill()
        self.mic.stop()
        try:
            await asyncio.wait_for(self.brain.stop(), 5)
        except Exception:
            log.exception("brain stop")
        events.emit("daemon_stopped")
        logging.shutdown()
        os._exit(0)  # executor threads (STT/TTS/mail calls) must not keep a restart waiting


def main() -> None:
    config.ensure_dirs()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(), logging.FileHandler(config.STATE_DIR / "justday.log")],
    )
    try:
        # numpy's OpenBLAS keeps a thread per core and wakes them all for every 80 ms of microphone audio:
        # on a 20-thread CPU that alone kept the idle daemon at half a core. Our arrays are tiny: one thread.
        from threadpoolctl import threadpool_limits
        threadpool_limits(1, user_api="blas")
    except ImportError:
        pass
    asyncio.run(Daemon().run())
