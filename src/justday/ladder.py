"""Лестница моделей демона: кому думать над просьбой, как подняться и как спуститься при лимите.

Вынесено из daemon.py (Р-80): методы работают с `self.cfg`, `self.brain`, `self.publish` и
`self.notify` демона, поэтому это миксин, а не отдельный объект."""
from __future__ import annotations

import asyncio
import functools
import logging
import time

from . import (
    dispatch,
    events,
    fallback,
)
from .i18n import t

log = logging.getLogger("justday.daemon")


class LadderMixin:
    async def _pick_model(self, text: str) -> tuple[str, str]:
        """Выбрать, кому думать над просьбой. Возвращает прежнюю пару — чтобы вернуться после.

        Переподключение стоит секунду-полторы, и платить её имеет смысл только вверх: подняться
        надо **до** работы, иначе работать будет не тот. Опускаться обратно можно потом, когда
        человек уже получил ответ и никуда не торопится.

        Три ступени, а не две. Совсем мелкое — «который час», «как дела» — не стоит даже лёгкой
        облачной модели: на это есть крошечная местная, если человек её завёл. Она на той же
        видеокарте, стоит ноль и отвечает мгновенно; инструменты ей почти не даются, поэтому
        берётся она только там, где делать ничего не надо.
        """
        b = self.cfg["brain"]
        home = str(b.get("home_provider") or "claude")
        was = (b.get("provider", "claude"), b.get("model", ""))
        if not b.get("auto_model", True) or b.get("provider", "claude") != home:
            return was
        light, strong = b.get("light_model") or "haiku", b.get("strong_model") or "sonnet"
        huge = str(b.get("huge_model") or "").strip()
        tiny_model = str(b.get("tiny_model") or "").strip()
        tiny_where = str(b.get("tiny_provider") or "ollama")
        tiny_ok = bool(tiny_model) and fallback.usable(tiny_where)
        if str(b.get("ask_judge") or "never") == "always":
            level, why = await asyncio.get_running_loop().run_in_executor(
                None, functools.partial(dispatch.level_for, text, tiny=tiny_ok))
        else:
            level, why = dispatch.LIGHT, "без судьи"
        if level == dispatch.TINY and tiny_ok:
            want = (tiny_where, tiny_model)
        elif level == dispatch.BIG:
            # Самая сильная — только за настоящую работу: спроектировать, переписать, разобраться
            # в большом. Лимит у подписки один на всё, и потраченный на мелочь не вернётся.
            want = (home, huge or strong)
        elif level == dispatch.STRONG:
            want = (home, strong)
        else:
            want = (home, light)
        # Усилие тоже выбирается само, по той же мерке: он просил, чтобы решала нейросеть, а не
        # настройка. Пустое `brain.effort` значит «как решит Claude Code», и его мы не трогаем.
        effort = dispatch.EFFORT.get(level, "") if b.get("auto_effort", True) else b.get("effort", "")
        if want == was and effort == b.get("effort", ""):
            return was
        b["provider"], b["model"] = want
        b["effort"] = effort
        try:
            await self.brain.reconnect()
        except Exception:
            log.exception("не вышло переключиться на %s, остаёмся на %s", want[1], was[1])
            b["provider"], b["model"] = was
            return was
        log.info("модель: %s → %s (%s)", was[1] or was[0], want[1] or want[0], why)
        events.emit("model_picked", model=want[1], was=was[1], why=why)
        self.publish(brain_model=want[1], brain_why=why, provider=want[0])
        return was

    async def _lift(self, name: str) -> bool:
        """Лёгкая сказала «НУЖНА: …» — пересесть на сильную. True — пересели, вопрос надо задать снова.

        Принимаем только свои ступени: слово из ответа модели не должно подставлять в конфиг
        что угодно.
        """
        b = self.cfg["brain"]
        home = str(b.get("home_provider") or "claude")
        if not b.get("auto_model", True) or b.get("provider", "claude") != home:
            return False
        strong, huge = b.get("strong_model") or "sonnet", str(b.get("huge_model") or "")
        name = name.lower()
        if name in (huge.lower(), "opus", "huge", "big") and huge:
            model, level = huge, dispatch.BIG
        elif name in (strong.lower(), "sonnet", "strong"):
            model, level = strong, dispatch.STRONG
        else:
            return False
        if b.get("model") == model:
            return False
        was = (b.get("provider", "claude"), b.get("model", ""), b.get("effort", ""))
        b["provider"], b["model"] = home, model
        if b.get("auto_effort", True):
            b["effort"] = dispatch.EFFORT[level]
        try:
            await self.brain.reconnect()
        except Exception:
            log.exception("не вышло подняться на %s", model)
            b["provider"], b["model"], b["effort"] = was
            return False
        log.info("модель: %s → %s (позвала лёгкая)", was[1], model)
        events.emit("model_picked", model=model, was=was[1], why="позвала лёгкая")
        self.publish(brain_model=model, brain_why="позвала лёгкая", provider=home)
        return True

    async def _fall_back(self, error: str) -> bool:
        """Перейти к запасному поставщику, если отказ похож на лимит. True — перешли."""
        if not fallback.looks_like_limit(error):
            return False
        got = fallback.next_provider(self.cfg)
        if not got:
            log.info("лимит, но переходить некуда")
            return False
        name, model = got
        b = self.cfg["brain"]
        was = b.get("provider", "claude")
        b["provider"], b["model"] = name, model
        self._fell_back_at = time.monotonic()
        try:
            await self.brain.reconnect()
        except Exception:
            log.exception("не вышло перейти на %s", name)
            b["provider"], b["model"] = was, b.get("model", model)
            return False
        log.info("лимит у %s → перешёл на %s (%s)", was, name, model)
        events.emit("provider_fallback", was=was, provider=name, model=model)
        self.publish(brain_model=model, brain_why="", provider=name)
        # Сказать об этом надо: человек должен знать, что отвечает уже не тот, кого он звал.
        self.notify(t("Лимит Claude кончился — перешёл на {where}.").format(where=name),
                    icon="dialog-information")
        return True

    async def _try_home(self) -> None:
        """Подняться обратно по лестнице, как только верхний снова отвечает.

        Угадывать, когда лимит вернётся, нечем: Claude этого не говорит. Поэтому мы не гадаем, а
        спрашиваем — раз в четверть часа одним словом, отдельным коротким процессом. Ответил —
        поднимаемся. Молчит — работаем там, где работаем, и спросим позже.

        Проверка идёт только между разговорами и только когда мозг свободен: забрать работу у
        того, кто её делает, посередине — значит потерять её. Нижний договаривает своё, и уже
        после этого место занимает верхний.
        """
        b = self.cfg["brain"]
        hours = float(b.get("fallback_back_after_hours") or 0)
        if not hours or not self._fell_back_at:
            return
        got = fallback.better_than(self.cfg)
        if not got:                                   # мы и так наверху
            return
        now = time.monotonic()
        if now - self._fell_back_at < hours * 3600:
            return
        every = max(1.0, float(b.get("fallback_check_minutes") or 15)) * 60
        if now - self._probed_at < every:
            return
        if self.brain.busy or self._workers_active:   # идёт работа — дождёмся её конца
            return
        self._probed_at = now
        name, model = got
        ok = await asyncio.get_running_loop().run_in_executor(
            None, fallback.probe, self.cfg, name, model)
        if not ok:
            return
        was = b.get("provider", "claude")
        b["provider"] = name
        b["model"] = model or b.get("light_model") or "haiku"
        try:
            await self.brain.reconnect()
        except Exception:
            log.exception("вернуться на %s не вышло", name)
            b["provider"] = was
            return
        self._fell_back_at = 0.0 if name == str(b.get("home_provider") or "claude") else now
        log.info("%s снова отвечает — вернулись с %s", name, was)
        events.emit("provider_home", provider=name, was=was)
        self.publish(brain_model=b["model"], brain_why="", provider=name)
        # Сказать стоит: человек должен знать, что отвечает снова тот, кого он звал.
        self.notify(t("{where} снова отвечает — вернулся к нему.").format(where=name),
                    icon="dialog-information")
