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

import numpy as np

from . import (audio, calendar_lane, config, events, fastpath, mail, media, namespot, palette, reminders,
               voiceprint, workers)
from .i18n import lang, t
from . import brain as brain_mod
from .brain import Brain
from .stt import STT
from . import tts as tts_mod
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
        for needle, icon in (("justday play", "media-playback-start"), ("justday video", "video-x-generic"),
                             ("justday player", "media-playback-start"), ("youtube", "youtube"), ("yt-dlp", "youtube"), ("justday claude", "applications-development"),
                             ("jii ", "system-software-install"), ("justday studio", "applications-graphics"), ("justday games", "applications-games"), ("steam", "steam"), ("justday apps", "application-x-executable"),
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
            "desktop": d.group(1) if d else "", "body": re.sub(r"<[^>]+>", "", unq(m["body"]))[:4000]}


# parts of a desktop id or an app name that match half the desktop: never search windows by these
NOISE = {"desktop", "app", "client", "gui", "gtk", "qt", "org", "com", "io", "net", "www", "free", "linux", "flatpak"}


def notification_terms(app: str, desktop_id: str) -> list[str]:
    """Window-search terms for a notification, most telling first: `org.telegram.desktop` + `Telegram Desktop`
    → org.telegram.desktop, telegram, telegram desktop. Plain `desktop` would match half the windows open."""
    terms: list[str] = []
    if desktop_id:
        terms.append(desktop_id.lower())
        parts = [p for p in desktop_id.lower().split(".") if p and p not in NOISE]
        if parts:
            terms.append(parts[-1])
    if app:
        terms.append(app.lower())
        word = app.lower().split()[0] if app.split() else ""
        if word and word not in NOISE:
            terms.append(word)
    out: list[str] = []
    for term in terms:  # keep the order, drop repeats and terms too short to mean anything
        if len(term) > 2 and term not in out:
            out.append(term)
    return out


def open_notification_app(app: str, desktop_id: str) -> str:
    """A tap on a notification on the island: bring its app forward (or start it). The exact chat opens only when
    Plasma's own popup is clicked — the island only watches notifications, it cannot press their buttons."""
    from . import desktop

    terms = notification_terms(app, desktop_id)
    for term in terms:
        if desktop.windows("focus", term):
            log.info("notification: focused a window matching %r", term)
            return "focused"
    # no window: Telegram and Discord hide in the tray, and starting them again does nothing.
    # Activating their tray icon is exactly what a click on it does — the window comes back.
    flat = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())  # noqa: E731
    keys = [flat(t) for t in terms if flat(t)]
    for item in desktop.tray_items():
        hay = flat(item["id"]) + " " + flat(item["title"])
        if any(k in hay for k in keys) and desktop.tray_activate(item):
            log.info("notification: activated the tray icon of %s", item["id"] or item["service"])
            return "tray"
    # still nothing: start the app from its desktop entry
    apps = desktop.list_apps()
    hit = next((a for a in apps if desktop_id and a["id"] == desktop_id), None)
    if not hit:  # a name like "Telegram Desktop" scores below an exact hit — take the best of the terms
        best = None
        for term in terms:
            for a in desktop.find_apps(term, 1):
                if a.get("score", 0) > (best or {}).get("score", 0):
                    best = a
        hit = best if best and best.get("score", 0) >= 0.6 else None
    if hit:
        desktop.launch_app_id(hit["id"])
        log.info("notification: launched %s", hit["id"])
        return "launched"
    log.info("notification: no app for app=%r desktop=%r", app, desktop_id)
    return "not found"


def settings_snapshot(cfg: dict) -> dict:
    b, m = cfg["brain"], cfg["mail"]
    return {"provider": b.get("provider", "claude"), "model": b["model"], "assistant_name": cfg["user"]["assistant_name"],
            "language": cfg["user"].get("language", "ru"),
            "earcons": cfg["audio"]["earcons"], "notifications": cfg["ui"]["notifications"],
            "wakeword": cfg["wakeword"]["enabled"], "mail": bool(m["address"]), "mail_announce": m["announce"],
            "accessibility": cfg["desktop"]["accessibility"], "island": cfg["island"],
            "microphone": cfg["audio"].get("microphone", True), "voice": cfg["tts"]["engine"] != "none",
            "volume": int(cfg["audio"].get("volume", 100)),
            "tts_engine": cfg["tts"]["engine"], "tts_previous": cfg["tts"].get("previous_engine", ""),
            "hotkeys": _hotkeys(), "media": cfg["media"]}


def _hotkeys() -> dict:
    from . import manage

    try:
        return manage.hotkeys()
    except (OSError, subprocess.SubprocessError):
        return {}


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


# Text selected on screen is attached to a typed request; the list of recent requests shows what the
# person actually asked, not the page they had open.
ATTACHED = re.compile(r"\n\n\[Текст, выделенный пользователем.*", re.S)


def recent_history(limit: int = 6) -> list[dict]:
    """Last requests with their spoken answers, for the expanded island."""
    try:
        with config.EVENTS_FILE.open("rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 200_000))
            lines = f.read().decode("utf-8", "replace").splitlines()[1:]
    except OSError:
        return []
    def said_soon_after(request_ts: str, say_ts: str) -> bool:
        """A request that was interrupted has no answer: what is spoken an hour later (an alarm, new mail)
        belongs to nobody, and must not be shown as its reply."""
        try:
            return abs(datetime.fromisoformat(say_ts) - datetime.fromisoformat(request_ts)).total_seconds() <= 300
        except ValueError:
            return True

    out: list[dict] = []
    for line in lines:
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("kind") == "request" and e.get("source") != "event":
            out.append({"ts": e.get("ts", "")[11:16], "q": ATTACHED.sub("", e.get("text", "")).strip(), "a": "",
                        "at": e.get("ts", "")})
        elif e.get("kind") == "fast" and e.get("text"):
            out.append({"ts": e.get("ts", "")[11:16], "q": ATTACHED.sub("", e["text"]).strip(), "a": e.get("desc", ""),
                        "at": e.get("ts", "")})
        elif e.get("kind") == "say" and out and not out[-1]["a"] and said_soon_after(out[-1]["at"], e.get("ts", "")):
            out[-1]["a"] = e.get("text", "")
    return [{k: v for k, v in r.items() if k != "at"} for r in out[-limit:][::-1]]


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
        self.stt.vocabulary = vocabulary(self.cfg)
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
                asyncio.create_task(self.music.duck(value in ("listening", "speaking", "approval")))

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
                   "icon": tool_icon(data.get("name", ""), data.get("input", ""))}
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
            out = subprocess.run(cmd + ["JustDay", body[:300]], capture_output=True, text=True, timeout=5).stdout
            self._notify_id = int(out.strip() or 0)
        except Exception:
            pass

    # ---------------- speech output ----------------
    async def _on_brain_text(self, text: str) -> None:
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
                    asyncio.create_task(self._watch_release())
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
        if await self.media_fast(text):
            return
        if await self.reminder_fast(text):
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
            asyncio.create_task(self.music.set_volume(int(new["media"]["volume"])))
        self.brain.cfg["user"] = new["user"]
        self.stt.vocabulary = vocabulary(new)
        restart += [s for s in ("brain", "stt", "wakeword", "local_llm") if new[s] != old[s]]
        if new["user"].get("language") != old["user"].get("language"):
            restart.append("language")
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
        self._preapproved_until = 0.0
        if self._approval and not self._approval.done():
            self._approval.set_result("deny")
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

            side.append(asyncio.create_task(from_notification()))
        spoken = asyncio.create_task(self.wait_speech_done())
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
            self._colors = asyncio.create_task(self._resolve_colors(want))

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
            r = await (self.play_music(query) if kind == "music"
                       else self.play_video(query, random=kind == "video_random"))
            if r.get("ok"):
                self.brain.note(f"[Уже выполнено мгновенно, без тебя: «{text}» → {r.get('done', '')}. Не повторяй.]")
            elif r.get("error") != "cancelled":
                self.publish(kind="error", detail=t("Не нашёл «{q}»", q=query))
                await self.say(t("Не получилось включить: {e}", e=r.get("error", "")[:120]))

        asyncio.create_task(go())
        return True

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
                asyncio.create_task(self._cache_track(entries[0]))
        except Exception as e:  # noqa: BLE001
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
            asyncio.create_task(self._queue_rest(entries[1:]))
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
            self._cache_task = asyncio.create_task(self._cache_worker())

    async def _cache_worker(self) -> None:
        """One download at a time, so the library fills up without stealing bandwidth from what is playing."""
        loop = asyncio.get_running_loop()
        while self._cache_q:
            entry = self._cache_q.pop(0)
            try:
                await loop.run_in_executor(None, media.download_audio, entry, None)
            except Exception as e:  # noqa: BLE001
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
            except Exception as ex:  # noqa: BLE001
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
        events.emit("reminder_set", kind=rec["kind"], at=rec["at"], label=rec["label"])
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
        self._reminder_task = asyncio.create_task(self._reminder_loop())

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
        asyncio.create_task(self.music.duck(False))
        self.publish(kind="card_close")
        self.publish(reminders=self._reminders_state())

    def _pause_videos(self) -> None:
        if self.island_video:
            self.publish(kind="video_cmd", action="pause")
        media.window_command("set_property", "pause", True)

    WHERE_WORDS = [("browser", re.compile(r"ютуб|youtube|браузер|browser|сайт", re.I)),
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
        except Exception as ex:  # noqa: BLE001
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
                except Exception as ex:  # noqa: BLE001
                    self.island_video = None
                    self.publish(video=None)
                    return {"ok": False, "error": str(ex)}
                if not self.island_video or self.island_video.get("url") != e["url"]:
                    return {"ok": False, "error": "cancelled", "result": "the user closed the video while it loaded"}
                self.island_video.update(file=got["file"], thumb=got.get("thumb") or self.island_video["thumb"], progress=1.0)
                self.publish(video=self.island_video)
        events.emit("media_video", title=e["title"], where=where)
        return {"ok": True, "title": e["title"], "where": where, "url": e["url"], "done": done + ": " + e["title"]}

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
        elif action == "volume":
            v = int(value if value is not None else m.volume)
            await m.set_volume(v)
            self._save_later("media", "volume", v)
            self.cfg["media"]["volume"] = v
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

    MEDIA_KIND = {"image": "image", "edit": "image", "upscale": "image", "nobg": "image", "gif": "image",
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
                hello = {"state": self.state, "workers": self._workers_active, "settings": settings_snapshot(self.cfg),
                         "history": recent_history(), "weather": self.weather, "update": self.update_info,
                         "player": self._player_state, "video": self.island_video,
                         "reminders": self._reminders_state()}
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
                    self._approval.set_result(cmd == "approve" and (self._ask_choices or ["allow"])[0] or "deny")
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
                asyncio.create_task(self.handle_utterance(text, source="island"))
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
                self.publish(settings=settings_snapshot(self.cfg))
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
                    None, open_notification_app, req.get("app", ""), req.get("desktop", ""))}
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
        if self.mic_on():  # keyboard-only setups never load speech recognition
            loop.run_in_executor(None, self.stt.load)
        loop.run_in_executor(None, self.tts.load)
        await self.brain.start()
        if await self.music.attach():  # music that kept playing through a daemon restart
            log.info("music player reattached")
        self._reschedule()  # alarms survive a restart
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
