"""Text-to-speech. Default: Silero v5 Russian (local, CPU, ~0.1 s per sentence). Fallback: espeak-ng."""
from __future__ import annotations

import logging
import re
import subprocess
import threading
import time
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
        self._remote_warned = False
        self._silero_gone = False   # выяснилось, что нейросетевого голоса в окружении нет
        self._lock = threading.Lock()

    @property
    def speed(self) -> float:
        return max(0.5, min(2.0, float(self.cfg.get("speed", 1.0) or 1.0)))

    def _silero(self):
        if self._model is None:
            import torch

            torch.set_num_threads(4)
            path = config.MODELS_DIR / self.cfg["silero_model_url"].rsplit("/", 1)[1]
            if not path.exists():
                path.parent.mkdir(parents=True, exist_ok=True)
                log.info("downloading %s", self.cfg["silero_model_url"])
                urllib.request.urlretrieve(self.cfg["silero_model_url"], path)
            self._model = torch.package.PackageImporter(str(path)).load_pickle("tts_models", "model")
        return self._model

    def _silero_path(self):
        return config.MODELS_DIR / self.cfg["silero_model_url"].rsplit("/", 1)[1]

    def load(self) -> None:
        if self.cfg["engine"] in ("silero", "chatterbox", "elevenlabs"):  # у них Silero — запасной
            # Служба голоса держит torch у себя; демон только просит её подняться. Нет службы — как раньше.
            if self.path_exists() and self.nudge("warm", engine="silero", model=str(self._silero_path())):
                return
            try:
                self._silero()
            except ImportError:   # часть «voice» не установлена — говорить будет espeak-ng
                log.warning("нейросетевой голос не установлен, отвечаю голосом espeak-ng "
                            "(доставить: justday parts add voice)")

    def path_exists(self) -> bool:
        return self._silero_path().exists()

    NEURAL_RATE = 24000
    SOCKET = config.RUNTIME_DIR / "justday-voice.sock"
    CHATTERBOX_SOCKET = config.RUNTIME_DIR / "justday-chatterbox.sock"

    def neural_socket(self):
        """Куда идут `say`, `warm`, `sleep`: у Chatterbox своя служба (свой torch), у Qwen — своя."""
        return self.CHATTERBOX_SOCKET if self.cfg["engine"] == "chatterbox" else self.SOCKET

    _gpu_seen = (0.0, 0)

    def gpu_busy(self) -> bool:
        """Видеокарта занята чем-то кроме нас — тогда Chatterbox не зовём, говорит Silero на процессоре.

        Chatterbox считает фразу на видеокарте целиком, ~1 с на секунду речи. Когда карту делит игра
        или монтаж, он ждёт своей очереди — и человек слышит паузы по пять секунд, а игра ловит
        рывки. Silero на процессоре видеокарты не касается вовсе.
        """
        now = time.monotonic()
        at, load = self._gpu_seen
        if now - at > 2:  # nvidia-smi стоит ~50 мс, а фразы идут подряд
            try:
                out = subprocess.run(["nvidia-smi", "--query-gpu=utilization.gpu,memory.free",
                                      "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=2).stdout
                util, free = (int(x) for x in out.split("\n")[0].split(","))
                # Видеопамяти меньше гигабайта — Chatterbox упадёт по памяти, даже если карта не считает
                load = 100 if free < 1024 else util
            except (OSError, ValueError, subprocess.TimeoutExpired):
                load = 0  # не NVIDIA или драйвера нет — мерить нечем, не мешаем
            self._gpu_seen = (now, load)
        return load >= int(self.cfg.get("gpu_busy_percent", 50) or 101)

    def instruct(self) -> str:
        """Манера речи словами — то, что модель понимает сама.

        Темп раньше набирался растяжением уже готовой речи, и это слышно
        металлическим призвуком. Модель умеет говорить быстрее сама, если
        попросить; просьба на английском работает заметно сильнее русской.
        Свою формулировку можно задать в `tts.style`."""
        style = str(self.cfg.get("style") or "").strip()
        speed = self.speed
        if speed >= 1.3:
            pace = "Speak much faster than usual, brisk and energetic."
        elif speed >= 1.08:
            pace = "Speak noticeably faster than usual, brisk and business-like."
        elif speed <= 0.9:
            pace = "Speak slower than usual, calm and unhurried."
        else:
            pace = ""
        return " ".join(part for part in (style, pace) if part)

    def native_pace(self) -> float:
        """Насколько быстрее модель говорит сама, когда её об этом просят.

        Замер на одной фразе: 8,3 с обычным темпом против 6,9 с по просьбе —
        около 1,2. Но от фразы к фразе выходит по-разному, поэтому засчитываем
        осторожные 1,12: остаток доберёт растяжение, и оно будет мягким.
        """
        speed = self.speed
        if speed >= 1.3:
            return 1.2
        if speed >= 1.08:
            return 1.12
        if speed <= 0.9:
            return 0.92
        return 1.0

    def nudge(self, cmd: str, **extra) -> bool:
        """Одна строка голосовому сервису без ожидания ответа: `warm` или `sleep`.

        Нужна, чтобы прятать возврат модели. Сервис отпускает видеопамять, когда долго молчат, и
        поднимает её обратно секунд десять — заметно. Но между «человек начал говорить» и «ассистент
        ответил» проходит больше, и если попросить заранее, ждать не приходится вовсе.
        """
        import json
        import socket as socket_mod

        try:
            with socket_mod.socket(socket_mod.AF_UNIX) as sock:
                sock.settimeout(1.5)
                # Silero живёт в службе Qwen, даже когда основной голос — Chatterbox
                sock.connect(str(self.SOCKET if extra.get("engine") == "silero" else self.neural_socket()))
                sock.sendall((json.dumps({"cmd": cmd, **extra}) + "\n").encode())
            return True
        except OSError:
            return False

    def silero_remote(self, sentence: str) -> np.ndarray:
        """Silero в службе голоса (процессор, а не демон). OSError — службы нет или она не ответила."""
        import json
        import socket as socket_mod
        import struct

        if not self.path_exists():  # модель ещё не скачана: качает демон, это его дело
            raise OSError("no silero model file yet")
        req = {"cmd": "silero", "text": sentence, "speaker": self.cfg["speaker"], "rate": self.rate,
               "model": str(self._silero_path())}
        with socket_mod.socket(socket_mod.AF_UNIX) as sock:
            sock.settimeout(20)  # первая фраза будит службу: torch и модель поднимаются секунд пять
            sock.connect(str(self.SOCKET))
            sock.sendall((json.dumps(req, ensure_ascii=False) + "\n").encode())
            f = sock.makefile("rb")
            parts = []
            while True:
                head = f.read(4)
                if len(head) < 4:
                    raise OSError("voice service closed the stream")
                (size,) = struct.unpack("<I", head)
                if size == 0:
                    break
                data = f.read(size)
                if len(data) < size:
                    raise OSError("voice service closed the stream")
                parts.append(data)
        return np.frombuffer(b"".join(parts), dtype="<i2").astype(np.int16)

    async def stream(self, sentence: str):
        """Neural voice (justday-voice service): yields int16 PCM bytes at NEURAL_RATE as they are generated.
        Raises OSError when the service is unavailable (the caller falls back to Silero)."""
        import asyncio
        import json
        import struct

        reader, writer = await asyncio.open_unix_connection(str(self.neural_socket()))
        try:
            req = {"cmd": "say", "text": sentence, "voice": self.cfg.get("voice", "butler"),
                   "instruct": self.instruct()}
            if self.cfg["engine"] == "chatterbox":  # хрипота и ровность подбираются на слух: tts.chatterbox_*
                req.update({k: self.cfg[f"chatterbox_{k}"] for k in ("exaggeration", "cfg_weight", "temperature")
                            if f"chatterbox_{k}" in self.cfg})
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
        # Chatterbox и ElevenLabs сюда попадают, только когда сами не смогли (занята видеокарта,
        # кончились кредиты) — и тогда говорит Silero.
        if engine in ("silero", "chatterbox", "elevenlabs") and lang == "ru" and not self._silero_gone:  # Silero voices here are Russian-only
            try:
                try:
                    pcm = self.silero_remote(sentence)
                except OSError as e:  # службы нет — торч поднимется здесь, как до Р-35
                    if not self._remote_warned:
                        self._remote_warned = True
                        log.info("silero не в службе голоса (%s) — говорю из демона", e)
                    pcm = None
                if pcm is None:
                    with self._lock:
                        wave = self._silero().apply_tts(
                            text=sentence, speaker=self.cfg["speaker"], sample_rate=self.rate, put_accent=True,
                            put_yo=True)
                    pcm = (wave.numpy() * 32767).astype(np.int16)
                return timestretch(pcm, self.speed, self.rate)
            except ImportError:   # часть «voice» не установлена: спрашивать об этом каждую фразу незачем
                self._silero_gone = True
                log.warning("нейросетевого голоса нет, говорю espeak-ng (justday parts add voice)")
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
