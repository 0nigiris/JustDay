"""Telegram как второй канал: дотянуться до него где угодно и получить ответ оттуда же.

KDE Connect работает только в своей сети, а он живёт с телефоном в руках и далеко от дома.
Телеграм закрывает ровно эту дыру: бот пишет ему на телефон в любой точке мира, и он отвечает
боту так же, как говорил бы голосом дома.

**Почему длинный опрос, а не вебхук.** Вебхук потребовал бы открытого наружу порта — у нас такого
нет и не будет: наше правило говорит «только 127.0.0.1». Длинный опрос ходит наружу сам и ничего
не слушает, поэтому он подходит, а вебхук нет. Это не обходной путь, а единственный правильный.

**Почему голосовое сообщение, а не звонок.** Он просил, чтобы Джарвис ему позвонил. Настоящий
звонок на телефонный номер (Telnyx) требует публичного адреса, куда оператор шлёт события звонка:
без него нельзя узнать даже, сняли трубку или нет. Голосовое сообщение даёт то же самое — телефон
звякнул, Джарвис говорит его голосом, — и не требует ни порта, ни денег, ни номера.

Токен и `chat_id` лежат только в связке ключей (`telegram_token`, `telegram_chat`). В конфиге их
нет и быть не должно: конфиг уезжает в репозиторий, а связка — нет.
"""
from __future__ import annotations

import html
import json
import os
import re
import subprocess
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
from pathlib import Path

from . import providers

API = "https://api.telegram.org"
TIMEOUT = 15
POLL_SECONDS = 50          # сколько держать длинный опрос; телеграм разрешает до 50


def token() -> str:
    return providers.secret_get("telegram_token")


def chat() -> str:
    return providers.secret_get("telegram_chat")


def ready() -> bool:
    return bool(token() and chat())


def call(method: str, params: dict | None = None, timeout: float = TIMEOUT) -> dict:
    """Вызвать метод бота. Возвращает `result` или бросает RuntimeError с текстом от телеграма."""
    key = token()
    if not key:
        raise RuntimeError("нет токена бота: secret-tool store --label 'JustDay: telegram_token' "
                           "service justday key telegram_token")
    data = urllib.parse.urlencode({k: v for k, v in (params or {}).items() if v is not None}).encode()
    req = urllib.request.Request(f"{API}/bot{key}/{method}", data=data)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            got = json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        # Телеграм объясняет отказ словами («chat not found»), и это ровно то, что надо показать.
        body = e.read().decode(errors="replace")[:300]
        raise RuntimeError(f"телеграм отказал ({e.code}): {body}") from e
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise RuntimeError(f"телеграм недоступен: {e}") from e
    if not got.get("ok"):
        raise RuntimeError(f"телеграм отказал: {got.get('description', got)}")
    return got.get("result") or {}


def send(text: str, to: str = "") -> dict:
    """Написать ему сообщением. Длинный текст телеграм режет на 4096 знаков — режем сами, по словам."""
    where = to or chat()
    if not where:
        raise RuntimeError("неизвестно, кому писать: нет telegram_chat в связке ключей")
    text = str(text or "").strip()
    if not text:
        raise RuntimeError("нечего отправлять")
    last: dict = {}
    for part in _cut(text, 4096):
        last = call("sendMessage", {"chat_id": where, "text": part, "disable_web_page_preview": "true"})
    return last


def send_shell(text: str, to: str = "") -> dict:
    """Отправить ответ оболочки, сохраняя блоки кода моноширинными и длинные ответы целыми."""
    where = to or chat()
    if not where:
        raise RuntimeError("неизвестно, кому писать: нет telegram_chat в связке ключей")
    parts = re.split(r"```[^\n`]*\n?(.*?)```", str(text or ""), flags=re.S)
    chunks: list[str] = []
    for i, part in enumerate(parts):
        code = i % 2 == 1
        body = part
        while body:
            size, cut, boundary = 0, 0, 0
            for n, char in enumerate(body, 1):
                size += len(html.escape(char, quote=False))
                if size > 4000:
                    break
                cut = n
                if char in ("\n" if code else " "):
                    boundary = n
            if cut < len(body) and boundary > cut // 2:
                cut = boundary
            piece, body = html.escape(body[:cut], quote=False), body[cut:]
            if piece:
                chunks.append(f"<pre>{piece}</pre>" if code else piece)
    if not chunks:
        raise RuntimeError("нечего отправлять")
    last = {}
    for part in chunks:
        last = call("sendMessage", {"chat_id": where, "text": part, "parse_mode": "HTML",
                                     "disable_web_page_preview": "true"})
    return last


def download_voice(file_id: str, max_bytes: int = 20 * 1024 * 1024) -> Path:
    """Скачать голосовое в закрытый временный файл; Telegram ограничивает скачивание 20 МБ."""
    info = call("getFile", {"file_id": file_id})
    remote = str(info.get("file_path") or "")
    if not remote or ".." in Path(remote).parts or remote.startswith("/"):
        raise RuntimeError("телеграм вернул неверный путь голосового файла")
    if int(info.get("file_size") or 0) > max_bytes:
        raise RuntimeError("голосовое слишком большое (предел 20 МБ)")
    req = urllib.request.Request(f"{API}/file/bot{token()}/{remote}")
    try:
        with urllib.request.urlopen(req, timeout=60) as response:
            data = response.read(max_bytes + 1)
    except (urllib.error.URLError, OSError) as e:
        raise RuntimeError(f"не удалось скачать голосовое: {e}") from e
    if len(data) > max_bytes:
        raise RuntimeError("голосовое слишком большое (предел 20 МБ)")
    fd, name = tempfile.mkstemp(prefix="justday-telegram-voice-", suffix=Path(remote).suffix or ".ogg")
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(data)
    except Exception:
        Path(name).unlink(missing_ok=True)
        raise
    return Path(name)


def _cut(text: str, limit: int) -> list[str]:
    """Разрезать по границам строк и слов, а не по счёту знаков: иначе рвёт слова пополам."""
    if len(text) <= limit:
        return [text]
    out, rest = [], text
    while len(rest) > limit:
        cut = rest.rfind("\n", 0, limit)
        if cut < limit // 2:
            cut = rest.rfind(" ", 0, limit)
        if cut <= 0:
            cut = limit
        out.append(rest[:cut].rstrip())
        rest = rest[cut:].lstrip()
    if rest:
        out.append(rest)
    return out


def _to_ogg(pcm, rate: int) -> Path:
    """PCM от нашего синтеза → ogg/opus, как телеграм просит для голосового сообщения.

    Голосовое именно голосовым, а не файлом: оно показывается волной с кнопкой, его слушают одним
    нажатием прямо в чате, а файл сначала качают. Разница в том, услышит он Джарвиса или нет.
    """
    import wave

    tmp = Path(tempfile.gettempdir()) / f"justday-voice-{uuid.uuid4().hex}.wav"
    ogg = tmp.with_suffix(".ogg")
    with wave.open(str(tmp), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(int(rate))
        w.writeframes(pcm.astype("int16").tobytes())
    try:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", str(tmp),
                        "-c:a", "libopus", "-b:a", "32k", "-ar", "48000", "-ac", "1", str(ogg)],
                       check=True, capture_output=True, timeout=60)
    finally:
        tmp.unlink(missing_ok=True)
    return ogg


def voice(text: str, to: str = "", cfg: dict | None = None) -> dict:
    """Сказать ему голосом в телефон — то самое «Джарвис мне позвонил», только без номера.

    Синтез берётся наш же (`tts.TTS`), значит голос тот же, что дома. Если синтеза на этой машине
    нет или ffmpeg не справился, уходит обычный текст: промолчать хуже, чем написать.
    """
    from . import config
    from .tts import TTS

    where = to or chat()
    if not where:
        raise RuntimeError("неизвестно, кому писать: нет telegram_chat в связке ключей")
    text = str(text or "").strip()
    if not text:
        raise RuntimeError("нечего отправлять")
    ogg = None
    try:
        engine = TTS((cfg or config.load())["tts"])
        pcm = engine.synth(text if len(text) < 900 else text[:900])
        if not len(pcm):
            raise RuntimeError("синтез отдал тишину")
        ogg = _to_ogg(pcm, engine.rate)
        return _send_file("sendVoice", "voice", ogg, {"chat_id": where, "caption": text[:1024]})
    except Exception as e:    # любой отказ синтеза лечится текстом: промолчать хуже, чем написать
        out = send(text, where)
        out["voice_error"] = str(e)[:200]
        return out
    finally:
        if ogg is not None:
            ogg.unlink(missing_ok=True)


def _send_file(method: str, field: str, path: Path, params: dict) -> dict:
    """multipart вручную: ради одной отправки файла тянуть requests в зависимости незачем."""
    key = token()
    boundary = uuid.uuid4().hex
    body = bytearray()
    for name, value in params.items():
        body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{name}\"\r\n\r\n"
                 f"{value}\r\n").encode()
    body += (f"--{boundary}\r\nContent-Disposition: form-data; name=\"{field}\"; "
             f"filename=\"{path.name}\"\r\nContent-Type: audio/ogg\r\n\r\n").encode()
    body += path.read_bytes() + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(f"{API}/bot{key}/{method}", data=bytes(body),
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            got = json.loads(r.read().decode())
    except (urllib.error.URLError, OSError, ValueError) as e:
        raise RuntimeError(f"не ушло в телеграм: {e}") from e
    if not got.get("ok"):
        raise RuntimeError(f"телеграм отказал: {got.get('description', got)}")
    return got.get("result") or {}


def updates(offset: int = 0, seconds: int = POLL_SECONDS) -> list[dict]:
    """Длинный опрос: висим на соединении до `seconds`, пока не придёт сообщение.

    Это дешевле и быстрее частых коротких запросов: телеграм отвечает сразу, как только есть что
    отдать, а пустой ответ приходит один раз в минуту вместо шестидесяти в минуту.
    """
    return call("getUpdates", {"offset": offset or None, "timeout": seconds,
                               "allowed_updates": json.dumps(["message", "edited_message", "callback_query"])},
                timeout=seconds + 10)  # type: ignore[return-value]


def mine(update: dict) -> str:
    """Текст сообщения, если оно от него. Чужих не слушаем: бот открыт всему интернету.

    Без этой проверки любой, кто найдёт имя бота, писал бы прямо в мозг ассистента — с его
    почтой, окнами и правом запускать программы. Поэтому чужое молча выбрасывается.
    """
    msg = (update or {}).get("message") or {}
    if not owned(update):
        return ""
    return str(msg.get("text") or "").strip()


def owned(update: dict) -> bool:
    """Владелец — единственный, кому доступны мозг и команды удалённой оболочки."""
    msg = (update or {}).get("message") or {}
    who = str(((msg.get("chat") or {}).get("id")) or "")
    return bool(who and who == chat())


def mine_callback(update: dict) -> dict | None:
    """Кнопки подтверждения принимаются только из личного чата владельца."""
    query = (update or {}).get("callback_query") or {}
    who = str(((query.get("message") or {}).get("chat") or {}).get("id") or "")
    return query if who and who == chat() else None


def location(update: dict) -> tuple[float, float] | None:
    """Координаты из сообщения владельца: разовая точка или очередное обновление живой геопозиции.

    Живая геопозиция приходит как `edited_message` того же сообщения, поэтому смотрим оба. Чужие
    координаты отбрасываются так же, как чужой текст: иначе кто угодно мог бы «перевезти» владельца."""
    for key in ("message", "edited_message"):
        msg = (update or {}).get(key) or {}
        loc = msg.get("location")
        who = str(((msg.get("chat") or {}).get("id")) or "")
        if loc and who and who == chat():
            try:
                return float(loc["latitude"]), float(loc["longitude"])
            except (KeyError, TypeError, ValueError):
                return None
    return None


class PinGate:
    """Второй фактор для бота (Р-9 ревизии): угнанный Telegram-аккаунт не должен давать мозг и оболочку.

    Одной проверки `chat.id == владелец` мало: тот, кто залез в аккаунт, пишет из того же чата. Поэтому, если в
    связке лежит `telegram_pin`, команды принимаются только после того, как PIN прислан сообщением, — и так
    сутки; перезапуск демона запирает снова. Неверные попытки считаются только у сообщений, похожих на PIN
    (цифры той же длины): человек, забывший про замок и написавший «включи музыку», себя не заблокирует,
    а перебор шести цифр упирается в паузу: пять промахов — пятнадцать минут тишины.

    Сам PIN не хранится нигде, кроме связки, и сравнивается за постоянное время."""

    OPEN_S = 24 * 3600
    MAX_MISSES = 5
    LOCK_S = 15 * 60

    def __init__(self, pin=lambda: providers.secret_get("telegram_pin"), clock=time.monotonic) -> None:
        self._pin, self._clock = pin, clock
        self.until = 0.0
        self.misses = 0
        self.locked_until = 0.0

    def is_open(self) -> bool:
        """Открыт ли замок прямо сейчас — для кнопок и геопозиции, у которых PIN прислать нечем."""
        return not (self._pin() or "").strip() or self._clock() < self.until

    def check(self, text: str) -> str:
        """«open» — пропустить; «unlocked» — только что открыли (сообщение с PIN надо стереть); «denied» —
        похоже на PIN, но неверный; «locked» — слишком много промахов; «need» — нужен PIN."""
        import hmac

        pin = (self._pin() or "").strip()
        now = self._clock()
        if not pin or now < self.until:
            return "open"
        if now < self.locked_until:
            return "locked"
        said = (text or "").strip()
        if said and hmac.compare_digest(said.encode(), pin.encode()):
            self.until, self.misses = now + self.OPEN_S, 0
            return "unlocked"
        if said.isdigit() and len(said) == len(pin):
            self.misses += 1
            if self.misses >= self.MAX_MISSES:
                self.locked_until, self.misses = now + self.LOCK_S, 0
                return "locked"
            return "denied"
        return "need"


PIN_REPLY = {
    "need": "Нужен PIN: пришлите его одним сообщением — открою на сутки.",
    "unlocked": "Открыто на сутки.",
    "denied": "Неверный PIN.",
    "locked": "Слишком много попыток. Подождите пятнадцать минут.",
}
