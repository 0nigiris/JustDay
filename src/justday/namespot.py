"""Wake on the assistant's own names («Джарвис», «JustDay») instead of only the English "Hey Jarvis".

Silero VAD finds where speech starts; the first ~1.5 s go to the already loaded Whisper model, and if the
transcript begins with a name, JustDay wakes up. Speech after the name is kept, so "Джарвис, открой
калькулятор" works in one breath. Audio stays on the computer, like everything else in the voice loop.
"""
from __future__ import annotations

import logging
import queue
import re
import threading
from collections.abc import Callable

import numpy as np

from . import audio

log = logging.getLogger("justday.namespot")

HEAD_S = 1.6  # how much of the phrase Whisper reads to look for the name
TAIL_MAX_S = 8.0  # speech kept after the name while Whisper is busy
END_SILENCE_S = 0.5
MIN_NAME_PROB = 0.4  # Whisper's confidence in the name itself (real calls: 0.4–0.8)

# how Whisper spells the names in Russian and English; checked against the first words only
SPELLINGS = {
    "джарвис": ["джарвис", "джарвиз", "джарвес", "джервис", "жарвис", "jarvis", "jervis", "charvis"],
    "justday": ["justday", "джастдей", "джастдэй", "джаст дей", "джаст дэй", "just day", "jastday", "джасдей"],
}


FILLERS = ("эй", "хей", "окей", "ok", "okay", "hey", "привет")  # allowed before the name


def _norm(s: str) -> str:
    s = s.lower().replace("ё", "е").replace("-", " ")
    return re.sub(r"[^\w ]+", " ", s).strip()


def spellings(names: list[str]) -> list[str]:
    out: set[str] = set()
    for n in names:
        key = _norm(n).replace(" ", "")
        out.add(_norm(n))
        out.update(SPELLINGS.get(key, []))
    return sorted((s for s in out if s), key=len, reverse=True)


def split_name(text: str, variants: list[str]) -> tuple[bool, str]:
    """(starts with a name, the rest of the phrase, normalized). «Эй»/«hey»/«окей» before the name are allowed."""
    words = re.sub(rf"^({'|'.join(FILLERS)})\s+", "", _norm(text))
    for v in variants:
        if words == v or words.startswith(v + " "):
            return True, words[len(v):].strip()
    return False, words


def strip_name(text: str, variants: list[str]) -> str:
    """«Джарвис, открой калькулятор» → «открой калькулятор» (original casing and punctuation kept)."""
    for v in variants:
        name = r"[\s-]*".join(re.escape(w) for w in v.split())
        m = re.match(rf"^\W*(?:(?:эй|хей|окей|ok|okay|hey|привет)\W+)?{name}(?!\w)[\s,.!?:;—–-]*", text.replace("ё", "е"), re.I)
        if m:
            return text[m.end():]
    return text


class NameSpotter:
    """Fed 80 ms frames from the mic thread. `on_wake(clip, continuing, take_tail)` runs on the Whisper thread:
    `clip` starts with the name; `continuing` = there is a command after it (keep the audio: `take_tail()` returns
    (mic seq, frame) pairs said since the clip) rather than just the name and a pause (listen afresh)."""

    def __init__(self, transcribe: Callable[[np.ndarray], tuple[str, list[tuple[str, float]], float]],
                 names: list[str], seq: Callable[[], int],
                 on_wake: Callable[[np.ndarray, bool, Callable[[], list[tuple[int, np.ndarray]]]], None]):
        from .audio import voice_activity_model

        self.vad = voice_activity_model()
        self.transcribe = transcribe
        self.variants = spellings(names)
        self.on_wake = on_wake
        self.seq = seq
        self._pre: list[np.ndarray] = []
        self._clip: list[np.ndarray] | None = None
        self._silence = 0.0
        self._pending = False  # a clip is with Whisper; frames after it collect in _tail
        self._tail: list[tuple[int, np.ndarray]] = []
        self._stale = False  # the VAD kept running on the tail: start from a clean state
        self._lock = threading.Lock()
        self._jobs: queue.Queue = queue.Queue(maxsize=1)
        threading.Thread(target=self._worker, daemon=True, name="namespot").start()

    def reset(self) -> None:
        self._pre, self._clip, self._silence = [], None, 0.0
        self.vad.reset_states()

    def feed(self, frame: np.ndarray, active: bool) -> None:
        """`active` = JustDay may be woken now (not listening, not speaking)."""
        p = float(self.vad.predict(frame, frame_size=640))
        with self._lock:
            if self._pending:
                if len(self._tail) * audio.FRAME < TAIL_MAX_S * audio.RATE:
                    self._tail.append((self.seq(), frame))
                    return
                # nobody came for the audio (the wake was dropped): go back to spotting
                self._tail, self._pending, self._stale = [], False, True
        if not active or self._stale:
            self._stale = False
            self.reset()
            if not active:
                return
        if self._clip is None:
            self._pre = ([*self._pre, frame])[-4:]
            if p > 0.5:
                self._clip, self._silence = list(self._pre), 0.0
            return
        self._clip.append(frame)
        self._silence = self._silence + audio.FRAME / audio.RATE if p < 0.3 else 0.0
        long_enough = len(self._clip) * audio.FRAME >= HEAD_S * audio.RATE
        if long_enough or self._silence >= END_SILENCE_S:
            clip, still_talking = np.concatenate(self._clip), self._silence < END_SILENCE_S
            self._clip = None
            with self._lock:
                self._pending, self._tail = True, []
            try:
                self._jobs.put_nowait((clip, still_talking))
            except queue.Full:
                with self._lock:
                    self._pending = False

    def believable(self, text: str, words: list[tuple[str, float]], no_speech: float) -> bool:
        """Whisper invents names in murmur and background talk: demand a clearly spoken first word and a real phrase."""
        if no_speech > 0.5 or not words:
            return False
        first = [p for w, p in words[:3] if _norm(w) and _norm(w) not in FILLERS]
        if not first or first[0] < MIN_NAME_PROB:
            return False
        tokens = _norm(text).split()
        names = sum(t in self.variants for t in tokens)
        return names <= 1  # "JustDay, JustDay, JustDay." is a hallucination, not a call

    def _take_tail(self) -> list[tuple[int, np.ndarray]]:
        """Frames heard after the clip; stops collecting (the recorder takes over from here)."""
        with self._lock:
            tail, self._tail, self._pending, self._stale = self._tail, [], False, True
        return tail

    def _worker(self) -> None:
        while True:
            clip, still_talking = self._jobs.get()
            try:
                text, words, no_speech = self.transcribe(clip)
            except Exception:
                log.exception("name spotting failed")
                text, words, no_speech = "", [], 1.0
            hit, rest = split_name(text, self.variants) if text else (False, "")
            if hit and not self.believable(text, words, no_speech):
                log.info("name ignored (unsure): %r %s no_speech=%.2f", text, words[:3], no_speech)
                hit = False
            if hit:
                log.info("name heard: %r", text)
                # "Джарвис…" with speech going on → keep it; "Джарвис." + pause → a normal listen with a beep
                self.on_wake(clip, bool(rest) or still_talking, self._take_tail)
            else:
                self._take_tail()
