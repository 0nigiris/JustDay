"""Microphone capture and playback through PipeWire's own CLI tools (pw-record / pw-play).

Using the PipeWire tools avoids PortAudio device-name guessing and lets us target a
specific source node (e.g. a USB mic) even when the system default is a virtual mic.
"""
from __future__ import annotations

import asyncio
import logging
import shutil
import subprocess
import threading
import time

import numpy as np

log = logging.getLogger("justday.audio")

RATE = 16000
FRAME = 1280  # 80 ms — the frame size openWakeWord expects


def find_node(substring: str, kind: str = "sources") -> str | None:
    """Resolve a substring (e.g. 'Samson') to a full PipeWire node name."""
    if not substring:
        return None
    out = subprocess.run(["pactl", "list", "short", kind], capture_output=True, text=True).stdout
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) > 1 and substring.lower() in parts[1].lower() and not parts[1].endswith(".monitor"):
            return parts[1]
    return None


class Microphone:
    """Continuous 16 kHz mono int16 stream. Frames are delivered to subscribers from a reader thread."""

    def __init__(self, source_substring: str = ""):
        self.source = find_node(source_substring) if source_substring else None
        self._proc: subprocess.Popen | None = None
        self._thread: threading.Thread | None = None
        self._subscribers: list = []
        self._lock = threading.Lock()
        self.seq = 0  # number of the frame being delivered (read it inside a subscriber)

    def start(self) -> None:
        if self._proc and self._proc.poll() is None:
            return
        cmd = ["pw-record", "--rate", str(RATE), "--channels", "1", "--format", "s16", "--raw"]
        if self.source:
            cmd += ["--target", self.source]
        cmd.append("-")
        log.info("mic start: %s", " ".join(cmd))
        self._proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
        self._thread = threading.Thread(target=self._reader, daemon=True, name="mic")
        self._thread.start()

    def stop(self) -> None:
        if self._proc:
            self._proc.terminate()
            self._proc = None

    def _reader(self) -> None:
        proc = self._proc
        nbytes = FRAME * 2
        while proc and proc.poll() is None:
            data = proc.stdout.read(nbytes)
            if not data or len(data) < nbytes:
                break
            frame = np.frombuffer(data, dtype=np.int16)
            self.seq += 1
            with self._lock:
                subs = list(self._subscribers)
            for cb in subs:
                try:
                    cb(frame)
                except Exception:  # a broken subscriber must not kill the mic
                    log.exception("mic subscriber failed")
        log.warning("mic reader ended")

    def subscribe(self, cb) -> None:
        with self._lock:
            self._subscribers.append(cb)

    def unsubscribe(self, cb) -> None:
        with self._lock:
            if cb in self._subscribers:
                self._subscribers.remove(cb)


def voice_activity_model():
    """Silero VAD from openwakeword. The pip package ships without its model files, so on a fresh install
    silero_vad.onnx is not there and the daemon used to die at start: fetch it (and the wake-word feature
    models, a few MB) the first time instead."""
    import os

    import openwakeword
    from openwakeword.utils import download_models
    from openwakeword.vad import VAD

    models = os.path.join(os.path.dirname(openwakeword.__file__), "resources", "models")
    if not os.path.exists(os.path.join(models, "silero_vad.onnx")):
        log.info("first run: downloading the voice-activity model")
        download_models(model_names=["hey_jarvis"])
    return VAD()


class UtteranceRecorder:
    """Record one utterance: wait for speech, stop after trailing silence (Silero VAD)."""

    def __init__(self, mic: Microphone, silence_s: float, no_speech_timeout_s: float, max_s: float):
        self.mic = mic
        self.vad = voice_activity_model()
        self.silence_s = silence_s
        self.no_speech_timeout_s = no_speech_timeout_s
        self.max_s = max_s

    async def record(self, cancel: asyncio.Event, prefill=None) -> np.ndarray | None:
        """`prefill()` → (mic seq, frame) pairs already heard (speech in progress, e.g. after the assistant's name)."""
        loop = asyncio.get_running_loop()
        q: asyncio.Queue = asyncio.Queue()
        cb = lambda f: loop.call_soon_threadsafe(q.put_nowait, (self.mic.seq, f))  # noqa: E731
        self.vad.reset_states()
        frames: list[np.ndarray] = []
        pre_roll: list[np.ndarray] = []
        speech = False
        silence = 0.0
        started = time.monotonic()
        held: list[np.ndarray] = []
        self.mic.subscribe(cb)
        try:
            if prefill is not None:
                # frames are delivered one at a time to every subscriber in order, so everything before the first
                # frame we got has already reached the prefill source: no gap and no overlap
                try:
                    first = await asyncio.wait_for(q.get(), timeout=2)
                finally:
                    got, prefill = prefill(), None  # always collect it: the source keeps buffering until asked
                frames = [f for s, f in got if s < first[0]]
                speech = True
                held.append(first[1])
            while not cancel.is_set():
                try:
                    frame = held.pop() if held else (await asyncio.wait_for(q.get(), timeout=0.5))[1]
                except TimeoutError:
                    if time.monotonic() - started > self.no_speech_timeout_s and not speech:
                        return None
                    continue
                p = float(self.vad.predict(frame, frame_size=640))
                if not speech:
                    pre_roll = (pre_roll + [frame])[-4:]  # keep ~320 ms before onset
                    if p > 0.5:
                        speech = True
                        frames.extend(pre_roll)
                    elif time.monotonic() - started > self.no_speech_timeout_s:
                        return None
                    continue
                frames.append(frame)
                silence = silence + FRAME / RATE if p < 0.3 else 0.0
                if silence >= self.silence_s or len(frames) * FRAME / RATE >= self.max_s:
                    break
            if not frames:
                return None
            # cancel = "stop listening now": still return what we have
            return np.concatenate(frames)
        finally:
            self.mic.unsubscribe(cb)


class Player:
    """Plays int16 mono PCM through pw-play; stop() cuts playback immediately.

    `volume` is JustDay's own level (0–100): it sets the volume of our stream, so the assistant can be
    made quieter without touching the system volume — and without touching what other apps play."""

    def __init__(self, sink_substring: str = "", volume: int = 100):
        self.sink = find_node(sink_substring, "sinks") if sink_substring else None
        self.volume = volume
        self._proc: asyncio.subprocess.Process | None = None

    def _cmd(self, rate: int) -> list[str]:
        cmd = ["pw-play", "--rate", str(rate), "--channels", "1", "--format", "s16", "--raw",
               "--volume", f"{max(0, min(100, int(self.volume))) / 100:.3f}"]
        if self.sink:
            cmd += ["--target", self.sink]
        return cmd + ["-"]

    async def play(self, pcm: np.ndarray, rate: int) -> None:
        cmd = self._cmd(rate)
        self._proc = await asyncio.create_subprocess_exec(
            *cmd, stdin=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
        )
        try:
            self._proc.stdin.write(pcm.astype(np.int16).tobytes())
            await self._proc.stdin.drain()
            self._proc.stdin.close()
            await self._proc.wait()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            self._proc = None

    async def play_stream(self, chunks, rate: int) -> None:
        """Play PCM chunks as they are generated (neural voice: speech starts before synthesis ends)."""
        cmd = self._cmd(rate)
        self._proc = proc = await asyncio.create_subprocess_exec(
            *cmd, stdin=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL
        )
        try:
            async for data in chunks:
                if proc.returncode is not None:  # stop() killed the player
                    break
                proc.stdin.write(data)
                await proc.stdin.drain()
            proc.stdin.close()
            await proc.wait()
        except (BrokenPipeError, ConnectionResetError):
            pass
        finally:
            self._proc = None

    def stop(self) -> None:
        if self._proc and self._proc.returncode is None:
            self._proc.kill()

    @property
    def playing(self) -> bool:
        return self._proc is not None


def timestretch(pcm: np.ndarray, speed: float, rate: int) -> np.ndarray:
    """Speak faster (or slower) without moving the pitch — WSOLA: overlapping frames, aligned before they are added.

    A voice model has one tempo of its own; this is what turns it into the tempo the user asked for."""
    if speed <= 0 or abs(speed - 1.0) < 0.02 or pcm.size < rate // 10:
        return pcm
    x = pcm.astype(np.float32)
    frame = max(256, int(rate * 0.048) // 2 * 2)   # ~48 ms: long enough for the pitch, short enough for speech
    hop_out = frame // 2
    hop_in = max(1, int(round(hop_out * speed)))
    search = int(rate * 0.006)                     # ±6 ms to find where the next frame continues the last one
    win = np.hanning(frame).astype(np.float32)
    out = np.zeros(int(x.size / speed) + 2 * frame, np.float32)
    norm = np.zeros_like(out)
    tail = frame - hop_out
    ref = None
    pos_in = pos_out = 0
    while pos_in + frame + search < x.size and pos_out + frame < out.size:
        best = pos_in
        if ref is not None and search:
            lo = max(0, pos_in - search)
            hi = min(x.size - frame, pos_in + search)
            if hi > lo:
                corr = np.correlate(x[lo:hi + tail], ref, mode="valid")
                best = lo + int(np.argmax(corr))
        seg = x[best:best + frame]
        if seg.size < frame:
            break
        out[pos_out:pos_out + frame] += seg * win
        norm[pos_out:pos_out + frame] += win
        ref = x[best + hop_out:best + hop_out + tail]
        pos_out += hop_out
        pos_in += hop_in
    end = pos_out + frame
    np.divide(out[:end], np.maximum(norm[:end], 1e-3), out=out[:end])
    return np.clip(out[:end], -32768, 32767).astype(np.int16)


class Stretcher:
    """timestretch over a stream: keeps the samples a chunk ends with, so chunks join without a click."""

    def __init__(self, speed: float, rate: int) -> None:
        self.speed, self.rate = speed, rate
        self._rest = np.zeros(0, dtype=np.int16)

    @property
    def passthrough(self) -> bool:
        return abs(self.speed - 1.0) < 0.02

    def feed(self, pcm: np.ndarray) -> np.ndarray:
        if self.passthrough:
            return pcm
        buf = np.concatenate([self._rest, pcm]) if self._rest.size else pcm
        keep = int(self.rate * 0.06)               # one frame plus the search window
        if buf.size <= keep * 2:
            self._rest = buf
            return np.zeros(0, dtype=np.int16)
        self._rest = buf[-keep:]
        return timestretch(buf[:-keep], self.speed, self.rate)

    def drain(self) -> np.ndarray:
        rest, self._rest = self._rest, np.zeros(0, dtype=np.int16)
        return rest if self.passthrough else timestretch(rest, self.speed, self.rate)


def earcon(kind: str, rate: int = 48000) -> np.ndarray:
    """Short synthesized UI tones: 'listen' (rising), 'done' (falling), 'error' (low), 'alarm' (a chime)."""
    if kind == "alarm":  # a timer or an alarm going off: three bell-like notes, softly rung twice
        out = []
        for hz in (1174, 880, 1174, 880):
            t = np.arange(int(rate * 0.22)) / rate
            env = np.exp(-t * 7) * np.minimum(1, t * 400)
            tone = 0.32 * (np.sin(2 * np.pi * hz * t) + 0.35 * np.sin(4 * np.pi * hz * t)) * env
            out.append(tone)
            out.append(np.zeros(int(rate * 0.06)))
        return (np.concatenate(out) * 32767).astype(np.int16)
    notes = {"listen": [880, 1320], "done": [1320, 880], "error": [330, 220]}[kind]
    out = []
    for hz in notes:
        t = np.arange(int(rate * 0.07)) / rate
        env = np.minimum(1, np.minimum(t, t[::-1]) * 60)
        out.append(0.25 * np.sin(2 * np.pi * hz * t) * env)
    return (np.concatenate(out) * 32767).astype(np.int16)


def tools_present() -> dict[str, bool]:
    return {t: shutil.which(t) is not None for t in ("pw-record", "pw-play", "pactl")}
