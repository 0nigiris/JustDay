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
import shutil
import signal
import subprocess
import time

import numpy as np

from . import audio, calendar_lane, config, events, fastpath, mail, namespot, voiceprint, workers
from .i18n import lang, t
from .brain import Brain
from .stt import STT
from .tts import TTS, normalize, split_sentences

log = logging.getLogger("justday.daemon")

# Bare acknowledgements ("Готово.", "Открыл терминал.") are replaced by the "done" earcon.
ACK = re.compile(r"^\W*(готово|сделано|сделал|есть|окей|ок|хорошо|выполнено|принято|done|"
                 r"(открыл|запустил|включил|закрыл|свернул|переключил|поставил|выключил)[\w\s«»\"'.-]{0,40})\W*$", re.I)
STOP_WORDS = re.compile(r"\b(стоп|хватит|отмена|отмени|отменяй|замолчи|заткнись|stop|cancel|never ?mind|shut up|be quiet)\b", re.I)
YES = re.compile(r"\b(да|давай|разрешаю|разреши|подтверждаю|конечно|ок|окей|можно|делай|yes|yeah|sure|ok|okay|allow|go ahead|do it)\b", re.I)
NO = re.compile(r"\b(нет|не надо|отмена|отклон\w*|запрещаю|стоп|no|nope|don'?t|deny|cancel)\b", re.I)


def tool_icon(name: str, inp: str) -> str:
    """Freedesktop icon name for a tool call, shown next to it in the Dynamic Island."""
    if name.startswith("mcp__claude-in-chrome"):
        return "internet-web-browser"
    if name.endswith("__look") or name.endswith("screenshot"):
        return "view-preview"
    if name.startswith("mcp__plugin_justday_kwin"):
        return "input-mouse"
    if name in ("WebSearch", "WebFetch"):
        return "system-search"
    if name in ("Read", "Edit", "Write", "Glob", "Grep"):
        return "document-edit" if name in ("Edit", "Write") else "document-open"
    if name in ("Agent", "Task"):
        return "applications-development"
    if name == "Skill":
        return "games-hint"
    if name == "Bash":
        cmd = inp.lower()
        for needle, icon in (("youtube", "youtube"), ("yt-dlp", "youtube"), ("justday claude", "applications-development"),
                             ("justday games", "applications-games"), ("steam", "steam"), ("justday apps", "application-x-executable"),
                             ("justday windows", "preferences-system-windows"), ("xdg-open http", "internet-web-browser"),
                             ("playerctl", "media-playback-start"), ("wpctl", "audio-volume-high"), ("git ", "git"),
                             ("kitty", "utilities-terminal"), ("plocate", "system-search"), ("fd ", "system-search")):
            if needle in cmd:
                return icon
        return "utilities-terminal"
    return "system-run"


def vocabulary(cfg: dict) -> str:
    """Whisper hint: the words this user says that a generic model gets wrong. Kept short (prompt ≤ ~224 tokens)."""
    from . import contacts

    words = [cfg["user"]["assistant_name"], *cfg["user"].get("assistant_aliases", [])]
    for c in contacts.load():
        words += [c.get("name", ""), *c.get("aliases", [])]
    words += [k for k in cfg["apps"]["aliases"]]
    base = cfg["stt"].get("initial_prompt", "")
    seen, extra = set(base.lower().replace(",", " ").split()), []
    for w in words:
        if w and w.lower() not in seen:
            seen.add(w.lower())
            extra.append(w)
    return (base.rstrip(". ") + ", " + ", ".join(extra[:40]) + ".") if extra else base


NOTIFY_RX = re.compile(r'string "(?P<app>.*?)"\n\s*uint32 \d+\n\s*string "(?P<icon>.*?)"\n\s*string "(?P<summary>.*?)"\n'
                       r'\s*string "(?P<body>.*?)"\n\s*array \[', re.S)
DESKTOP_RX = re.compile(r'string "desktop-entry"\n\s*variant\s+string "(.*?)"')


def parse_notification(raw: str) -> dict | None:
    """One `dbus-monitor` Notify call → {app, icon, summary, body}."""
    m = NOTIFY_RX.search(raw)
    if not m:
        return None
    d = DESKTOP_RX.search(raw)
    unq = lambda s: s.replace('\\"', '"')  # noqa: E731
    return {"app": unq(m["app"]), "icon": (d.group(1) if d else "") or m["icon"], "summary": unq(m["summary"]),
            "body": re.sub(r"<[^>]+>", "", unq(m["body"]))[:300]}


def settings_snapshot(cfg: dict) -> dict:
    b, m = cfg["brain"], cfg["mail"]
    return {"provider": b.get("provider", "claude"), "model": b["model"], "assistant_name": cfg["user"]["assistant_name"],
            "language": cfg["user"].get("language", "ru"),
            "earcons": cfg["audio"]["earcons"], "notifications": cfg["ui"]["notifications"],
            "wakeword": cfg["wakeword"]["enabled"], "mail": bool(m["address"]), "mail_announce": m["announce"],
            "accessibility": cfg["desktop"]["accessibility"], "island": cfg["island"]}


WMO = {0: ("Ясно", "sun"), 1: ("Малооблачно", "cloud-sun"), 2: ("Переменная облачность", "cloud-sun"), 3: ("Пасмурно", "cloud"),
       45: ("Туман", "cloud-fog"), 48: ("Туман", "cloud-fog"), 51: ("Морось", "cloud-rain"), 53: ("Морось", "cloud-rain"),
       55: ("Морось", "cloud-rain"), 61: ("Дождь", "cloud-rain"), 63: ("Дождь", "cloud-rain"), 65: ("Ливень", "cloud-rain"),
       71: ("Снег", "cloud-snow"), 73: ("Снег", "cloud-snow"), 75: ("Снегопад", "cloud-snow"), 80: ("Ливень", "cloud-rain"),
       81: ("Ливень", "cloud-rain"), 82: ("Ливень", "cloud-rain"), 85: ("Снег", "cloud-snow"), 86: ("Снег", "cloud-snow"),
       95: ("Гроза", "cloud-lightning"), 96: ("Гроза", "cloud-lightning"), 99: ("Гроза", "cloud-lightning")}


def fetch_weather(city: str) -> dict | None:
    """Current weather from Open-Meteo (free, no key). Only the city name / coordinates leave the computer."""
    import urllib.parse
    import urllib.request

    state = events.load_state()
    geo = state.get("weather_geo") or {}
    if geo.get("query") != city:
        url = "https://geocoding-api.open-meteo.com/v1/search?" + urllib.parse.urlencode({"name": city, "count": 1, "language": lang()})
        with urllib.request.urlopen(url, timeout=10) as r:
            found = (json.load(r).get("results") or [None])[0]
        if not found:
            return None
        geo = {"query": city, "lat": found["latitude"], "lon": found["longitude"], "name": found.get("name", city)}
        events.save_state(weather_geo=geo)
    url = ("https://api.open-meteo.com/v1/forecast?" + urllib.parse.urlencode(
        {"latitude": geo["lat"], "longitude": geo["lon"], "current": "temperature_2m,weather_code,is_day",
         "daily": "temperature_2m_max,temperature_2m_min", "forecast_days": 1, "timezone": "auto"}))
    with urllib.request.urlopen(url, timeout=10) as r:
        data = json.load(r)
    cur, daily = data["current"], data.get("daily", {})
    text, icon = WMO.get(int(cur["weather_code"]), ("", "cloud"))
    text = t(text)
    if icon == "sun" and not cur.get("is_day", 1):
        icon = "moon"
    return {"city": geo["name"], "temp": round(cur["temperature_2m"]), "text": text, "icon": icon,
            "max": round((daily.get("temperature_2m_max") or [cur["temperature_2m"]])[0]),
            "min": round((daily.get("temperature_2m_min") or [cur["temperature_2m"]])[0])}


def recent_history(limit: int = 6) -> list[dict]:
    """Last requests with their spoken answers, for the expanded island."""
    try:
        with config.EVENTS_FILE.open("rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 200_000))
            lines = f.read().decode("utf-8", "replace").splitlines()[1:]
    except OSError:
        return []
    out: list[dict] = []
    for line in lines:
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("kind") == "request" and e.get("source") != "event":
            out.append({"ts": e.get("ts", "")[11:16], "q": e.get("text", ""), "a": ""})
        elif e.get("kind") == "fast" and e.get("text"):
            out.append({"ts": e.get("ts", "")[11:16], "q": e["text"], "a": e.get("desc", "")})
        elif e.get("kind") == "say" and out and not out[-1]["a"]:
            out[-1]["a"] = e.get("text", "")
    return out[-limit:][::-1]


class Daemon:
    def __init__(self) -> None:
        self.cfg = config.load()
        a = self.cfg["audio"]
        self.mic = audio.Microphone(a["input"])
        self.player = audio.Player(a["output"])
        self.recorder = audio.UtteranceRecorder(self.mic, a["silence_seconds"], a["no_speech_timeout_seconds"],
                                                a["max_utterance_seconds"])
        self.stt = STT(self.cfg["stt"])
        self.tts = TTS(self.cfg["tts"])
        self.brain = Brain(self.cfg, on_text=self._on_brain_text, approver=self._approve)
        self._subs: set[asyncio.StreamWriter] = set()
        self._notify_proc: asyncio.subprocess.Process | None = None
        self._state = "idle"
        self._workers_active = 0
        self._listen_cancel: asyncio.Event | None = None
        self._listen_task: asyncio.Task | None = None
        self._speech_q: asyncio.Queue[str | None] = asyncio.Queue()
        self._speech_gen = 0
        self._approval: asyncio.Future | None = None
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
        self._activation = "button"
        self._cancel_gen = 0  # bumped by cancel_all: anything started before it is dropped
        self.weather: dict | None = None
        self.update_info: dict | None = None
        self._weather_city = ""
        self.mail = mail.MailAssistant()
        self.stt.vocabulary = vocabulary(self.cfg)

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
        if kind == "tool":
            msg = {"kind": "tool", "detail": data.get("label") or data.get("desc", ""),
                   "icon": tool_icon(data.get("name", ""), data.get("input", ""))}
        elif kind == "fast":
            msg = {"kind": "fast", "detail": data.get("desc", ""), "icon": fastpath.last_icon}
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
            out = subprocess.run(cmd + ["JustDay", body[:300]], capture_output=True, text=True, timeout=5).stdout
            self._notify_id = int(out.strip() or 0)
        except Exception:
            pass

    # ---------------- speech output ----------------
    async def _on_brain_text(self, text: str) -> None:
        if ACK.match(text.strip()) and len(text) < 60:
            events.emit("ack_suppressed", text=text)
            return
        self._spoken += 1
        lang = self.cfg["user"].get("language", "ru")
        self.tts.cfg["lang"] = lang
        for s in split_sentences(normalize(text, lang)):
            self._speech_q.put_nowait(s)

    async def say(self, text: str) -> None:
        await self._on_brain_text(text)

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
                if self.tts.cfg["engine"] == "qwen" and await self._speak_neural(sentence, gen):
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

    async def _speak_neural(self, sentence: str, gen: int) -> bool:
        """Stream one sentence from the neural voice service. False = service unavailable → caller uses Silero."""
        stream = self.tts.stream(sentence)
        try:
            first = await stream.__anext__()
        except StopAsyncIteration:
            return True
        except OSError:
            if not self._voice_warned:
                self._voice_warned = True
                log.warning("neural voice unavailable (systemctl --user status justday-voice), using Silero")
            return False
        self._voice_warned = False
        if gen != self._speech_gen:
            await stream.aclose()
            return True

        # jitter buffer: start playing only with ~0.4 s in hand, so a busy GPU doesn't tear the voice apart
        head = [first]
        buffered = len(first)
        try:
            while buffered < self.tts.NEURAL_RATE * 2 * 0.4:
                data = await stream.__anext__()
                head.append(data)
                buffered += len(data)
        except StopAsyncIteration:
            pass
        except OSError:
            log.warning("neural voice stream broke while buffering")

        async def chunks():
            for data in head:
                yield data
            async for data in stream:
                if gen != self._speech_gen:
                    break
                yield data

        self.state = "speaking"
        try:
            await self.player.play_stream(chunks(), self.tts.NEURAL_RATE)
        except OSError:
            log.warning("neural voice stream broke")
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
                    asyncio.create_task(self._watch_release())
                return "holding"
            self._listen_cancel.set()  # second tap: finish the utterance now
            return "stop-listening"
        self._holding = False
        self._activation = source
        self.stop_speaking()
        self.listen()
        return "listening"

    async def _watch_release(self) -> None:
        while self._holding and self.state == "listening":
            await asyncio.sleep(0.1)
            if time.monotonic() - self._last_toggle > 0.4:  # auto-repeat stopped → key released
                self._holding = False
                if self._listen_cancel:
                    self._listen_cancel.set()

    def listen(self, followup: bool = False, prefill=None) -> bool:
        if self._listen_task and not self._listen_task.done():
            return False
        self._listen_task = asyncio.create_task(self._listen_once(followup, prefill))
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

    async def handle_utterance(self, text: str, source: str = "voice") -> None:
        if self._approval and not self._approval.done():
            if YES.search(text) and not NO.search(text):
                self._approval.set_result(True)
                return
            if NO.search(text):
                self._approval.set_result(False)
                return
        if STOP_WORDS.search(text) and len(text.split()) <= 6:
            await self.cancel_all()
            return
        gen = self._cancel_gen
        done = await asyncio.get_running_loop().run_in_executor(None, fastpath.try_handle, text)
        if gen != self._cancel_gen:
            return
        if done:
            events.emit("fast", text=text, desc=done)
            self.publish(detail=done, kind="tool")
            self.brain.note(f"[Уже выполнено мгновенно, без тебя: «{text}» → {done}. Не повторяй это действие.]")
            self.state = "thinking" if self.brain.busy else "idle"
            await self.earcon("done")
            return
        if calendar_lane.CAL_WORDS.search(text):
            try:
                cal = await asyncio.get_running_loop().run_in_executor(None, calendar_lane.handle, text)
            except Exception as e:  # noqa: BLE001
                log.warning("calendar failed: %s", e)
                cal = (t("Не получилось открыть календарь."), None)
            if cal and gen == self._cancel_gen:
                reply, card = cal
                if card:
                    self.publish(kind="card", card=card)
                await self.say(reply)
                return
        if self.cfg["mail"]["address"] and self.mail.wants(text):
            if await self.handle_mail(text) or gen != self._cancel_gen:
                return
        if self.brain.busy:
            await self.brain.inject(text, source)  # keep the running task; Claude handles both
            return
        asyncio.create_task(self.run_turn(text, source))

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
        a = new["audio"]
        self.tts.cfg = new["tts"]
        self.recorder.silence_s = a["silence_seconds"]
        self.recorder.no_speech_timeout_s = a["no_speech_timeout_seconds"]
        self.recorder.max_s = a["max_utterance_seconds"]
        if a["input"] != old["audio"]["input"]:
            self.mic.stop()  # listen() starts it again on the new device
            self.mic.source = audio.find_node(a["input"]) if a["input"] else None
            if self._wake:
                self.mic.start()
        if a["output"] != old["audio"]["output"]:
            self.player.sink = audio.find_node(a["output"], "sinks") if a["output"] else None
        self.brain.cfg["user"] = new["user"]
        self.stt.vocabulary = vocabulary(new)
        restart = [s for s in ("brain", "stt", "wakeword", "local_llm") if new[s] != old[s]]
        if new["user"].get("language") != old["user"].get("language"):
            restart.append("language")
        if new["tts"]["engine"] != old["tts"]["engine"]:
            restart.append("tts")
        names = lambda c: (c["user"]["assistant_name"], c["user"].get("assistant_aliases"))  # noqa: E731
        if self._names and names(new) != names(old):  # the name spotter was built with the old names
            restart.append("wakeword")
        self.publish(settings=settings_snapshot(new))
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
        if self._approval and not self._approval.done():
            self._approval.set_result(False)
        while not self._event_queue.empty():
            self._event_queue.get_nowait()
        await self.brain.interrupt()
        self.state = "idle"
        self.publish(detail=t("Отменено"), kind="tool")
        await self.earcon("error")

    async def run_turn(self, text: str, source: str = "voice") -> str:
        self.state = "thinking"
        spoken_before = self._spoken
        gen = self._cancel_gen
        try:
            reply = await self.brain.ask(text, source=source)
        except Exception as e:
            if gen != self._cancel_gen:
                return ""
            events.emit("turn_failed", error=repr(e))
            await self.say(t("Не получилось связаться с мозгом. Подробности в логе."))
            reply = ""
        if gen != self._cancel_gen:  # cancelled: no "done" sound, no follow-up listening
            return ""
        await self.wait_speech_done()
        self.state = "idle"
        if self._spoken == spoken_before and source != "event":
            await self.earcon("done")  # silent success
        if source == "voice" and reply.rstrip().endswith("?") and self.cfg["audio"]["followup_seconds"] > 0:
            self.listen(followup=True)
        return reply

    # ---------------- approvals ----------------
    async def _approve(self, desc: str, reason: str) -> bool:
        loop = asyncio.get_running_loop()
        self._approval = loop.create_future()
        events.emit("approval_wait", desc=desc)
        self.state = "approval"
        # the command itself is shown on the island / in the notification; reading "rm минус rf…" aloud helps nobody
        await self.say(t("Нужно подтверждение. Разрешить?"))
        proc = await asyncio.create_subprocess_exec(
            "notify-send", "-a", "JustDay", "-u", "critical", "-i", "dialog-warning", "--wait",
            f"--action=allow={t('Разрешить')}", f"--action=deny={t('Отклонить')}",
            t("JustDay просит подтверждение"), f"{desc[:400]}\n{reason[:200]}",
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)

        async def from_notification():
            out, _ = await proc.communicate()
            choice = out.decode().strip()
            if choice in ("allow", "deny") and not self._approval.done():
                self._approval.set_result(choice == "allow")

        note_task = asyncio.create_task(from_notification())
        await self.wait_speech_done()
        self.listen(followup=True)
        try:
            return await asyncio.wait_for(asyncio.shield(self._approval), timeout=120)
        except TimeoutError:
            return False
        finally:
            self.state = "thinking"
            note_task.cancel()
            if proc.returncode is None:
                proc.kill()
            self._approval = None

    # ---------------- background: wake word, mic idle, worker reports ----------------
    def _setup_wakeword(self) -> None:
        w = self.cfg["wakeword"]
        if not w["enabled"]:
            return
        import openwakeword
        from openwakeword.model import Model
        from openwakeword.utils import download_models

        download_models(model_names=[w["model"]])
        path = os.path.join(os.path.dirname(openwakeword.__file__), "resources", "models", f"{w['model']}_v0.1.onnx")
        prof = voiceprint.profile() or {}
        verifier = prof.get("wake_verifier") or ""
        if verifier and os.path.exists(verifier):  # trained on the user's own "Hey Jarvis"
            self._wake = Model(wakeword_models=[path], inference_framework="onnx",
                               custom_verifier_models={os.path.basename(path).rsplit(".onnx", 1)[0]: verifier},
                               custom_verifier_threshold=0.3)
        else:
            self._wake = Model(wakeword_models=[path], inference_framework="onnx")
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
            names = [n for n in [u["assistant_name"], *u.get("assistant_aliases", [])] if n]
            self._names = namespot.spellings(names)

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
        n = parse_notification(raw)
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
                except Exception as e:  # noqa: BLE001 — offline is fine
                    log.info("update check failed: %s", type(e).__name__)
            if time.monotonic() - getattr(self, "_last_cal", 0) > 300 and calendar_lane.urls():
                self._last_cal = time.monotonic()
                try:
                    nxt = await asyncio.get_running_loop().run_in_executor(None, calendar_lane.upcoming, 2)
                except Exception:  # noqa: BLE001 — offline
                    nxt = None
                self.publish(next_event=nxt)
            isl = self.cfg["island"]
            if isl["show_weather"] and isl["city"] and (time.monotonic() - last_weather > 900 or self._weather_city != isl["city"]):
                last_weather, self._weather_city = time.monotonic(), isl["city"]
                try:
                    self.weather = await asyncio.get_running_loop().run_in_executor(None, fetch_weather, isl["city"])
                except Exception as e:  # noqa: BLE001 — offline is fine
                    log.info("weather unavailable: %s", type(e).__name__)
                self.publish(weather=self.weather)
            if time.monotonic() - last_ping > 5:  # heartbeat: lets the island notice a dead connection
                last_ping = time.monotonic()
                self.stt.vocabulary = vocabulary(self.cfg)  # contacts learned meanwhile
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
                asyncio.create_task(self.run_turn(self._event_queue.get_nowait(), source="event"))

    # ---------------- control socket ----------------
    async def _client(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        try:
            req = json.loads((await reader.readline()).decode() or "{}")
            cmd = req.get("cmd")
            if cmd == "subscribe":
                self._subs.add(writer)
                hello = {"state": self.state, "workers": self._workers_active, "settings": settings_snapshot(self.cfg),
                         "history": recent_history(), "weather": self.weather, "update": self.update_info}
                writer.write((json.dumps(hello, ensure_ascii=False) + "\n").encode())
                await writer.drain()
                await reader.read()  # hold the connection until the client goes away
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
            elif cmd == "ask" and self.brain.busy and not req.get("wait"):
                await self.brain.inject(req["text"], source="cli")
                resp = {"ok": True, "result": "(передано в текущую задачу)"}
            elif cmd == "ask":
                done = await asyncio.get_running_loop().run_in_executor(None, fastpath.try_handle, req["text"])
                if done:
                    events.emit("fast", text=req["text"], desc=done)
                    self.brain.note(f"[Уже выполнено мгновенно, без тебя: «{req['text']}» → {done}. Не повторяй это действие.]")
                    resp = {"ok": True, "result": f"(мгновенно) {done}"}
                elif req.get("silent"):
                    reply = await self.brain.ask(req["text"], source="cli")
                else:
                    reply = await self.run_turn(req["text"], source="cli")
                if not done:
                    resp = {"ok": True, "result": reply}
            elif cmd == "say":
                self.stop_speaking()
                await self.say(req["text"])
                await self.wait_speech_done()
                resp = {"ok": True}
            elif cmd == "status":
                resp = {"ok": True, "state": self.state, "brain_busy": self.brain.busy,
                        "session": self.brain.session_id, "wakeword": bool(self._wake),
                        "mic_source": self.mic.source, "model": self.cfg["brain"]["model"]}
            elif cmd in ("approve", "deny"):
                pending = self._approval is not None and not self._approval.done()
                if pending:
                    self._approval.set_result(cmd == "approve")
                resp = {"ok": pending, "error": None if pending else "nothing awaits approval"}
            elif cmd == "new_session":
                await self.brain.new_session()
                resp = {"ok": True}
            elif cmd == "type":  # text typed into the Dynamic Island: same routing as speech
                events.emit("heard", text=req["text"], seconds=0)
                asyncio.create_task(self.handle_utterance(req["text"], source="island"))
                resp = {"ok": True}
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
                    asyncio.create_task(self._speak_and_listen(reply, expects))
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
            elif cmd == "reload_settings":  # after `justday config set`: hot-apply what can be
                resp = {"ok": True, "restart_needed": self.reload_settings()}
            else:
                resp = {"ok": False, "error": f"unknown command {cmd}"}
        except Exception as e:
            log.exception("control request failed")
            resp = {"ok": False, "error": repr(e)}
        writer.write((json.dumps(resp, ensure_ascii=False) + "\n").encode())
        await writer.drain()
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
        asyncio.create_task(self._speech_worker())
        # Warm up models in the background so the first command is fast.
        loop.run_in_executor(None, self.stt.load)
        loop.run_in_executor(None, self.tts.load)
        await self.brain.start()
        self._setup_wakeword()
        asyncio.create_task(self._housekeeping())
        if shutil.which("dbus-monitor"):
            asyncio.create_task(self._watch_notifications())
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
        except Exception:  # noqa: BLE001
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
    asyncio.run(Daemon().run())
