"""Инициатива: Джарвис иногда заговаривает сам, без повода — «от скуки» (П22, его слова 12 нояб.).

Шкала `initiative.level` 0…3 в настройках. 0 — молчит (так по умолчанию: он сам говорил, что
пользуется Джарвисом мало и пустые реплики его злят). Дальше — раз в три часа, раз в час, раз в
двадцать минут, и то только когда он за компьютером, не в игре и сам давно ничего не просил.

Реплику говорит крошечная местная модель (`brain.tiny_model`), а нет её — готовая фраза: тратить на
болтовню лимит подписки нельзя, он один на весь день. Напоминания о встречах — не здесь, это
`observer.py`, и шкала их не трогает: встреча — повод, а не скука.
"""
from __future__ import annotations

import datetime as dt
import logging
import random

from . import chitchat, localllm
from .i18n import t

log = logging.getLogger("justday")

# Минут тишины между репликами для уровней 1…3.
EVERY = {1: 180, 2: 60, 3: 20}
QUIET_HOURS = (23, 9)   # ночью и рано утром — ни слова: человек спит или только проснулся

PROMPT = """Ты — {name}, голосовой помощник на компьютере, с характером. Сейчас {when}. Человек работает за
компьютером и давно ничего не просил. Скажи сам ОДНУ короткую живую фразу (до двенадцати слов) по-русски:
лёгкое замечание, шутку или предложение помощи. Без эмодзи, без разметки, без вопросов о его делах. Ничего
не выдумывай про мир (погоду, новости), ничего не обещай."""

CANNED = ["Я тут, если что.", "Тихо у нас сегодня.", "Если нужно что-то найти, только скажите.",
          "Скучаю без задач, честно.", "Можно включить музыку, если работается тяжело."]


def due(level: int, quiet_minutes: float, now: dt.datetime) -> bool:
    """Пора ли сказать что-то самому: уровень не ноль, он молчит дольше порога, и сейчас не ночь."""
    every = EVERY.get(max(0, min(3, int(level or 0))))
    if not every or quiet_minutes < every:
        return False
    start, end = QUIET_HOURS[1], QUIET_HOURS[0]
    return start <= now.hour < end


def remark(cfg: dict, now: dt.datetime) -> str:
    """Что сказать. Блокирующий вызов: зовут из потока."""
    model = str(cfg.get("brain", {}).get("tiny_model") or "").strip()
    if model:
        when = "утро" if now.hour < 12 else "день" if now.hour < 18 else "вечер"
        try:
            name = cfg.get("user", {}).get("assistant_name") or "Джарвис"
            got = localllm.chat(PROMPT.format(name=name, when=when), "скажи что-нибудь", max_tokens=60,
                                timeout=6, model=model, keep_alive="1m")
            if line := chitchat._sane(got, "скажи"):
                return line
        except Exception as e:  # Ollama нет или не успела — готовая фраза ничем не хуже
            log.info("инициатива: местная модель не ответила (%s)", type(e).__name__)
    return t(random.choice(CANNED))
