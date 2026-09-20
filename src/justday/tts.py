"""Text-to-speech. Default: Silero v5 Russian (local, CPU, ~0.1 s per sentence). Fallback: espeak-ng."""
from __future__ import annotations

import logging
import re
import subprocess
import threading
import urllib.request

import numpy as np

from . import config, numerals
from .audio import timestretch

log = logging.getLogger("justday.tts")

# Silero's Russian models silently drop Latin letters, so English names must be spelled in Cyrillic.
LEXICON = {
    "claude code": "клод код", "claude": "клод", "anthropic": "антропик", "opus": "опус", "sonnet": "сонет",
    "haiku": "хайку", "youtube": "ютуб", "discord": "дискорд", "steam": "стим", "proton": "протон",
    "github": "гитхаб", "gitlab": "гитлаб", "git": "гит", "python": "пайтон", "rust": "раст",
    "javascript": "джаваскрипт", "typescript": "тайпскрипт", "node": "ноуд", "linux": "линукс",
    "kde": "кэ-дэ-э", "plasma": "плазма", "wayland": "вэйланд", "vs code": "ви-эс код", "vscode": "ви-эс код",
    "chrome": "хром", "helium": "хелиум", "firefox": "файрфокс", "google": "гугл", "gmail": "джимейл",
    "kindle": "киндл", "amazon": "амазон", "telegram": "телеграм", "obsidian": "обсидиан", "kitty": "китти",
    "mcp": "эм-си-пи", "api": "эй-пи-ай", "ai": "эй-ай", "ok": "окей", "okay": "окей", "readme": "ридми",
    "commit": "коммит", "push": "пуш", "pull request": "пулл реквест", "diff": "дифф", "bug": "баг",
    "test": "тест", "tests": "тесты", "justday": "джастдэй", "jarvis": "джарвис", "fedora": "федора", "wifi": "вай-фай",
    "email": "имейл", "e-mail": "имейл", "osu": "осу", "roblox": "роблокс", "sober": "собер", "json": "джейсон",
    "npm": "эн-пи-эм", "docker": "докер", "heroic": "хироик", "cyberpunk": "киберпанк", "deltarune": "дельтарун",
}
_LEX_RE = re.compile(r"\b(" + "|".join(sorted(map(re.escape, LEXICON), key=len, reverse=True)) + r")\b", re.I)

# Crude phonetic fallback for unknown Latin words (better than silence).
_DIGRAPHS = [("sch", "ш"), ("sh", "ш"), ("ch", "ч"), ("th", "т"), ("ph", "ф"), ("oo", "у"), ("ee", "и"),
             ("ck", "к"), ("qu", "кв"), ("kh", "х"), ("zh", "ж"), ("ya", "я"), ("yu", "ю"), ("ts", "ц")]
_LETTERS = dict(zip("abcdefghijklmnopqrstuvwxyz", ["а", "б", "к", "д", "е", "ф", "г", "х", "и", "дж", "к", "л", "м",
                                                   "н", "о", "п", "к", "р", "с", "т", "у", "в", "в", "кс", "й", "з"]))


_LETTER_NAMES = dict(zip("abcdefghijklmnopqrstuvwxyz", [
    "эй", "би", "си", "ди", "и", "эф", "джи", "эйч", "ай", "джей", "кей", "эл", "эм", "эн", "оу", "пи", "кью", "ар",
    "эс", "ти", "ю", "ви", "дабл-ю", "экс", "уай", "зед"]))


def _latin_word(m: re.Match) -> str:
    raw = m.group(0)
    w = raw.lower()
    if raw.isupper() and len(raw) <= 4:  # acronym: spell it
        return "-".join(_LETTER_NAMES[c] for c in w)
    for a, b in _DIGRAPHS:
        w = w.replace(a, b)
    return "".join(_LETTERS.get(c, c) for c in w)


def normalize(text: str, lang: str = "ru", latin: str = "translit", numbers: bool = True) -> str:
    """Markup, links and emoji out; figures spelled out; Latin words handled the way this voice needs them.

    latin="translit" is for voices that cannot read Latin at all (Silero, espeak) — they simply drop it.
    latin="keep" is for multilingual voices (the neural one, ElevenLabs), which read English better
    than any transliteration could."""
    text = re.sub(r"```.*?```", " ", text, flags=re.S)           # code blocks are not for ears
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", text)          # markdown links
    text = re.sub(r"https?://\S+", " ссылка " if lang == "ru" else " link ", text)
    text = re.sub(r"(?<!\w)[~/][\w./-]+", " ", text)              # file paths
    text = re.sub(r"[*_#>|]+", " ", text)
    text = re.sub(r"[\U0001F000-\U0001FFFF☀-➿]", " ", text)  # emoji
    if lang == "ru" and numbers:  # figures are read badly by every engine: say them as words
        text = numerals.spell(text)
    if lang == "ru" and latin == "translit":  # Silero swallows Latin letters: spell brand names the Russian way
        text = _LEX_RE.sub(lambda m: LEXICON[m.group(0).lower()], text)
        text = re.sub(r"[A-Za-z]+", _latin_word, text)
    text = text.replace("—", ",").replace("–", ",")
    return re.sub(r"\s+", " ", text).strip()


def split_sentences(text: str, max_len: int = 400) -> list[str]:
    parts = re.split(r"(?<=[.!?…])\s+|\n+", text)
    out: list[str] = []
    for p in parts:
        p = p.strip()
        while len(p) > max_len:
            cut = p.rfind(",", 0, max_len)
            cut = cut if cut > 50 else max_len
            out.append(p[:cut + 1])
            p = p[cut + 1:].strip()
        if re.search(r"\w", p):
            out.append(p)
    return out


# voices that read English (and any other script) on their own
MULTILINGUAL = ("qwen", "elevenlabs")


def latin_mode(cfg: dict) -> str:
    mode = cfg.get("latin", "auto")
    if mode in ("keep", "translit"):
        return mode
    return "keep" if cfg.get("engine") in MULTILINGUAL else "translit"


class TTS:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self.rate = int(cfg["sample_rate"])
        self._model = None
        self._lock = threading.Lock()

    @property
    def speed(self) -> float:
        return max(0.5, min(2.0, float(self.cfg.get("speed", 1.0) or 1.0)))

    def _silero(self):
        if self._model is None:
            import torch

            torch.set_num_threads(4)
            path = config.DATA_DIR / "models" / self.cfg["silero_model_url"].rsplit("/", 1)[1]
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                log.info("downloading %s", self.cfg["silero_model_url"])
                urllib.request.urlretrieve(self.cfg["silero_model_url"], path)
            self._model = torch.package.PackageImporter(str(path)).load_pickle("tts_models", "model")
        return self._model

    def load(self) -> None:
        if self.cfg["engine"] == "silero":
            self._silero()

    NEURAL_RATE = 24000
    SOCKET = config.RUNTIME_DIR / "justday-voice.sock"

    async def stream(self, sentence: str):
        """Neural voice (justday-voice service): yields int16 PCM bytes at NEURAL_RATE as they are generated.
        Raises OSError when the service is unavailable (the caller falls back to Silero)."""
        import asyncio
        import json
        import struct

        reader, writer = await asyncio.open_unix_connection(str(self.SOCKET))
        try:
            req = {"cmd": "say", "text": sentence, "voice": self.cfg.get("voice", "butler")}
            writer.write((json.dumps(req, ensure_ascii=False) + "\n").encode())
            await writer.drain()
            while True:
                head = await reader.readexactly(4)
                (size,) = struct.unpack("<I", head)
                if size == 0:
                    return
                yield await reader.readexactly(size)
        except asyncio.IncompleteReadError as e:
            raise OSError("voice service closed the stream") from e
        finally:
            writer.close()

    ELEVEN_RATE = 24000
    ELEVEN_URL = "https://api.elevenlabs.io/v1/text-to-speech/{voice}/stream?output_format=pcm_24000&optimize_streaming_latency=3"

    def eleven_key(self) -> str:
        return config.secret("ELEVENLABS_API_KEY")

    async def eleven_stream(self, sentence: str):
        """ElevenLabs: yields int16 PCM at ELEVEN_RATE. The text leaves the machine — that is the trade.

        Raises OSError when there is no key or the service refuses, so the caller can fall back."""
        import asyncio
        import json as jsonlib
        import urllib.error
        import urllib.request

        key = self.eleven_key()
        if not key:
            raise OSError("no ElevenLabs key (justday voice key)")
        speed = max(0.7, min(1.2, self.speed))   # the API's own range; the rest is done by timestretch
        body = jsonlib.dumps({"text": sentence, "model_id": self.cfg.get("eleven_model", "eleven_flash_v2_5"),
                              "voice_settings": {"stability": 0.45, "similarity_boost": 0.75, "speed": speed}},
                             ensure_ascii=False).encode()
        req = urllib.request.Request(self.ELEVEN_URL.format(voice=self.cfg.get("eleven_voice", "")), data=body,
                                     headers={"xi-api-key": key, "content-type": "application/json"})
        loop = asyncio.get_running_loop()
        queue: asyncio.Queue = asyncio.Queue(maxsize=32)

        def pump() -> None:
            try:
                with urllib.request.urlopen(req, timeout=30) as r:
                    while True:
                        chunk = r.read(8192)
                        if not chunk:
                            break
                        loop.call_soon_threadsafe(queue.put_nowait, chunk)
                loop.call_soon_threadsafe(queue.put_nowait, None)
            except (urllib.error.URLError, OSError, ValueError) as e:
                loop.call_soon_threadsafe(queue.put_nowait, e)

        await asyncio.to_thread(lambda: None)  # keep the thread pool warm
        task = loop.run_in_executor(None, pump)
        try:
            while True:
                item = await queue.get()
                if item is None:
                    return
                if isinstance(item, BaseException):
                    raise OSError(f"ElevenLabs: {item}") from item
                yield item
        finally:
            task.cancel()

    def synth(self, sentence: str) -> np.ndarray:
        """Return int16 PCM at self.rate for one already-normalized sentence."""
        engine = self.cfg["engine"]
        lang = self.cfg.get("lang", "ru")
        if engine == "silero" and lang == "ru":  # Silero voices here are Russian-only
            try:
                with self._lock:
                    wave = self._silero().apply_tts(
                        text=sentence, speaker=self.cfg["speaker"], sample_rate=self.rate, put_accent=True, put_yo=True
                    )
                return timestretch((wave.numpy() * 32767).astype(np.int16), self.speed, self.rate)
            except Exception:
                log.exception("silero failed on %r, using espeak", sentence)
        if engine == "none":
            return np.zeros(0, dtype=np.int16)
        words = str(int(175 * self.speed))  # espeak has a speed of its own: no need to stretch it afterwards
        wav = subprocess.run(["espeak-ng", "-v", lang if lang in ("ru", "en") else "ru", "-s", words, "--stdout", sentence],
                             capture_output=True).stdout
        pcm = np.frombuffer(wav[44:], dtype=np.int16)  # espeak: 22050 Hz mono WAV
        idx = np.linspace(0, len(pcm) - 1, int(len(pcm) * self.rate / 22050)).astype(int)
        return pcm[idx] if len(pcm) else pcm
