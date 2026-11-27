"""JustDay without the cloud: no tokens, no internet — still a remote control, and still someone to answer.

When the brain cannot be reached, the request comes here. A small local model (Ollama, the same one that
reads the mail) picks one of the few things that never needed the cloud — open an app, play what is already
downloaded, change the volume, answer in a sentence — and the daemon does it. Nothing is invented: if the
request needs the cloud, it says so plainly instead of failing in silence.
"""
from __future__ import annotations

import json
import logging
import re

from . import desktop, localllm, media
from .i18n import t

log = logging.getLogger("justday")

PROMPT = """Ты — офлайн-режим голосового помощника на компьютере с Linux. Облако недоступно.
Ты умеешь ровно четыре вещи:
1. app — открыть установленную программу (query = её название).
2. music — включить музыку из уже скачанного (query = название песни или пусто = любая).
3. volume — громкость системы (query = число 0-100, либо "+" / "-").
4. answer — коротко ответить своими знаниями (answer = 1-2 предложения, тем же языком, что и просьба).

Отвечай ТОЛЬКО JSON: {"action": "app|music|volume|answer", "query": "...", "answer": "..."}
Если просьба требует интернета, файлов, кода, почты или чего-то, чего нет в списке —
action = "answer", а в answer честно скажи, что сейчас без облака этого не сделаешь.
Установленные программы: %(apps)s"""


def available() -> bool:
    return localllm.available()


CLOUD = """%(character)s

Ты — голосовой ассистент на компьютере человека (%(os)s). Отвечаешь вслух: коротко, живо, без
разметки, без списков, одно-три предложения, если не просят подробно. Обращение: «%(address)s».
Кроме разговора умеешь: app — открыть программу (query = её название), music — включить скачанную
музыку (query = песня или пусто), volume — громкость (query = число 0-100 или "+"/"-"),
close — закрыть программу (query = её название), search — найти в интернете (query = что искать;
так же, если просят свежее: погоду, новости, курс).
Отвечай ТОЛЬКО JSON: {"action": "app|music|volume|close|search|answer", "query": "...", "answer": "что сказать вслух"}.
Установленные программы: %(apps)s"""

# Последние реплики разговора с бесплатной моделью: без них «а теперь погромче» и «а он кто?» не
# понимались — у каждой реплики была своя память в одну фразу.
# ponytail: память только до перезапуска демона и только последние 12 реплик.
_history: list[dict] = []


def _cloud(text: str, apps: str) -> dict | None:
    from . import config, freellm, persona

    if not freellm.ready():
        return None
    cfg = config.load()
    system = CLOUD % {"character": persona.character(cfg), "os": "Windows" if config.WINDOWS else "Linux",
                      "address": cfg["user"].get("address_as", ""), "apps": apps}
    try:
        raw = freellm.chat([{"role": "system", "content": system}, *_history, {"role": "user", "content": text}])
    except RuntimeError as e:
        log.info("бесплатные модели молчат: %s", e)
        return None
    m = re.search(r"\{.*\}", raw, re.S)
    try:
        got = json.loads(m.group(0)) if m else {"action": "answer", "answer": raw}
    except json.JSONDecodeError:
        got = {"action": "answer", "answer": raw}
    _history[:] = [*_history, {"role": "user", "content": text}, {"role": "assistant", "content": raw}][-12:]
    got["cloud"] = True
    return got


def decide(text: str) -> dict:
    """Бесплатная облачная модель, если есть ключ; иначе местная; иначе две регулярки."""
    apps = ", ".join(sorted({a["name"] for a in desktop.list_apps() if a["name"]})[:120])
    got = _cloud(text, apps)
    if got is not None:
        action = str(got.get("action", "answer")).strip().lower()
        return {"action": action if action in ("app", "music", "volume", "close", "search") else "answer",
                "query": str(got.get("query", "")).strip(), "answer": str(got.get("answer", "")).strip(), "cloud": True}
    try:
        raw = localllm.chat(PROMPT % {"apps": apps}, text, json_mode=True, max_tokens=200, timeout=60)
        got = json.loads(raw)
    except Exception as e:  # no Ollama either: fall back to the regexes below
        log.info("offline model unavailable (%s)", type(e).__name__)
        return _guess(text)
    action = str(got.get("action", "")).strip().lower()
    if action not in ("app", "music", "volume", "answer"):
        return _guess(text)
    return {"action": action, "query": str(got.get("query", "")).strip(), "answer": str(got.get("answer", "")).strip()}


OPEN = re.compile(r"\b(открой|запусти|включи|open|launch|start)\s+(?P<q>.+)$", re.I)
PLAY = re.compile(r"\b(музык|музон|музл|музычк|песн|песен|трек|music|song|track)", re.I)


def _guess(text: str) -> dict:
    """No model at all: the two requests worth catching by hand."""
    if PLAY.search(text):
        return {"action": "music", "query": "", "answer": ""}
    m = OPEN.search(text)
    if m:
        return {"action": "app", "query": m.group("q").strip(" .,!?"), "answer": ""}
    return {"action": "answer", "query": "",
            "answer": t("Облако сейчас недоступно. Могу включить музыку из скачанного, открыть программу или "
                        "поменять громкость.")}


def summary() -> dict:
    """What still works right now — for `justday doctor` and for the island."""
    return {"local_model": available(), "downloaded_tracks": len(media.library()),
            "apps": len(desktop.list_apps())}
