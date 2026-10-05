"""История буфера обмена — своя, а не поверх cliphist.

Зачем своя. Готовые истории (cliphist, clipman) запоминают всё подряд, включая то, что копируют из
менеджера паролей. Для ассистента это недопустимо дважды: сначала пароль ложится на диск, потом
попадает в глаза модели вместе с остальной историей. Здесь наоборот: секреты не запоминаются, и это
не настройка, а поведение по умолчанию.

Как секреты отсекаются, по порядку надёжности:

1. **Пометка от самой программы.** Менеджеры паролей кладут в буфер служебный тип
   ``x-kde-passwordManagerHint`` со значением ``secret`` — так делают KeePassXC, KWallet и Plasma.
   Есть пометка — запись не появляется вовсе. Это не догадка, а просьба того, кто копировал.
2. **На что это похоже.** Ключи API и приватные ключи узнаются по началу строки: ``sk-``, ``ghp_``,
   ``AKIA``, ``-----BEGIN … PRIVATE KEY-----`` и подобное. Список неполон по определению, поэтому он
   и стоит вторым, а не первым.
3. **Пауза.** ``justday clip pause`` — история не пишется, пока не включат обратно. Для того, что
   не пометила программа и не угадал список.

Что ещё здесь важно:

* файл истории лежит с правами 0600, и каталог тоже;
* картинки хранятся отдельными файлами, в истории — только их размер и путь;
* ассистент видит запись только тогда, когда о ней просят: «вставь то, что я копировал про отпуск».
  Ни один запрос к модели не несёт историю буфера сам по себе.

    justday clip                 # что в истории
    justday clip use 3           # третью запись — в буфер и в то окно, где курсор
    justday clip pin 3           # закрепить заметку сверху
    justday clip edit 3 "текст"  # править скопированное
    justday clip forget 3        # забыть одну
    justday clip wipe            # забыть всё
    justday clip pause           # не запоминать, пока не вернут
"""
from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
import time
from pathlib import Path

from . import config

STORE = config.STATE_DIR / "clipboard.jsonl"
BLOBS = config.STATE_DIR / "clipboard"
PAUSE_FLAG = config.STATE_DIR / "clipboard.paused"

MAX_ENTRIES = 300          # больше листать всё равно не станут, а файл растёт
MAX_TEXT = 64 * 1024       # длиннее — это уже файл, а не то, что копируют читать
MAX_IMAGE = 8 * 1024 * 1024
PREVIEW = 220              # сколько символов показывать в списке

# Текст, который программы кладут в буфер вместе со снимком экрана. Сам снимок уже
# лежит как kind=image — эта строка в истории только мешает и выглядит как «screenshot copied».
SCREENSHOT_TEXT = re.compile(
    r"""(?ix)
    ^\s*(?:
        screenshot\s+(?:copied|saved|stored)(?:\s+to\s+clipboard)?
      | (?:снимок|скриншот)\s+(?:скопирован|сохранён|сохранен)(?:\s+в\s+буфер(?:\s+обмена)?)?
      | image\s+copied\s+to\s+clipboard
    )\.?\s*$
    """,
)

# То, что выглядит ключом. Список заведомо неполон — он второй уровень защиты, не первый.
SECRETS = re.compile(
    r"""(?x)
    ^(?:
        sk-[A-Za-z0-9_-]{16,}          # OpenAI и совместимые
      | sk-ant-[A-Za-z0-9_-]{16,}      # Anthropic
      | gh[pousr]_[A-Za-z0-9]{16,}     # GitHub
      | github_pat_[A-Za-z0-9_]{20,}
      | xox[baprs]-[A-Za-z0-9-]{10,}   # Slack
      | AKIA[0-9A-Z]{16}               # AWS
      | AIza[0-9A-Za-z_-]{30,}         # Google
      | glpat-[A-Za-z0-9_-]{16,}       # GitLab
      | -----BEGIN\s[A-Z ]*PRIVATE\sKEY-----
      | ey[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}\.[A-Za-z0-9_-]{10,}   # JWT
    )""",
)


def paused() -> bool:
    return PAUSE_FLAG.exists()


def pause(on: bool = True) -> bool:
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    if on:
        PAUSE_FLAG.touch()
    else:
        PAUSE_FLAG.unlink(missing_ok=True)
    return paused()


# Похожее на пароль. Не «угадать пароль», а «не запоминать то, что на него похоже»: в истории
# буфера цена ошибки несимметрична. Не запомнили лишнее — человек скопирует ещё раз, это секунда.
# Запомнили пароль — он лежит на диске, и однажды попадёт в глаза модели вместе с остальной историей.
PASSWORD_MIN, PASSWORD_MAX = 8, 64
HEX = re.compile(r"^[0-9a-fA-F]+$")                       # хеш коммита, UUID — это не секреты
STRUCTURED = re.compile(r"^[\w.-]+@|^[a-z]+://|^[~/.]|\.(com|ru|org|net|io|dev)(/|$)|^v?\d+\.\d+")


def _classes(body: str) -> int:
    """Сколько разных родов знаков в строке: строчные, прописные, цифры, всё остальное."""
    return sum((any(c.islower() for c in body), any(c.isupper() for c in body),
                any(c.isdigit() for c in body),
                any(not c.isalnum() for c in body)))


def looks_like_password(body: str) -> bool:
    """Строка без пробелов подходящей длины, в которой смешаны разные знаки.

    Адрес, путь, почта, номер версии и шестнадцатеричная строка (хеш коммита, UUID) исключены:
    их копируют постоянно и секретами они не являются."""
    if " " in body or "\n" in body or not (PASSWORD_MIN <= len(body) <= PASSWORD_MAX):
        return False
    if HEX.match(body) or STRUCTURED.search(body):
        return False
    return _classes(body) >= 2


def looks_secret(text: str) -> bool:
    """Похоже ли это на ключ или пароль, который не стоит держать на диске."""
    body = text.strip()
    if SECRETS.match(body) or ("-----BEGIN" in body[:400] and "PRIVATE KEY" in body[:400]):
        return True
    return looks_like_password(body)


def _read() -> list[dict]:
    try:
        lines = STORE.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return []
    out = []
    for line in lines:
        try:
            out.append(json.loads(line))
        except ValueError:
            continue
    return out


def _write(items: list[dict]) -> None:
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    STORE.write_text("".join(json.dumps(i, ensure_ascii=False) + "\n" for i in items), encoding="utf-8")
    # История буфера — это всё, что человек копировал за день. Читать её должен только он.
    STORE.chmod(0o600)


def _forget_blob(item: dict) -> None:
    if item.get("file"):
        Path(item["file"]).unlink(missing_ok=True)


def store(text: str = "", *, image: bytes = b"", kind: str = "") -> dict:
    """Запомнить то, что попало в буфер. Ответ говорит, запомнили ли и почему нет."""
    if paused():
        return {"ok": False, "why": "пауза"}
    if image:
        if len(image) > MAX_IMAGE:
            return {"ok": False, "why": "картинка больше предела"}
        digest = hashlib.sha256(image).hexdigest()[:16]
        BLOBS.mkdir(parents=True, exist_ok=True)
        BLOBS.chmod(0o700)
        path = BLOBS / f"{digest}.png"
        if not path.exists():
            path.write_bytes(image)
            path.chmod(0o600)
        entry = {"id": digest, "at": time.time(), "kind": "image", "size": len(image),
                 "file": str(path), "text": ""}
    else:
        body = text
        if not body.strip():
            return {"ok": False, "why": "пусто"}
        if SCREENSHOT_TEXT.match(body.strip()):
            return {"ok": False, "why": "подпись к снимку экрана — картинка уже в истории"}
        if len(body) > MAX_TEXT:
            return {"ok": False, "why": "слишком длинно"}
        if looks_secret(body):
            _count_skipped()
            return {"ok": False, "why": "похоже на пароль или ключ — не запоминаем"}
        digest = hashlib.sha256(body.encode()).hexdigest()[:16]
        entry = {"id": digest, "at": time.time(), "kind": kind or "text", "size": len(body),
                 "text": body}

    prev = next((i for i in _read() if i.get("id") == digest), None)
    if prev and prev.get("pinned"):
        entry["pinned"] = True
    items = [i for i in _read() if i.get("id") != digest]     # повтор поднимается наверх, а не копится
    items.insert(0, entry)
    items = _sorted(items)
    for extra in items[MAX_ENTRIES:]:
        _forget_blob(extra)
    _write(items[:MAX_ENTRIES])
    return {"ok": True, "id": digest, "kind": entry["kind"], "pinned": bool(entry.get("pinned"))}


SKIPPED = config.STATE_DIR / "clipboard-skipped.json"


def _count_skipped() -> None:
    """Счётчик пропущенного. Нужен не для статистики: без него «я скопировал, а в истории пусто»
    выглядит поломкой, а не защитой."""
    try:
        was = json.loads(SKIPPED.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        was = {}
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        SKIPPED.write_text(json.dumps({"count": int(was.get("count", 0)) + 1, "at": time.time()}),
                           encoding="utf-8")
    except OSError:
        pass


def skipped() -> dict:
    try:
        got = json.loads(SKIPPED.read_text(encoding="utf-8"))
        return {"count": int(got.get("count", 0)), "at": float(got.get("at", 0))}
    except (OSError, ValueError):
        return {"count": 0, "at": 0.0}


def preview(item: dict) -> str:
    """Одна строка про запись — то, что видно в списке (у картинок подпись под миниатюрой)."""
    if item.get("kind") == "image":
        kb = max(1, int(item.get("size", 0)) // 1024)
        return f"снимок · {kb} КБ"
    body = " ".join(str(item.get("text", "")).split())
    return body[:PREVIEW] + ("…" if len(body) > PREVIEW else "")


def items(limit: int = 60, query: str = "") -> list[dict]:
    """История: закреплённое сверху, затем самое свежее. С запросом — только подходящее.

    Текст в ответ не кладём целиком: список рисуется по строке-предпросмотру (у картинок — путь
    к файлу для миниатюры), а полное содержимое нужно только в момент вставки или правки."""
    words = [w for w in query.lower().split() if w]
    out = []
    for item in _sorted(_read()):
        if words and not all(w in str(item.get("text", "")).lower() for w in words):
            continue
        out.append({"id": item["id"], "at": item["at"], "kind": item.get("kind", "text"),
                    "size": item.get("size", 0), "preview": preview(item),
                    "file": item.get("file", ""), "pinned": bool(item.get("pinned")),
                    "lines": str(item.get("text", "")).count("\n") + 1})
        if len(out) >= limit:
            break
    return out


def get(which: str) -> dict | None:
    """Запись по её id или по номеру в списке, начиная с единицы."""
    all_items = _read()
    if which.isdigit() and 1 <= int(which) <= len(all_items):
        return all_items[int(which) - 1]
    return next((i for i in all_items if i["id"] == which or i["id"].startswith(which)), None)


def forget(which: str) -> bool:
    item = get(which)
    if not item:
        return False
    _forget_blob(item)
    _write([i for i in _read() if i["id"] != item["id"]])
    return True


def wipe() -> int:
    """Забыть всё. Картинки удаляются с диска, а не просто теряют строку в истории."""
    count = len(_read())
    if BLOBS.is_dir():
        shutil.rmtree(BLOBS, ignore_errors=True)
    STORE.unlink(missing_ok=True)
    SKIPPED.unlink(missing_ok=True)
    return count


def put_back(which: str, *, paste: bool = True, ready=None, app: str = "") -> dict:
    """Запись — снова в буфер обмена и сразу в то окно, где курсор (как ⌘V на macOS).

    Короткий однострочный текст печатаем напрямую; длинный / многострочный / картинку —
    кладём в буфер и шлём Ctrl+V. Панель перед этим закрывается, PASTE_DELAY даёт
    композитору вернуть фокус в прежнее окно; демон вместо слепой паузы передаёт `ready` — ответ
    «окно снова слушает» по событиям KWin (см. glyphs.use).
    """
    from . import face, glyphs

    def settle() -> bool:
        if ready is None:
            time.sleep(glyphs.PASTE_DELAY)
            return True
        return ready()

    item = get(which)
    if not item:
        return {"ok": False, "error": "такой записи нет"}
    if item.get("kind") == "image":
        path = item.get("file", "")
        if not path or not Path(path).is_file():
            return {"ok": False, "error": "картинка потерялась"}
        ok = _copy_image(path)
        pasted = False
        how = ""
        if paste and ok and settle():
            pasted, how = glyphs.paste_chord(glyphs.is_terminal(app))
        return {"ok": ok, "kind": "image", "pasted": pasted, "how": how,
                "note": "" if pasted else ("картинка в буфере — вставьте Ctrl+V" if ok
                                           else "нечем положить картинку в буфер"),
                "session": face.session()}
    text = str(item.get("text", ""))
    copied = glyphs.to_clipboard(text)
    typed = False
    pasted = False
    how = ""
    if paste and copied and settle():
        # Печатаем только короткое, в одну строку и латиницей: иначе Enter на каждый \n ломает правку, а
        # `ydotool type` кириллицу и эмодзи «печатает» кодом 0 — молча, с ответом «успех» (см. glyphs.use).
        if len(text) <= 400 and "\n" not in text and text.isascii():
            typed, how = glyphs.type_out(text)
        if not typed:
            pasted, how = glyphs.paste_chord(glyphs.is_terminal(app))
    return {"ok": copied or typed or pasted, "kind": "text", "typed": typed, "pasted": pasted,
            "how": how,
            "note": "" if (typed or pasted) else ("в буфере обмена — вставьте Ctrl+V" if copied
                                                  else "нечем положить в буфер"),
            "session": face.session()}


def _copy_image(path: str) -> bool:
    from . import face

    cmd = (["wl-copy", "--type", "image/png"] if face.session() == "wayland" and shutil.which("wl-copy")
           else ["xclip", "-selection", "clipboard", "-t", "image/png"] if shutil.which("xclip") else [])
    if not cmd:
        return False
    try:
        with open(path, "rb") as fh:
            subprocess.run(cmd, stdin=fh, timeout=10, check=False)
        return True
    except (OSError, subprocess.SubprocessError):
        return False




def _sorted(items: list[dict]) -> list[dict]:
    """Pinned notes stay on top (newest pinned first), then the rest by recency."""
    pinned = [i for i in items if i.get("pinned")]
    rest = [i for i in items if not i.get("pinned")]
    pinned.sort(key=lambda i: float(i.get("at") or 0), reverse=True)
    rest.sort(key=lambda i: float(i.get("at") or 0), reverse=True)
    return pinned + rest


def pin(which: str, on: bool | None = None) -> dict:
    """Закрепить или открепить запись. Без on — переключить."""
    item = get(which)
    if not item:
        return {"ok": False, "error": "такой записи нет"}
    want = (not bool(item.get("pinned"))) if on is None else bool(on)
    items = _read()
    for i in items:
        if i["id"] == item["id"]:
            if want:
                i["pinned"] = True
            else:
                i.pop("pinned", None)
            break
    _write(_sorted(items))
    return {"ok": True, "id": item["id"], "pinned": want}


def edit(which: str, text: str) -> dict:
    """Править текст записи. Картинку править нельзя — только текст."""
    item = get(which)
    if not item:
        return {"ok": False, "error": "такой записи нет"}
    if item.get("kind") == "image":
        return {"ok": False, "error": "картинку так не правят — скопируйте заново"}
    body = str(text)
    if not body.strip():
        return {"ok": False, "error": "пусто"}
    if len(body) > MAX_TEXT:
        return {"ok": False, "error": "слишком длинно"}
    if looks_secret(body):
        return {"ok": False, "error": "похоже на пароль или ключ — не сохраняем"}
    digest = hashlib.sha256(body.encode()).hexdigest()[:16]
    items = _read()
    out = []
    for i in items:
        if i["id"] != item["id"]:
            if i.get("id") == digest:
                continue  # drop duplicate of new text
            out.append(i)
            continue
        out.append({**i, "id": digest, "text": body, "size": len(body), "kind": "text",
                    "at": time.time()})
    _write(_sorted(out))
    return {"ok": True, "id": digest, "preview": preview({"kind": "text", "text": body})}


def text_of(which: str) -> dict:
    """Полный текст записи — для правки в панели. Картинкам отдаём путь к файлу."""
    item = get(which)
    if not item:
        return {"ok": False, "error": "такой записи нет"}
    if item.get("kind") == "image":
        return {"ok": True, "id": item["id"], "kind": "image", "file": item.get("file", ""),
                "pinned": bool(item.get("pinned")), "text": ""}
    return {"ok": True, "id": item["id"], "kind": item.get("kind", "text"),
            "text": str(item.get("text", "")), "pinned": bool(item.get("pinned"))}


# ───────────────────────────── наблюдатель ─────────────────────────────


# Текстовый наблюдатель отдаёт каждое копирование демону по трубе, записи разделены NUL (в скопированном
# тексте его не бывает). Раньше на каждое копирование wl-paste запускал `justday clip store` — новый Python с
# импортом всего пакета, 0,3–0,5 с процессора и десятки мегабайт на каждое Ctrl+C. `sh` стоит миллисекунду.
WATCH_TEXT = ["wl-paste", "--type", "text", "--watch", "sh", "-c", "cat; printf '\\0'"]


def watch_argv() -> list[list[str]]:
    """Чем следить за буфером в этом сеансе.

    На Wayland это `wl-paste --watch`: он сам запускает команду на каждое изменение и отдаёт ей
    содержимое на вход — ровно то, что нужно, и ровно так же работает cliphist. Отдельно текст и
    отдельно картинки: типы не смешиваются, иначе картинка пришла бы как мусорный текст.
    Текст читает сам демон из трубы (`WATCH_TEXT`, `records`); картинки редки, и для них остаётся
    `justday clip store --image`.

    На X11 постоянного наблюдателя нет: там демон опрашивает буфер сам, см. `poll_once`."""
    from . import face

    if face.session() != "wayland" or not shutil.which("wl-paste"):
        return []
    me = shutil.which("justday") or "justday"
    return [WATCH_TEXT, ["wl-paste", "--type", "image/png", "--watch", me, "clip", "store", "--image"]]


async def records(stream, limit: int = MAX_TEXT * 2):
    """Копирования из трубы `WATCH_TEXT`: каждое — байты до NUL. Слишком длинное пропускается целиком, а не
    копится в памяти демона: `store` всё равно отказал бы ему «слишком длинно»."""
    buf, skipping = b"", False
    while chunk := await stream.read(65536):
        parts = (buf + chunk).split(b"\0")
        buf = parts.pop()
        for rec in parts:
            if skipping:
                skipping = False        # хвост уже выброшенного длинного копирования
            elif rec:
                yield rec
        if len(buf) > limit:
            buf, skipping = b"", True


def store_watched(data: bytes, *, image: bool = False) -> dict:
    """Запомнить то, что принёс наблюдатель. Перед этим спрашиваем сам буфер, не помечен ли он как
    секрет: так просят менеджеры паролей."""
    if not image and is_secret_hint():
        return {"ok": False, "why": "помечено как секрет"}
    return store(image=data) if image else store(data.decode("utf-8", errors="replace"))


def poll_once(seen: dict) -> dict | None:
    """Один взгляд на буфер для X11. `seen` — то, что демон помнит между вызовами."""
    if not shutil.which("xclip"):
        return None
    try:
        got = subprocess.run(["xclip", "-o", "-selection", "clipboard"],
                             capture_output=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    if got.returncode != 0:
        return None
    text = got.stdout.decode("utf-8", errors="replace")
    if not text.strip() or text == seen.get("text"):
        return None
    seen["text"] = text
    return store(text)


def is_secret_hint() -> bool:
    """Просил ли тот, кто копировал, не запоминать это.

    Менеджеры паролей кладут рядом с содержимым служебный тип с пометкой «secret» — договорённость
    Plasma, которую соблюдают KeePassXC и KWallet. Спрашиваем сам буфер, а не догадываемся."""
    if not shutil.which("wl-paste"):
        return False
    try:
        types = subprocess.run(["wl-paste", "--list-types"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return False
    if "x-kde-passwordmanagerhint" not in types.stdout.lower():
        return False
    try:
        hint = subprocess.run(["wl-paste", "--type", "x-kde-passwordManagerHint"],
                              capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return True     # тип есть, прочитать не смогли — считаем секретом
    return "secret" in hint.stdout.lower()


def stats() -> dict:
    """Что в истории — для `justday test clip` и настроек."""
    all_items = _read()
    images = sum(1 for i in all_items if i.get("kind") == "image")
    pinned = sum(1 for i in all_items if i.get("pinned"))
    return {"entries": len(all_items), "images": images, "pinned": pinned, "paused": paused(),
            "skipped": skipped()["count"],
            "store": str(STORE), "watch": "wl-paste" if watch_argv() else "опрос xclip",
            "size_kb": (STORE.stat().st_size // 1024 if STORE.is_file() else 0)}
