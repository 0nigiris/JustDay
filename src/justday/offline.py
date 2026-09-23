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


def decide(text: str) -> dict:
    """The local model's verdict, or a plain heuristic when even it is not there."""
    apps = ", ".join(sorted({a["name"] for a in desktop.list_apps() if a["name"]})[:120])
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
PLAY = re.compile(r"\b(музык|песн|трек|music|song|track)", re.I)


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
