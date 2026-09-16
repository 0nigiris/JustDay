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


class UtteranceRecorder:
    """Record one utterance: wait for speech, stop after trailing silence (Silero VAD)."""

    def __init__(self, mic: Microphone, silence_s: float, no_speech_timeout_s: float, max_s: float):
        from openwakeword.vad import VAD

        self.mic = mic
        self.vad = VAD()
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
    """Plays int16 mono PCM through pw-play; stop() cuts playback immediately."""

    def __init__(self, sink_substring: str = ""):
        self.sink = find_node(sink_substring, "sinks") if sink_substring else None
        self._proc: asyncio.subprocess.Process | None = None

    async def play(self, pcm: np.ndarray, rate: int) -> None:
        cmd = ["pw-play", "--rate", str(rate), "--channels", "1", "--format", "s16", "--raw"]
        if self.sink:
            cmd += ["--target", self.sink]
        cmd.append("-")
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
        cmd = ["pw-play", "--rate", str(rate), "--channels", "1", "--format", "s16", "--raw"]
        if self.sink:
            cmd += ["--target", self.sink]
        cmd.append("-")
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


def earcon(kind: str, rate: int = 48000) -> np.ndarray:
    """Short synthesized UI tones: 'listen' (rising), 'done' (falling), 'error' (low)."""
    notes = {"listen": [880, 1320], "done": [1320, 880], "error": [330, 220]}[kind]
    out = []
    for hz in notes:
        t = np.arange(int(rate * 0.07)) / rate
        env = np.minimum(1, np.minimum(t, t[::-1]) * 60)
        out.append(0.25 * np.sin(2 * np.pi * hz * t) * env)
    return (np.concatenate(out) * 32767).astype(np.int16)


def tools_present() -> dict[str, bool]:
    return {t: shutil.which(t) is not None for t in ("pw-record", "pw-play", "pactl")}
