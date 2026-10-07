"""justdayd — the voice loop: hotkey/wake word → record → transcribe → brain → speak.

Control API: newline-delimited JSON over a user-only Unix socket ($XDG_RUNTIME_DIR/justday.sock).
Never exposed on the network.
"""
from __future__ import annotations

import asyncio
import contextlib
import copy
import json
import logging
import os
import re
import shutil
import signal
import subprocess
import threading
import time
from pathlib import Path
from typing import ClassVar

import numpy as np

from . import (
    audio,
    briefing,
    calendar_lane,
    chitchat,
    clipboard,
    config,
    desktop,
    dispatch,
    dock,
    events,
    fallback,
    fastpath,
    filesearch,
    focus,
    geo,
    inbox,
    island,
    jobs,
    mail,
    media,
    namespot,
    notifications,
    numerals,
    observer,
    offline,
    parts,
    providers,
    scenes,
    session,
    sysload,
    voiceprint,
    volume,
    workers,
)
from . import brain as brain_mod
from . import tts as tts_mod
from . import weather as weather_mod
from .aio import spawn
from .approvals import AskMixin
from .brain import Brain
from .commands import CommandsMixin
from .i18n import t
from .ladder import LadderMixin
from .music_lane import MusicMixin
from .reminder_lane import ReminderMixin
from .stt import STT
from .tts import TTS, normalize, split_sentences
from .video_lane import VideoMixin
from .watchers import WatchersMixin

log = logging.getLogger("justday.daemon")

# Bare acknowledgements ("Готово.", "Открыл терминал.") are replaced by the "done" earcon.
ACK = re.compile(r"^\W*(?:(?:готово|окей|ок|хорошо|done|ok)\W+)?(готово|сделано|сделал|есть|окей|ок|хорошо|выполнено|принято|done|"
                 r"(открыл|запустил|включил|закрыл|свернул|переключил|поставил|выключил|включаю|ставлю|запускаю|"
                 r"включено|играет|играю|вот|now playing|playing)[\w\s«»\"'.,:—–-]{0,70})\W*$", re.I)
# «Выпало "…". Включаю.» — an announcement of a start is not an answer either, wherever the verb sits
ACK_TAIL = re.compile(r"(включаю|ставлю|запускаю|показываю|ищу|сейчас будет|playing|now playing)\s*[.!…]*$", re.I)
STOP_WORDS = re.compile(r"\b(стоп|хватит|отмена|отмени|отменяй|замолчи|заткнись|stop|cancel|never ?mind|shut up|be quiet)\b", re.I)


SIDE_AFTER_S = 5.0   # a tool call this old means an injected request would sit and wait: use the side session


class Daemon(CommandsMixin, LadderMixin, AskMixin, WatchersMixin, MusicMixin, VideoMixin, ReminderMixin):
    def __init__(self) -> None:
        self.cfg = config.load()
        self._from_file = copy.deepcopy(self.cfg)   # что было в файле: с ним сравнивает reload_settings
        a = self.cfg["audio"]
        self.mic = audio.Microphone(a["input"])
        self.player = audio.Player(a["output"], int(a.get("volume", 100)))
        self._saves: dict[tuple[str, str], asyncio.TimerHandle] = {}  # sliders: write the config once, not per pixel
        self._colors: asyncio.Task | None = None   # one background question about track colours at a time
        self._colors_after = 0.0                   # ... and a pause before asking again after a failure
        self.recorder = audio.UtteranceRecorder(self.mic, a["silence_seconds"], a["no_speech_timeout_seconds"],
                                                a["max_utterance_seconds"],
                                                a.get("silence_long_seconds", 2.2),
                                                a.get("long_speech_seconds", 5.0),
                                                a.get("speculate_after_seconds", 0.45))
        self.stt = STT(self.cfg["stt"])
        self._wake_score = 0.0       # последний балл openWakeWord: по нему слух имён решает, будить ли Whisper
        self._name_gate: tuple[float, bool] = (0.0, True)
        self._gave_up_vram = False   # видеопамять уже отдана игре
        self.tts = TTS(self.cfg["tts"])
        self.brain = Brain(self.cfg, on_text=self._on_brain_text, approver=self._approve, asker=self._answer_questions)
        self._chat_brains: dict[str, Brain] = {}   # по мозгу на открытый чат; закрываются после 10 минут тишины
        self._chat_closers: dict[str, asyncio.TimerHandle] = {}
        self.side: Brain | None = None             # a second session, for what must not wait for the first one
        self._side_close: asyncio.TimerHandle | None = None
        self.jobs = jobs.Jobs(on_change=lambda: self.publish(jobs=self.jobs.state()), on_done=self._job_done)
        self._subs: set[asyncio.StreamWriter] = set()
        self._notify_proc: asyncio.subprocess.Process | None = None
        # Подслушивать уведомления на шине нужно, только когда их показывает кто-то другой. Когда
        # сервером стал сам островок, они приходят ему напрямую, и второй экземпляр того же
        # уведомления — это не подстраховка, а двоение.
        self._notify_watch = True
        self._layout: dict = {}
        self._layout_proc: asyncio.subprocess.Process | None = None
        self._windows_proc: asyncio.subprocess.Process | None = None
        self._windows: list[dict] = []
        self._last_active_id = ""
        self._dock: dict = {}
        self._windows_debounce: asyncio.Task | None = None
        self._windows_pending: list[dict] | None = None
        self._windows_sent = 0.0   # когда список окон уходил на островок в последний раз
        self._trash_full = False
        self._state = "idle"
        self._workers_active = 0
        self._listen_cancel: asyncio.Event | None = None
        self._listen_task: asyncio.Task | None = None
        self._speech_q: asyncio.Queue[str | None] = asyncio.Queue()
        self._synth_ahead: dict[str, asyncio.Future] = {}  # фразы, которые уже синтезируются, пока играет предыдущая
        self._speech_gen = 0
        self._approval: asyncio.Future | None = None
        self._telegram_shell = None
        self._ask_choices: list[str] = []
        self._ask_free = False
        self._preapproved_until = 0.0  # a message draft the user approved: its "send" needs no second question
        self._last_mic_use = time.monotonic()
        self._notify_id = 0
        self._wake = None
        self._wake_cooldown = 0.0
        self._spotter = None  # детектор имени; пока нет микрофона — None
        self._names: list[str] = []  # spellings of the assistant's names, for trimming them off a woken phrase
        self._quiet_until = 0.0  # the assistant's own voice may still echo in the room
        self._event_queue: asyncio.Queue[str] = asyncio.Queue()
        self._inbox_timer: asyncio.Task | None = None
        self._wake_strict_until = 0.0  # после ложного срабатывания слушаем строже
        self._loop: asyncio.AbstractEventLoop | None = None
        # Нагрузка машины: один взгляд, помнящий предыдущий. Опрашивается, только когда кто-то
        # смотрит — островок с открытым монитором или спросивший ассистент; в покое демон не
        # тратит ничего.
        self.load = sysload.Load()
        self.load_watchers = 0
        self._load_wake = asyncio.Event()   # зритель появился — `_load_loop` просыпается
        self._sessions_until = 0.0          # страницу сессий смотрят до этого момента (monotonic); держит её QML
        self._sessions_wake = asyncio.Event()
        self._clip_seen: dict = {}       # что видели в буфере на X11, где нет наблюдателя
        self._clip_procs: list = []      # запущенные wl-paste --watch
        self._spoken = 0
        self._discard_recording = False
        self._last_toggle = 0.0
        self._holding = False
        self._voice_warned = False
        self._neural_cold_until = 0.0   # до каких пор не стучаться к нейроголосу после отказа
        self._music_started = 0.0   # music that just started speaks for itself: the reply after it stays silent
        self._offline_note = 0.0    # when the user was last told that the cloud is out
        self._fell_back_at = 0.0      # когда ушли с Claude на запасного
        self._probed_at = 0.0         # когда в последний раз спрашивали верхнего
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
        self.last_video: dict | None = None   # закрытый ролик: его можно продолжить с того же места

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
            if value == "speaking":
                events.emit("first_audio")  # `justday latency` меряет от heard до него (Р2-35)
            self.publish(state=value)
            self._warm_models(value)
            if self.music.alive and self.cfg["media"]["duck"]:  # music steps back while we talk
                spawn(self.music.duck(value in ("listening", "speaking", "approval")))

    def _voice_ping(self) -> dict:
        """Что говорит голосовой сервис о себе: поднята ли модель и давно ли молчит."""
        import json as jsonlib
        import socket as socket_mod
        import subprocess as sp

        # Служба может быть выключена по простою, и спрашивать её «спишь ли ты» через гнездо —
        # значит будить: вопрос сам бы поднял два гигабайта обратно.
        try:
            if sp.run(["systemctl", "--user", "is-active", "--quiet", "justday-voice.service"],
                      timeout=4).returncode != 0:
                return {"ok": True, "loaded": False, "stopped": True, "idle": None}
        except (OSError, sp.SubprocessError):
            pass
        try:
            with socket_mod.socket(socket_mod.AF_UNIX) as sock:
                sock.settimeout(3)
                sock.connect(str(self.tts.SOCKET))
                sock.sendall(b'{"cmd": "ping"}\n')
                return jsonlib.loads(sock.makefile().readline() or "{}")
        except (OSError, ValueError) as e:
            return {"ok": False, "error": str(e)}

    def _warm_models(self, value: str) -> None:
        """Поднять то, что понадобится через пару секунд, пока есть эти пару секунд.

        Модели отпускают память, когда ими долго не пользуются, и возвращаются небыстро: слух около
        трёх секунд, голос около десяти. Но разговор устроен так, что предупреждение всегда есть.
        Начали слушать — значит, сейчас придётся распознавать. Начали думать — значит, скоро
        отвечать вслух. Обе просьбы уходят в сторону и ничего не ждут.
        """
        if value == "listening":
            self.stt.warm()
        engine = self.cfg["tts"]["engine"]
        if value not in ("listening", "thinking") or self.silent() or engine not in ("qwen", "silero", "chatterbox"):
            return
        try:   # состояние меняется и до запуска цикла — тогда греть попросту некуда и незачем
            # `to_thread`, а не `run_in_executor`: тот отдаёт Future, а задачу делают из корутины.
            # Из-за этого прогрев падал TypeError прямо в присваивании состояния — и с ним падал
            # весь заход в прослушивание. Со стороны это выглядело так: Джарвис перестал слышать.
            if engine == "silero" or (engine == "chatterbox" and self.tts.gpu_busy()):
                extra = {"engine": "silero", "model": str(self.tts._silero_path())}
            else:
                extra = {}
            spawn(asyncio.to_thread(self.tts.nudge, "warm", **extra))
        except RuntimeError:
            pass

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
            # Острова может не быть вовсе (X11, Plasma 5, Quickshell не поставлен): тогда ответ
            # показывает обычное уведомление — иначе он существует только как звук.
            if kind == "say" and not self._subs and data.get("text"):
                self.notify(data["text"], icon="dialog-information")
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

        def send() -> None:  # в потоке: уведомления шлют и из цикла событий, а `notify-send` может зависнуть (Р-33)
            try:
                out = subprocess.run([*cmd, "JustDay", body[:300]], capture_output=True, text=True, timeout=5).stdout
                self._notify_id = int(out.strip() or 0)
            except Exception:
                pass

        threading.Thread(target=send, daemon=True, name="notify").start()

    # ---------------- speech output ----------------
    def silent(self) -> str:
        """Why the answer is only shown, not spoken: "off", "game", "focus", or "" when the voice is on."""
        t = self.cfg["tts"]
        if t["engine"] == "none" or t.get("muted"):
            return "off"
        if t.get("mute_in_games", True) and desktop.running_game():
            return "game"
        if focus.active(self.cfg.get("focus", {}).get("schedule", [])):
            return "focus"
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

    async def run_scene(self, scene: dict) -> str:
        """Сценарий целиком: окна, команды, музыка, тишина. Без модели и без сети."""
        loop = asyncio.get_running_loop()
        self.publish(detail=scene["name"], kind="tool")
        result = await loop.run_in_executor(None, scenes.run, scene)
        if scene.get("silent") is not None:
            await self.set_voice(not scene["silent"])
        if scene.get("music"):
            spawn(self.play_library(shuffle=True) if scene["music"] in ("моя", "library", "фонотека")
                  else self.play_music(scene["music"]))
        said = scene.get("say") or scenes.summary(result)
        events.emit("scene", name=scene["name"], opened=result["opened"], closed=result["closed"])
        self.brain.note(f"[Сценарий «{scene['name']}» уже выполнен мгновенно, без тебя: "
                        f"{scenes.summary(result)}. Не повторяй эти действия.]")
        await self.say(said)
        return said

    async def session_switch(self, what: str) -> str:
        """«Я ушёл» — remember the open applications and ask them to close; «я вернулся» — open them again.

        Closing is asked about first: the list is what the user will get back, and a window that has
        unsaved work in it is better mentioned before it is told to close."""

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
            self._synth_in_advance(s)

    async def say(self, text: str, force: bool = False) -> None:
        await self._on_brain_text(text, force)

    def _synth_in_advance(self, sentence: str) -> None:
        """Голос, который синтезирует фразу целиком (Silero, espeak), начинает следующую, пока играет
        предыдущая: раньше каждая ждала конца предыдущей и потом ещё 0,1–0,5 с собственного синтеза (Р-53).
        Потоковые голоса (Qwen, ElevenLabs) не тронуты: они и так играют по мере генерации."""
        engine = self.tts.cfg["engine"]
        if engine in ("qwen", "elevenlabs", "chatterbox", "none") or sentence in self._synth_ahead:
            return
        try:
            self._synth_ahead[sentence] = asyncio.get_running_loop().run_in_executor(None, self.tts.synth, sentence)
        except RuntimeError:  # цикла нет — синтезировать некому, воркер сделает сам
            pass

    def stop_speaking(self) -> None:
        self._synth_ahead.clear()  # не cancel: ждущий воркер получил бы CancelledError и умер бы вместе с голосом
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
                # Отказ ElevenLabs (кончились кредиты, голос не для бесплатного тарифа) — сразу Silero.
                # Раньше запасным был Qwen: 3,4 ГБ видеопамяти и полминуты холодного старта на
                # каждый такой отказ. И не стучаться к нему каждой фразой, пока не остынет.
                if (engine == "elevenlabs" and time.monotonic() >= self._neural_cold_until
                        and await self._speak_stream(sentence, gen, "elevenlabs")):
                    continue
                if (engine == "qwen" and time.monotonic() >= self._neural_cold_until
                        and await self._speak_stream(sentence, gen, "qwen")):
                    continue
                if (engine == "chatterbox" and time.monotonic() >= self._neural_cold_until and not self._gpu_taken()
                        and await self._speak_stream(sentence, gen, "chatterbox")):
                    continue
                ahead = self._synth_ahead.pop(sentence, None)
                pcm = await (ahead or loop.run_in_executor(None, self.tts.synth, sentence))
                if gen != self._speech_gen or not len(pcm):
                    continue
                self.state = "speaking"
                await self.player.play(pcm, self.tts.rate)
                if self.state == "speaking":
                    self.state = "thinking" if self.brain.busy else "idle"
            except Exception:
                log.exception("speech failed")

    def _gpu_taken(self) -> bool:
        """Chatterbox делит видеокарту с игрой или монтажом — и тогда лагают оба. Его просьба 7 октября:
        «если видеокарта сильно используется — пусть переключается на Silero, чтобы не лагало»."""
        return bool(desktop.running_game() or self.tts.gpu_busy())

    async def _speak_stream(self, sentence: str, gen: int, engine: str) -> bool:
        """Stream one sentence from a voice that generates as it speaks (the local neural service or ElevenLabs).

        False = this voice is unavailable, and the caller falls back to the next one."""
        if engine == "elevenlabs":
            stream, rate, native = self.tts.eleven_stream(sentence), self.tts.ELEVEN_RATE, max(0.7, min(1.2, self.tts.speed))
        else:
            # Нейроголос набирает темп сам, по словесной просьбе (`instruct`), но
            # на глаз: от фразы к фразе выходит то быстрее, то медленнее. Поэтому
            # большую часть ускорения берёт на себя модель, а остаток — мягкое
            # растяжение: 1,07 вместо 1,2 слышно несравнимо меньше.
            stream, rate = self.tts.stream(sentence), self.tts.NEURAL_RATE
            native = self.tts.native_pace() if engine == "qwen" else 1.0  # Chatterbox просьб о темпе не понимает
        stretch = audio.Stretcher(self.tts.speed / native, rate)
        try:
            first = await stream.__anext__()
        except StopAsyncIteration:
            return True
        except OSError as e:
            if not self._voice_warned:
                self._voice_warned = True
                log.warning("%s voice unavailable (%s), falling back", engine, e)
            # И больше не стучаться к нему каждой фразой. Нейроголос падает не разово: кончилась
            # видеопамять — значит кончилась и на следующую фразу, а ожидание отказа человек
            # слышит как задержку перед каждым словом. Это и есть «голос лагает».
            self._neural_cold_until = time.monotonic() + 60 * float(
                self.cfg["tts"].get("retry_minutes", 10) or 0)
            return False
        self._voice_warned = False
        self._neural_cold_until = 0.0
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
        """Есть ли с чего слушать. Без установленного распознавания речи микрофон бесполезен:
        кнопка «говорить» открывает поле ввода, а не запись, — иначе первое же слово упало бы
        в ImportError. Доставить: justday parts add speech."""
        return self.cfg["audio"].get("microphone", True) and parts.have("speech")

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
        """Одно прослушивание. Любая беда внутри — и состояние всё равно возвращается: раньше ошибка
        распознавания (CUDA после сна) оставляла «transcribing» навсегда, и _wake_by_name отказывался
        будить до рестарта (Р-13)."""
        try:
            await self._listen_body(followup, prefill)
        except Exception as e:
            log.exception("listening failed")
            events.emit("listen_failed", error=repr(e))
            if self.state in ("listening", "transcribing"):
                self.state = "thinking" if self.brain.busy else "idle"
            await self.earcon("error")

    async def _listen_body(self, followup: bool, prefill=None, carry: str = "") -> None:
        self.mic.start()
        self._last_mic_use = time.monotonic()
        self.publish(followup=followup)  # остров: продолжение разговора не гасит ответ на экране
        self.state = "listening"
        self._listen_cancel = asyncio.Event()
        self._discard_recording = False
        if not followup and prefill is None:  # mid-phrase after the name: a beep would land in the recording
            await self.earcon("listen")
        events.emit("listen_start", followup=followup, source=self._activation)
        rec = self.recorder
        if followup:
            rec = audio.UtteranceRecorder(self.mic, rec.silence_s, self.cfg["audio"]["followup_seconds"], rec.max_s,
                                          rec.silence_long_s, rec.long_after_s, rec.speculate_after_s)
        loop = asyncio.get_running_loop()
        early: list[asyncio.Future] = []  # раннее распознавание: последнее запущенное, годится ли — решает rec.speculated

        def speculate(pcm: np.ndarray) -> None:
            fut = loop.run_in_executor(None, self.stt.transcribe, pcm)
            fut.add_done_callback(lambda f: f.cancelled() or f.exception())  # брошенное не должно ругаться в журнал
            early.append(fut)

        def level(frame: np.ndarray) -> None:
            rms = float(np.sqrt((frame.astype(np.float32) ** 2).mean())) / 32768.0
            db = 20 * np.log10(rms + 1e-9)  # −50 dBFS (room) … −20 dBFS (loud speech) → 0…1, like a VU meter
            loop.call_soon_threadsafe(lambda: self.publish(level=round(min(1.0, max(0.0, (db + 50) / 30)), 3)))

        self.mic.subscribe(level)
        try:
            pcm = await rec.record(self._listen_cancel, prefill, speculate)
        finally:
            self.mic.unsubscribe(level)
        self._last_mic_use = time.monotonic()
        after = "thinking" if self.brain.busy else "idle"
        if self._discard_recording:
            events.emit("listen_cancelled")
            self.state = after
            return
        if pcm is None or len(pcm) < audio.RATE * 0.3:
            events.emit("listen_empty", source=self._activation)
            if carry:  # договаривать никто не стал: уходит то, что есть
                self.state = after
                await self.handle_utterance(carry)
                return
            # Разбудили и никто не заговорил — скорее всего, показалось. Следующие
            # полминуты слово пробуждения слушаем строже: ложные срабатывания идут
            # сериями (звук из колонок, чужой голос в ролике), а настоящий зов после
            # такого всё равно проходит — по кнопке или чуть громче.
            if self._activation == "wake":
                self._wake_strict_until = time.monotonic() + 30
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
        text = None
        if rec.speculated is not None and early:
            try:
                text = await early[-1]  # распознано, пока доходила пауза: человек после этого не заговорил
                events.emit("heard_early")
            except Exception as e:  # раннее не вышло (видеокарта, память) — обычный путь ещё впереди
                log.info("раннее распознавание упало (%s): распознаю заново", type(e).__name__)
        if text is None:
            text = await asyncio.get_running_loop().run_in_executor(None, self.stt.transcribe, pcm)
        if gen != self._cancel_gen:  # cancelled while transcribing: forget what was said
            events.emit("listen_cancelled", text=text)
            return
        self.state = "thinking" if self.brain.busy else "idle"
        if self._activation == "wake" and self._names:
            text = namespot.strip_name(text, self._names)
        events.emit("heard", text=text, seconds=round(len(pcm) / audio.RATE, 1))
        if carry and text:
            text = f"{carry} {text}"   # продолжение: одна просьба из двух кусков
        if not text:
            if carry:
                await self.handle_utterance(carry)
                return
            await self.earcon("error")
            return
        if not carry and fastpath.unfinished(text):
            # «поставь таймер на…» — пауза пришла раньше конца мысли: слушаем ещё раз и склеиваем
            events.emit("heard_unfinished", text=text)
            await self._listen_body(True, None, carry=text)
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
        if fastpath.wants_fresh_session(text):
            await self.brain.new_session()
            return t("Начинаю заново.")
        if (scene := scenes.match(text)) is not None:
            return await self.run_scene(scene)
        if (what := fastpath.session_switch(text)) is not None:
            return await self.session_switch(what)
        if (levels := await asyncio.get_running_loop().run_in_executor(None, volume.plan, text)) is not None:
            return await self._set_volumes(text, levels)
        if re.match(r"^верни (удален\w+|только что удален\w+) (трек|песню|музыку)$", fastpath._clean(text)):
            name = await asyncio.to_thread(media.untrash_last)
            return t("Вернул: {name}", name=name) if name else t("Возвращать нечего.")
        if re.match(r"^(открой |покажи )?(микшер|регулятор(ы)? звука|громкость программ)$", fastpath._clean(text)):
            self.publish(panel="mixer")  # «включи звук» сюда не попадает: это не микшер, а громкость
            return ""
        if re.match(r"^(включи|поставь|запусти|играй) (это )?(из буфера|что (я )?скопировал\w*|ссылку из буфера)$", fastpath._clean(text)):
            return await self._play_from_clipboard()
        if await self.media_fast(text) or await self.reminder_fast(text):
            return ""
        if (said := fastpath.small_talk(text)) is not None:
            await self.say(said)
            return said
        if what := chitchat.kind(text):
            said = await asyncio.get_running_loop().run_in_executor(None, chitchat.reply, what, text, self.cfg)
            await self.say(said)
            return said
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
        if calendar_lane.wants(text):
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

    async def _set_volumes(self, text: str, levels: list) -> str | None:
        """«Discord 50, музыку 20»: все части сразу, один ответ на всё (Р-48)."""
        loop = asyncio.get_running_loop()
        for a in levels:
            # Не вышло (wpctl/pactl упали) — не врём «готово»: фраза уходит мозгу, он скажет как есть.
            if a.kind == "music":
                ok = (await self.media_control("volume", a.level)).get("ok")
            else:
                ok = await loop.run_in_executor(None, volume.apply, a)
            if not ok:
                return None
        said = volume.phrase(levels)
        events.emit("fast", text=text, desc=said)
        self.brain.note(f"[Уже выполнено мгновенно, без тебя: «{text}» → громкость: {said}. Не повторяй.]")
        await self.say(said)
        return said

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

    async def dictate(self, path: str, to_inbox: bool = False, created: float = 0.0) -> dict:
        """Надиктованное с телефона: распознать здесь и выполнить, как сказанное вслух.

        `to_inbox` — запись, наговоренная без связи: выполнять её сейчас поздно и опасно
        («выключи компьютер», сказанное час назад, к делу уже не относится). Такое ложится
        в список сообщений, и ассистент разберётся с ним, когда доложит хозяину."""
        loop = asyncio.get_running_loop()
        self.state = "transcribing"
        try:
            text = await loop.run_in_executor(None, self.transcribe_file, path)
        finally:
            self.state = "thinking" if self.brain.busy else "idle"
        if not text:
            events.emit("dictate_empty")
            return {"ok": False, "error": t("Не расслышал.")}
        if to_inbox:
            rec = inbox.add(text, "phone-voice", created)
            events.emit("inbox_add", source="phone-voice", text=text[:200])
            self._inbox_soon()
            return {"ok": True, "text": text, "id": rec["id"], "pending": len(inbox.pending())}
        events.emit("heard", text=text, source="phone")
        self.publish(kind="heard", detail=text)
        local = await self.handle_local(text, "phone")
        reply = local if local is not None else await self.chat_ask("phone", text)
        return {"ok": True, "text": text, "result": reply or t("сделано")}

    async def _telegram_loop(self) -> None:
        """Слушать телеграм длинным опросом и отвечать тем же Джарвисом, что и дома.

        Почему не вебхук: вебхук потребовал бы открытого наружу порта, а наше правило — только
        127.0.0.1. Длинный опрос ходит наружу сам и ничего не слушает.

        Чужие сообщения выбрасываются молча (`telegram.mine`): бот открыт всему интернету, и без
        этой проверки любой, кто найдёт его имя, писал бы прямо в мозг — с почтой, окнами и правом
        запускать программы.
        """
        from . import telegram as tg

        if not tg.ready():
            return
        self._tg_gate = tg.PinGate()
        loop = asyncio.get_running_loop()
        offset = 0
        quiet = 0.0
        while True:
            try:
                got = await loop.run_in_executor(None, tg.updates, offset)
                quiet = 0.0
            except Exception as e:                  # сеть рвётся; молчать об этом вечно нельзя
                quiet = min(60.0, quiet * 2 or 5.0)
                log.debug("телеграм: %s", e)
                await asyncio.sleep(quiet)
                continue
            for upd in got or []:
                offset = max(offset, int(upd.get("update_id", 0)) + 1)
                if upd.get("callback_query"):
                    # Кнопка «Разрешить» — это тоже команда: пока замок PIN закрыт, она недействительна.
                    if self._telegram_shell and self._tg_gate.is_open():
                        with contextlib.suppress(Exception):
                            await self._telegram_shell.callback(upd)
                    continue
                if (where := tg.location(upd)) is not None:
                    if self._tg_gate.is_open():     # чужая рука с угнанным аккаунтом не «перевозит» владельца
                        geo.remember(*where)        # координаты нужны наблюдателю; в мозг они не идут
                    continue
                if not tg.owned(upd):
                    continue
                verdict = self._tg_gate.check(tg.mine(upd))
                if verdict != "open":
                    msg = upd.get("message") or {}
                    with contextlib.suppress(Exception):
                        if verdict in ("unlocked", "denied"):   # PIN не должен оставаться в переписке
                            await loop.run_in_executor(None, tg.call, "deleteMessage",
                                                       {"chat_id": tg.chat(), "message_id": msg.get("message_id")})
                        await loop.run_in_executor(None, tg.send, tg.PIN_REPLY[verdict])
                    continue
                if self._telegram_shell is None:
                    from .telegram_shell import TelegramShell
                    self._telegram_shell = TelegramShell(self)
                try:
                    handled = await self._telegram_shell.message(upd)
                except Exception:
                    log.exception("телеграм-оболочка: команда не удалась")
                    continue
                if handled:
                    continue
                text = tg.mine(upd)
                if not text:
                    continue
                events.emit("heard", text=text, source="telegram")
                try:
                    local = await self.handle_local(text, "telegram")
                    reply = local if local is not None else await self.chat_ask("telegram", text)
                except Exception:
                    log.exception("телеграм: ход не удался")
                    reply = "Не получилось — посмотри журнал."
                with contextlib.suppress(Exception):
                    await loop.run_in_executor(None, tg.send, reply or "сделано")

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

    # То, что демон меняет в настройках мозга на ходу: модель под задачу, запасной поставщик по лимиту.
    _BRAIN_LIVE = ("provider", "model", "effort")

    def _adopt(self, new: dict) -> None:
        """Взять новые настройки, не подменяя объект.

        Конфиг один на всех: его держат мозг, голос, слух. Раньше reload клал в self.cfg новый
        словарь, а мозг оставался со старым — и после первого же щелчка в настройках выбор модели
        писал в словарь, который мозг больше не читал: 0 смен модели из 16 до рестарта (Р-5).
        Поэтому разделы обновляются на месте. Модель и поставщика, выбранных на ходу, перезагрузка
        не трогает, если человек не менял их в файле: щелчок по громкости не должен возвращать
        мозг с запасного поставщика на тот, у которого кончился лимит."""
        last = getattr(self, "_from_file", None) or new
        live = {k: self.cfg["brain"].get(k) for k in self._BRAIN_LIVE
                if new["brain"].get(k) == last["brain"].get(k) and k in self.cfg["brain"]}
        self._from_file = copy.deepcopy(new)
        for key, value in new.items():
            if isinstance(value, dict) and isinstance(self.cfg.get(key), dict):
                self.cfg[key].clear()
                self.cfg[key].update(value)
            else:
                self.cfg[key] = value
        self.cfg["brain"].update(live)

    @staticmethod
    def _wake_names(cfg: dict) -> list[str]:
        """Имена, на которые просыпаемся: свои из настроек, а если пусто — имя ассистента."""
        return [n for n in (cfg["wakeword"].get("wake_names") or [cfg["user"]["assistant_name"]]) if n]

    def _apply_names(self, cfg: dict) -> None:
        u = cfg["user"]
        self._names = namespot.spellings([n for n in [u["assistant_name"], *u.get("assistant_aliases", [])] if n])
        self._spotter.variants = namespot.spellings(self._wake_names(cfg))

    def reload_settings(self) -> list[str]:
        """Apply config changes without a restart where possible; returns the sections that still need one."""
        new = config.load()
        old = getattr(self, "_from_file", None) or copy.deepcopy(self.cfg)
        self._adopt(new)
        restart: list[str] = []
        a = new["audio"]
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
            spawn(self._reconnect_brain())
        self.stt.vocabulary = island.vocabulary(new)
        # Имя будится без перезапуска (ниже): wake_names не повод пересобирать детектор
        sans = lambda c: {k: v for k, v in c["wakeword"].items() if k != "wake_names"}  # noqa: E731
        restart += [s for s in ("brain", "stt", "local_llm") if new[s] != old[s]]
        if sans(new) != sans(old):
            restart.append("wakeword")
        if new["user"].get("language") != old["user"].get("language"):
            restart.append("language")
        names = lambda c: (c["user"]["assistant_name"], c["user"].get("assistant_aliases"),  # noqa: E731
                           c["wakeword"].get("wake_names"))
        if self._spotter and names(new) != names(old):  # новое имя подхватывается на лету, без перезапуска
            self._apply_names(new)
        elif self._names and names(new) != names(old):
            restart.append("wakeword")
        # Plasma system OSD ↔ island.show_osd (and popups island mode via sync call sites).
        if (new["island"].get("show_osd", True) != old["island"].get("show_osd", True)
                or new["island"].get("system_popups", False) != old["island"].get("system_popups", False)):
            try:
                notifications.sync_plasma_osd(
                    show_osd=new["island"].get("show_osd", True),
                    system_popups=new["island"].get("system_popups", False),
                )
            except Exception:
                log.exception("plasma OSD sync")
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
        self.publish(detail=t("Почта · локально"), kind="tool", icon="mail-message")  # без значка крутилось кольцо
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
        await self._try_home()
        # Одна модель на разговор: раньше после ответа демон возвращался к модели из конфига (sonnet),
        # а следующий ход снова уходил на лёгкую — два переподключения `claude --resume` по 1–1,5 с и
        # сброшенный кэш промпта на каждом ходу (Р-24). Теперь выбранная модель остаётся, пока
        # следующий выбор или «НУЖНА: …» не скажут другое.
        await self._pick_model(text)
        try:
            reply = await self.brain.ask(text, source=source)
            # Ничего не говоря вслух про пересадку: человек услышит только ответ.
            if (want := dispatch.hands_up(reply)) and await self._lift(want):
                reply = await self.brain.ask(text, source=source)
            self._cloud_down_until = 0.0
        except Exception as e:
            if gen != self._cancel_gen:
                return ""
            events.emit("turn_failed", error=repr(e))
            # Лимит и обрыв связи — разные беды. При лимите есть куда пойти: бесплатные модели в
            # том же интернете работают. При обрыве идти некуда, и честнее сказать это сразу.
            moved = await self._fall_back(repr(e))
            if moved:
                try:
                    reply = await self.brain.ask(text, source=source)
                except Exception as again:
                    events.emit("turn_failed", error=repr(again))
                    self._cloud_down_until = time.monotonic() + 300
                    reply = await self.offline_turn(text)
            elif isinstance(e, brain_mod.BrainError) and not fallback.looks_like_limit(str(e)):
                # Модель ответила, но ошибкой: связь есть, и запирать облако на пять минут незачем.
                # Сырой текст ошибки вслух не читаем — он для журнала, а не для ушей.
                reply = t("У модели что-то сломалось, попробуй ещё раз.")
                await self.say(reply)
            else:
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







    # ---------------- background: wake word, mic idle, worker reports ----------------
    def _wake_threshold(self) -> float:
        """Насколько уверенно должно прозвучать слово пробуждения прямо сейчас.

        Пока играет музыка или видео, микрофон слышит колонки — «Джарвис» из ролика
        будил ассистента наравне с хозяином. И сразу после пустого пробуждения планка
        тоже выше: такие срабатывания приходят сериями."""
        w = self.cfg["wakeword"]
        base = float(w["threshold"])
        loud = bool(self.island_video) or bool(self._player_state and not self._player_state.get("paused"))
        if loud:
            base = max(base, float(w.get("threshold_while_playing") or base))
        if time.monotonic() < self._wake_strict_until:
            base = min(0.95, base + 0.15)
        return base

    def _name_spotting_allowed(self) -> bool:
        """В игре и при выключенном голосе Whisper имён не слушает: он занимал бы видеопамять игры (Р-30).
        Кадры идут каждые 80 мс, а `silent()` обходит /proc — поэтому ответ живёт две секунды."""
        now = time.monotonic()
        if now - self._name_gate[0] > 2.0:
            self._name_gate = (now, not self.silent())
        return self._name_gate[1]

    def _name_min_prob(self) -> float:
        """Та же строгость, что и у слова пробуждения, но для имени, услышанного в речи."""
        loud = bool(self.island_video) or bool(self._player_state and not self._player_state.get("paused"))
        base = namespot.MIN_NAME_PROB
        if loud:
            base = 0.65
        if time.monotonic() < self._wake_strict_until:
            base = max(base, 0.7)
        return base

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
                self._wake_score = 0.0
                return
            score = self._wake_score = float(max(self._wake.predict(frame).values()))
            if score >= self._wake_threshold():
                self._wake_cooldown = time.monotonic() + 2.5
                self._wake.reset()
                events.emit("wakeword", score=round(float(score), 2))
                loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self.toggle(source="wake")))

        self.mic.subscribe(on_frame)
        if w.get("names", True):
            u = self.cfg["user"]
            # only the main name wakes it («Джарвис»); the other names are for talking, not for waking
            names = self._wake_names(self.cfg)
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

            spotter = namespot.NameSpotter(self.stt.transcribe_head, names, lambda: self.mic.seq, on_name,
                                           min_prob=self._name_min_prob,
                                           floor=lambda: float(self.cfg["wakeword"].get("name_candidate", 0.0)))
            self._spotter = spotter
            self.mic.subscribe(lambda f: spotter.feed(
                f, self.state in ("idle", "thinking") and time.monotonic() > max(self._quiet_until, self._wake_cooldown)
                and self._name_spotting_allowed(), self._wake_score))
        self.mic.start()





    # Сколько держать паузу между двумя рассылками списка окон. Буря геометрии (окно тянут за
    # угол) присылает десятки списков в секунду, и каждый — перерисовка дока.
    WINDOWS_QUIET = 0.18




    async def _observe(self) -> None:
        """Раз в минуту: пора ли Джарвису написать первым (observer.py)."""
        try:
            await observer.tick(calendar_lane.between, self._nudge, self.cfg, travel=geo.minutes_to if geo.here() else None)
        except Exception as e:
            log.info("наблюдатель: %s", type(e).__name__)

    async def _nudge(self, text: str) -> None:
        """Сказать ему то, что наблюдатель счёл нужным: везде, где это бесплатно. Звонок — нет, он стоит денег."""
        from . import server, telegram

        events.emit("nudge", text=text)
        self.notify(text, "appointment-soon")
        if (self.cfg.get("observer") or {}).get("telegram", True):
            try:
                await asyncio.get_running_loop().run_in_executor(None, telegram.send, text)
            except Exception as e:     # бота нет или он не настроен — остаются уведомление и голос
                log.info("наблюдатель: телеграм не отправил (%s)", type(e).__name__)
        if server.here() is True:      # за компьютером — ещё и вслух; в комнате без него голос никому не нужен
            await self.say(text)




    async def _welcome_back(self) -> None:
        """Человек вернулся и отпер сеанс — вернуть ему машину, не дожидаясь команды.

        Он пришёл домой и застал погашенный монитор: режим сервера держал экраны, пока его не
        выключили руками. Ввести пароль — это и есть «я вернулся», другого знака не нужно.
        Поэтому пока режим включён, мы раз в несколько секунд смотрим на замок, и как только он
        снят, отдаём всё обратно: экраны, звук, музыку, рабочий стол.
        """
        from . import server

        st = server.state()
        if st.get("on") and st.get("waiting"):
            # Режим включили, пока человек сидел за машиной, и экран ему оставили. Отошёл — гасим.
            # Замка ещё не было, так что «сеанс отперт» здесь не значит «вернулся».
            if await asyncio.get_running_loop().run_in_executor(None, server.tick):
                log.info("человек отошёл — режим сервера погасил экраны")
            return
        # Без замка отпертый сеанс ничего не говорит: с `lock: false` режим выключался бы сам через
        # десять секунд после включения.
        if not st.get("locked") or time.monotonic() - getattr(self, "_lock_seen", 0) < 5:
            return
        self._lock_seen = time.monotonic()
        try:
            done = await asyncio.get_running_loop().run_in_executor(
                None, lambda: subprocess.run(
                    ["loginctl", "show-session", os.environ.get("XDG_SESSION_ID", "auto"),
                     "-p", "LockedHint"], capture_output=True, text=True, timeout=5))
        except (OSError, subprocess.SubprocessError):
            return
        if "LockedHint=no" not in done.stdout:
            return
        # Сеанс отперт — значит человек тут. Ждём чуть-чуть: он мог отпереть и сразу уйти обратно.
        if not getattr(self, "_unlocked_at", 0):
            self._unlocked_at = time.monotonic()
            return
        if time.monotonic() - self._unlocked_at < 10:
            return
        self._unlocked_at = 0.0
        await asyncio.get_running_loop().run_in_executor(None, server.off)
        log.info("человек вернулся — режим сервера выключен")
        self.notify(t("С возвращением. Вернул экраны, звук и рабочий стол."), icon="dialog-information")

    HOUSEKEEPING_EVERY = 2.0
    HEARTBEAT_EVERY = 5.0   # островок считает демон мёртвым после 12 с тишины

    async def _heartbeat(self) -> None:
        """Пинг островку — отдельной задачей. В круге _housekeeping он стоял в хвосте, после git по сети,
        календаря, погоды и почты; круг шёл дольше 12 с, и островок объявлял демон мёртвым и сбрасывал
        подписку (Р-15)."""
        while True:
            await asyncio.sleep(self.HEARTBEAT_EVERY)
            self.publish(ping=1, state=self.state)

    def _focus_now(self) -> dict | None:
        return focus.current(self.cfg.get("focus", {}).get("schedule", []))

    def _publish_focus(self) -> None:
        """Островку — какое окно тишины идёт, но только при смене: круг домашних дел короче минуты."""
        cur = self._focus_now()
        if cur != getattr(self, "_focus_sent", None):
            self._focus_sent = cur
            self.publish(focus=cur)

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
                await self._welcome_back()
                # Подняться обратно по лестнице можно и молча, не дожидаясь следующей просьбы: лимит
                # возвращается сам по себе, и ждать с ним до разговора незачем.
                await self._try_home()
                await self._diary_maybe()
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

    # ---------------- сообщения с телефона ----------------
    def _inbox_soon(self, delay: float = 4.0) -> None:
        """Доложить о накопившемся — но не мгновенно.

        Сообщения приходят пачкой: телефон, увидев компьютер в сети, отдаёт всё, что
        накопил в дороге. Небольшая пауза собирает их в один доклад вместо пяти."""
        if self._inbox_timer and not self._inbox_timer.done():
            self._inbox_timer.cancel()
        self._inbox_timer = spawn(self._inbox_report(delay))

    async def _inbox_report(self, delay: float) -> None:
        await asyncio.sleep(delay)
        items = inbox.pending()
        if not items:
            return
        # Ждём, пока ассистент освободится: перебивать им же начатую работу незачем,
        # сообщения и так пролежали дольше.
        while self.brain.busy or self.state != "idle":
            await asyncio.sleep(5)
            if not inbox.pending():
                return
        items = inbox.pending()
        inbox.mark_reported([i["id"] for i in items])
        self.publish(kind="tool", detail=t("Сообщения с телефона: {n}", n=len(items)))
        one = len(items) == 1
        self._event_queue.put_nowait(
            f"[Событие JustDay] Пока тебя не было, с телефона {'пришла просьба' if one else 'пришли просьбы'}:\n"
            f"{inbox.summary(items)}\n"
            "Доложи хозяину коротко, своими словами («вот что мне передали с телефона…»), и сам реши по смыслу: "
            "что-то сделай сразу, что-то занеси в планы (`justday plan add …`), о чём-то спроси. "
            "Если просьба уже неактуальна по времени — скажи об этом и не делай.")































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
                    self.publish(sessions=got)
                except Exception:
                    log.debug("не смог прочитать сессии", exc_info=True)
                seen, at = fingerprint, time.monotonic()
            await asyncio.sleep(self.SESSIONS_TICK * Daemon._game_slowdown(self))

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
            await asyncio.sleep(2.0 * Daemon._game_slowdown(self))
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
                        stderr=asyncio.subprocess.DEVNULL)
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
        elif self.cfg["audio"].get("microphone", True) and not parts.have("speech"):
            # Микрофон в настройках есть, а распознавания в окружении нет: молча превращаться
            # в «кнопка ничего не делает» нельзя — так и выглядела бы поломка.
            log.warning("%s", parts.missing_note("speech"))
            self.notify(parts.missing_note("speech"), icon="audio-input-microphone")
        loop.run_in_executor(None, self.tts.load)
        from . import manage

        await loop.run_in_executor(None, manage.refresh_hotkeys)  # первый снимок настроек уже с клавишами
        await self.brain.start()
        if await self.music.attach():  # music that kept playing through a daemon restart
            log.info("music player reattached")
        self._reschedule()  # alarms survive a restart
        self._setup_wakeword()
        spawn(self._housekeeping())
        spawn(self._heartbeat())
        spawn(self._load_loop())
        spawn(self._sessions_loop())
        spawn(self._clip_watch())
        spawn(self._file_index_loop())
        if shutil.which("dbus-monitor"):
            spawn(self._watch_notifications())
        spawn(self._watch_windows())
        spawn(self._watch_layout())
        spawn(self._watch_brightness())
        spawn(self._telegram_loop())
        spawn(self._cpu_loop())
        # Каталог дока уходит по живому сокету. Перезапускать ради него оболочку не надо.
        async def _warm_dock() -> None:
            # Пробуем, пока не опознаются закреплённые значки: пустой док поверх острова не шлём.
            try:
                pins = await loop.run_in_executor(None, dock.pinned)
            except Exception:
                pins = []
            delay = 0.0
            last = None
            for _ in range(8):
                if delay:
                    await asyncio.sleep(delay)
                delay = 1.5
                try:
                    got = await loop.run_in_executor(None, dock.catalog)
                except Exception:
                    log.exception("dock catalog")
                    continue
                if not isinstance(got, dict):
                    continue
                last = got
                if got.get("items") or not pins:
                    self._dock = got
                    self.publish(dock=got)
                    return
            if isinstance(last, dict) and (last.get("items") or []):
                self._dock = last
                self.publish(dock=last)
        spawn(_warm_dock())
        # Остров — единственное место для уведомлений, если так попросили.
        want_popups = bool(self.cfg["island"].get("system_popups", False))
        if notifications.system_popups().get("popups") != want_popups:
            await loop.run_in_executor(None, notifications.system_popups, want_popups)
        # Mute Plasma volume/brightness/keyboard OSD when JustDay show_osd owns the HUD.
        await loop.run_in_executor(
            None,
            lambda: notifications.sync_plasma_osd(
                show_osd=self.cfg["island"].get("show_osd", True),
                system_popups=want_popups,
            ),
        )
        events.emit("daemon_ready", socket=str(config.SOCKET_PATH), mic=self.mic.source, wakeword=bool(self._wake))
        self._inbox_soon(delay=20)  # то, что оставили с телефона, пока компьютера не было
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
        if self._windows_proc and self._windows_proc.returncode is None:
            self._windows_proc.kill()
        desktop.watch_stop()
        for watcher in self._clip_procs:      # наблюдатели буфера живут ровно столько, сколько демон
            if watcher.returncode is None:
                watcher.kill()
        self.mic.stop()
        try:
            await asyncio.wait_for(self.brain.stop(), 5)
        except Exception:
            log.exception("brain stop")
        events.emit("daemon_stopped")
        logging.shutdown()
        os._exit(0)  # executor threads (STT/TTS/mail calls) must not keep a restart waiting


def log_file_handler(path: Path | None = None, max_bytes: int = 5 * 1024 * 1024) -> logging.Handler:
    """Журнал демона с ротацией (Р-37): `justday.log` вырос до 11 МБ — whisper пишет строки на каждый прогон, —
    а читать его целиком всё труднее. Прошлые части лежат рядом как `justday.log.1…3`; уже накопленный большой
    файл при первой записи просто переименуется в `.1`, а не пропадёт."""
    from logging.handlers import RotatingFileHandler

    return RotatingFileHandler(path or config.STATE_DIR / "justday.log", maxBytes=max_bytes, backupCount=3,
                               encoding="utf-8")


def main() -> None:
    config.ensure_dirs()
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(name)s %(levelname)s %(message)s",
        handlers=[logging.StreamHandler(), log_file_handler()],
    )
    try:
        # numpy's OpenBLAS keeps a thread per core and wakes them all for every 80 ms of microphone audio:
        # on a 20-thread CPU that alone kept the idle daemon at half a core. Our arrays are tiny: one thread.
        from threadpoolctl import threadpool_limits
        threadpool_limits(1, user_api="blas")
    except ImportError:
        pass
    asyncio.run(Daemon().run())
