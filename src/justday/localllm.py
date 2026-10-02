"""Minimal client for the local model (Ollama on 127.0.0.1). Used for private data that must not reach the cloud."""
from __future__ import annotations

import json
import urllib.request

from . import config


def chat(system: str, user: str, *, json_mode: bool = False, max_tokens: int = 400, timeout: float = 120,
         model: str = "", keep_alive: str = "") -> str:
    """Спросить местную модель. `model`/`keep_alive` — для тех, кому нужна другая или на недолго.

    Зачем `keep_alive` снаружи. Карта одна, и девятимиллиардная модель занимает на ней шесть
    гигабайт. Если она висит там десять минут после одного вопроса в одно слово, нейронному голосу
    грузиться уже некуда — и Джарвис умолкает (так и было: CUDA out of memory на загрузке голоса).
    Поэтому короткие вопросы просят отпускать память сразу.
    """
    cfg = config.load()["local_llm"]
    body = {
        "model": model or cfg["model"],
        "stream": False,
        "think": False,
        "keep_alive": keep_alive or cfg.get("keep_alive", "30m"),
        "options": {"num_ctx": cfg.get("num_ctx", 16384), "num_predict": max_tokens, "temperature": 0.3},
        "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
    }
    if json_mode:
        body["format"] = "json"
    req = urllib.request.Request(cfg["url"].rstrip("/") + "/api/chat", data=json.dumps(body).encode(),
                                 headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.load(r)["message"]["content"].strip()


def available() -> bool:
    cfg = config.load()["local_llm"]
    try:
        with urllib.request.urlopen(cfg["url"].rstrip("/") + "/api/tags", timeout=2) as r:
            names = {m["name"] for m in json.load(r)["models"]}
        return cfg["model"] in names or f"{cfg['model']}:latest" in names
    except Exception:
        return False
