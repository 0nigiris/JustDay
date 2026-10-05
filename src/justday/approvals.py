"""Подтверждения и вопросы человеку: кнопка в островке, голос или уведомление рабочего стола.

Вынесено из daemon.py (Р-80). Ответ голосом разбирает `_match_answer`: согласие на опасное — только
фраза целиком из согласия (Р-4), а не «да» среди чужой речи."""
from __future__ import annotations

import asyncio
import logging
import os
import re
import socket
import struct
import time

from . import (
    events,
    providers,
)
from .aio import spawn
from .i18n import t

log = logging.getLogger("justday.daemon")


YES = re.compile(r"\b(да|давай|разрешаю|разреши|подтверждаю|конечно|ок|окей|можно|делай|yes|yeah|sure|ok|okay|allow|go ahead|do it)\b", re.I)
# Слова, из которых целиком состоит согласие. «Да, конечно» из телевизора всё равно пройдёт, но «да, и вообще
# я считаю, что…» — нет: раньше хватало одного «да» где угодно во фразе (Р-4).
YES_WORDS = frozenset({
    "да", "давай", "разрешаю", "разреши", "подтверждаю", "конечно", "ок", "окей", "можно", "делай", "пожалуйста", "ну",
    "yes", "yeah", "sure", "ok", "okay", "allow", "go", "ahead", "do", "it"})
NO = re.compile(r"\b(нет|не надо|отмена|отклон\w*|запрещаю|стоп|no|nope|don'?t|deny|cancel)\b", re.I)


class AskMixin:
    # ---------------- approvals and questions ----------------
    async def _ask(self, speech: str, choices: list[str] | None = None, free_text: bool = False,
                   notify: tuple[str, str] | None = None) -> str | None:
        """Wait for the user's answer: an island button, the voice, or (no island running) a desktop notification.
        Returns "allow" / "deny", one of `choices`, the user's own words (`free_text`), or None after 120 s.
        A click counts at once — no waiting for the question to be read out."""
        loop = asyncio.get_running_loop()
        fut = self._approval = loop.create_future()
        self._ask_choices, self._ask_free = choices or [], free_text
        self.state = "approval"
        await self.say(speech)
        side: list[asyncio.Task] = []
        proc = None
        if notify and not self._subs:
            proc = await asyncio.create_subprocess_exec(
                "notify-send", "-a", "JustDay", "-u", "critical", "-i", "dialog-warning", "--wait",
                f"--action=allow={t('Разрешить')}", f"--action=deny={t('Отклонить')}",
                t("JustDay просит подтверждение"), f"{notify[0][:400]}\n{notify[1][:200]}",
                stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)

            async def from_notification():
                out, _ = await proc.communicate()
                choice = out.decode().strip()
                if choice in ("allow", "deny") and not fut.done():
                    fut.set_result(choice)

            side.append(spawn(from_notification()))
        spoken = spawn(self.wait_speech_done())
        deadline = loop.time() + 120
        try:
            await asyncio.wait({fut, spoken}, timeout=120, return_when=asyncio.FIRST_COMPLETED)
            if not fut.done():
                self.listen(followup=True)  # the question has been read out: now a spoken answer is welcome too
                await asyncio.wait({fut}, timeout=max(0.0, deadline - loop.time()))
            return fut.result() if fut.done() else None
        finally:
            if not spoken.done():
                spoken.cancel()
                self.stop_speaking()
            if fut.done() and self.state == "listening" and self._listen_cancel:  # clicked while we listened
                self._discard_recording = True
                self._listen_cancel.set()
            self.state = "thinking" if self.brain.busy else "idle"
            for task in side:
                task.cancel()
            if proc and proc.returncode is None:
                proc.kill()
            self._approval = None
            self._ask_choices, self._ask_free = [], False

    def _match_answer(self, text: str) -> str | None:
        """A spoken reply to the pending question, or None if it is not an answer."""
        norm = re.sub(r"[^\w ]+", " ", text.lower().replace("ё", "е")).strip()
        for c in self._ask_choices:
            cn = re.sub(r"[^\w ]+", " ", c.lower().replace("ё", "е")).strip()
            if cn and (cn in norm or (len(norm) > 2 and norm in cn)):
                return c
        words = norm.split()
        long = len(words) > 3  # "да, но добавь смайлик" is a correction, not a yes
        yes, no = bool(YES.search(text)) and not NO.search(text), bool(NO.search(text))
        if yes and not self._ask_choices and not self._ask_free:
            # Разрешение на действие — только фраза целиком из согласия, а не «да» среди чужой речи.
            yes = 0 < len(words) <= 4 and all(w in YES_WORDS for w in words)
        if not (self._ask_free and long):
            if yes:
                return self._ask_choices[0] if self._ask_choices else "allow"
            if no and not self._ask_choices:
                return "deny"
        return text if self._ask_free else None

    @staticmethod
    def _peer_is_ai(writer: asyncio.StreamWriter) -> bool:
        """Подключился ли к сокету мозг или его потомок (Р-1). Не узнали собеседника — значит нельзя."""
        try:
            cred = writer.get_extra_info("socket").getsockopt(socket.SOL_SOCKET, socket.SO_PEERCRED, 12)
        except (OSError, AttributeError):
            return True
        return providers.spawned_by_ai(struct.unpack("3i", cred)[0], os.getpid())

    async def _approve(self, desc: str, reason: str, hard: bool = True) -> bool:
        if not hard and time.monotonic() < self._preapproved_until:
            events.emit("approval_auto", desc=desc)  # the user already approved this in the draft card
            return True
        if hard and desc:  # опасное называют вслух: «разрешить?» без слова о том, что именно, — слепое «да» (Р-4)
            what = desc if len(desc) <= 140 else desc[:140].rsplit(" ", 1)[0] + "…"
            speech = t("Нужно подтверждение: {what}. Разрешить?", what=what)
        else:
            speech = t("Нужно подтверждение. Разрешить?")
        return await self._ask(speech, notify=(desc, reason)) == "allow"

    async def _answer_questions(self, questions: list[dict]) -> dict | None:
        """The brain's AskUserQuestion, shown as a card with the options as buttons; answered by click or voice."""
        answers: dict[str, str] = {}
        try:
            for q in questions[:4]:
                labels = [o.get("label", "") for o in q.get("options", []) if o.get("label")]
                self.publish(kind="card", card={"type": "question", "question": q.get("question", ""),
                                                "header": q.get("header", ""), "options": q.get("options", [])})
                spoken = q.get("question", "")
                if labels:
                    spoken += " " + (t("{a} или {b}?", a=", ".join(labels[:-1]), b=labels[-1]) if len(labels) > 1 else labels[0])
                ans = await self._ask(spoken, choices=labels, free_text=True)
                if ans in (None, "deny"):
                    return None
                answers[q.get("question", "")] = labels[0] if ans == "allow" and labels else ans
            return answers
        finally:
            self.publish(kind="card_close")

    async def confirm_message(self, to: str, via: str, text: str) -> dict:
        """A message draft shown BEFORE the brain opens the messenger. Approved → sending is pre-approved."""
        self.publish(kind="card", card={"type": "message_draft", "to": to, "via": via, "body": text})
        where = f"{to} ({via})" if via else to
        ans = await self._ask(t("{to}: «{text}». Отправить?", to=where, text=text), free_text=True)
        self.publish(kind="card_close")
        if ans == "allow":
            self._preapproved_until = time.monotonic() + 180
            return {"ok": True, "result": "approved: the user approved exactly this text. Now open the app and send it; "
                                          "do not ask again (sending is pre-approved for 3 minutes)."}
        if ans in (None, "deny"):
            return {"ok": True, "result": "denied: do not send it" + (" (no answer)" if ans is None else "")}
        return {"ok": True, "result": f"edit: the user said «{ans}». Rewrite the text accordingly and run "
                                      f"confirm-message again before sending."}
