"""Бесплатные облачные модели по ключу: мозг Джарвиса там, где нет Claude Code.

Главный мозг — Claude Code (brain.py). Но у друга на Windows его нет, а подписки тем более, и без
мозга Джарвис умел только «открой» и «громче». Здесь — прямой разговор с бесплатными моделями
(Gemini, Groq, OpenRouter) через их OpenAI-совместимый адрес: ключ бесплатный, берётся за минуту.

Имена моделей у бесплатных поставщиков меняются каждые пару месяцев (Groq снял Llama 3.3 в августе
2026). Поэтому модель не вписана намертво: спрашиваем у поставщика список и берём первую подходящую
по предпочтениям; что не ответило — пропускаем и идём к следующему поставщику.
"""
from __future__ import annotations

import json
import logging
import urllib.request

from . import providers

log = logging.getLogger("justday.freellm")

# Порядок — порядок попыток. `secret` — имя ключа в связке, `keys` — где его взять.
FREE: list[dict] = [
    {"id": "gemini", "name": "Google Gemini", "base": "https://generativelanguage.googleapis.com/v1beta/openai",
     "keys": "https://aistudio.google.com/apikey", "prefer": ["gemini-flash-latest", "flash"],
     "note": "лучше всех понимает русский; вход аккаунтом Google"},
    {"id": "groq", "name": "Groq", "base": "https://api.groq.com/openai/v1",
     "keys": "https://console.groq.com/keys", "prefer": ["gpt-oss-120b", "llama-4", "llama", "qwen"],
     "note": "самый быстрый ответ — хорош для голоса"},
    {"id": "openrouter", "name": "OpenRouter", "base": "https://openrouter.ai/api/v1",
     "keys": "https://openrouter.ai/keys", "prefer": ["openrouter/free", ":free"],
     "note": "много бесплатных моделей, 50 запросов в день"},
]
_model: dict[str, str] = {}


def ready() -> list[dict]:
    """Поставщики, на которых лежит ключ."""
    return [p for p in FREE if providers.secret_get(p["id"])]


def _call(url: str, key: str, body: dict | None = None, timeout: float = 60) -> dict:
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body else None,
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)


def pick(p: dict, key: str) -> str:
    """Первая модель поставщика, подходящая под предпочтения; запоминается до перезапуска."""
    if p["id"] not in _model:
        names = [m["id"].removeprefix("models/") for m in _call(p["base"] + "/models", key, timeout=15)["data"]]
        _model[p["id"]] = next((n for want in p["prefer"] for n in names if want in n), names[0])
    return _model[p["id"]]


def chat(messages: list[dict], *, json_mode: bool = False, max_tokens: int = 700) -> str:
    """Ответ первой живой бесплатной модели. Нет ключей или все молчат — RuntimeError."""
    errors = []
    for p in ready():
        key = providers.secret_get(p["id"])
        try:
            body = {"model": pick(p, key), "messages": messages, "max_tokens": max_tokens, "temperature": 0.5}
            if json_mode:
                body["response_format"] = {"type": "json_object"}
            return _call(p["base"] + "/chat/completions", key, body)["choices"][0]["message"]["content"].strip()
        except Exception as e:  # лимит, снятая модель, сеть — к следующему поставщику
            _model.pop(p["id"], None)
            errors.append(f"{p['id']}: {type(e).__name__}")
            log.info("бесплатная модель %s не ответила: %s", p["id"], e)
    raise RuntimeError("; ".join(errors) or "нет ни одного ключа")
