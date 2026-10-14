"""Слух демона: кнопка и отпускание, запись фразы, слово пробуждения и шпион имён.

Вынесено из daemon.py (Р-80). Миксин: тела методов не менялись, `self` — демон."""
from __future__ import annotations

import asyncio
import logging
import os
import time

import numpy as np

from . import (
    audio,
    events,
    fastpath,
    namespot,
    parts,
    voiceprint,
)
from .aio import spawn
from .i18n import t

log = logging.getLogger("justday.daemon")


class HearingMixin:
    # ---------------- listening ----------------
    async def toggle(self, source: str = "button") -> str:
        """Hotkey handler. Tap (auto-stop on silence, tap again to finish), double tap (cancel all) and hold:
        a held key auto-repeats, so toggles arriving <1 s apart mean "still held"; when they stop,
        the key was released and the utterance ends."""
        now = time.monotonic()
        gap, self._last_toggle = now - self._last_toggle, now
        double = self.cfg["audio"]["double_tap_seconds"]
        # double press = cancel everything. Auto-repeat of a held key starts only after the repeat delay (~600 ms)
        # and then comes every ~40 ms, so a 60–350 ms gap is a real second press.
        if double and 0.06 < gap < double and not self._holding:
            self._last_toggle = 0.0
            await self.cancel_all()
            return "cancel"
        if self.state == "listening" and self._listen_cancel:
            if gap < 1.0:
                if not self._holding:
                    self._holding = True
                    spawn(self._watch_release())
                return "holding"
            self._listen_cancel.set()  # second tap: finish the utterance now
            return "stop-listening"
        self._holding = False
        self._activation = source
        self.stop_speaking()
        if not self.mic_on():  # keyboard mode: the talk key opens the text field
            self.publish(kind="compose")
            return "compose"
        self.listen()
        return "listening"

    async def _watch_release(self) -> None:
        while self._holding and self.state == "listening":
            await asyncio.sleep(0.1)
            if time.monotonic() - self._last_toggle > 0.4:  # auto-repeat stopped → key released
                self._holding = False
                if self._listen_cancel:
                    self._listen_cancel.set()

    def mic_on(self) -> bool:
        """Есть ли с чего слушать. Без установленного распознавания речи микрофон бесполезен:
        кнопка «говорить» открывает поле ввода, а не запись, — иначе первое же слово упало бы
        в ImportError. Доставить: justday parts add speech."""
        return self.cfg["audio"].get("microphone", True) and parts.have("speech")

    def listen(self, followup: bool = False, prefill=None) -> bool:
        if not self.mic_on():  # no microphone: typed answers only (the island shows a reply field)
            if not followup and prefill is None:
                self.publish(kind="compose")
            return False
        if self._listen_task and not self._listen_task.done():
            return False
        self._listen_task = spawn(self._listen_once(followup, prefill))
        return True

    def _wake_by_name(self, prefill, take_tail) -> None:
        """«Джарвис, …» was heard. `prefill` is set when a command follows the name in the same breath."""
        if self.state in ("listening", "transcribing", "speaking") or not self.listen(prefill=prefill):
            take_tail()
            return
        self._holding = False
        self._activation = "wake"

    async def _listen_once(self, followup: bool, prefill=None) -> None:
        """Одно прослушивание. Любая беда внутри — и состояние всё равно возвращается: раньше ошибка
        распознавания (CUDA после сна) оставляла «transcribing» навсегда, и _wake_by_name отказывался
        будить до рестарта (Р-13)."""
        try:
            await self._listen_body(followup, prefill)
        except Exception as e:
            log.exception("listening failed")
            events.emit("listen_failed", error=repr(e))
            if self.state in ("listening", "transcribing"):
                self.state = "thinking" if self.brain.busy else "idle"
            await self.earcon("error")

    async def _listen_body(self, followup: bool, prefill=None, carry: str = "") -> None:
        self.mic.start()
        self._last_mic_use = time.monotonic()
        self.publish(followup=followup)  # остров: продолжение разговора не гасит ответ на экране
        self.state = "listening"
        self._listen_cancel = asyncio.Event()
        self._discard_recording = False
        if not followup and prefill is None:  # mid-phrase after the name: a beep would land in the recording
            await self.earcon("listen")
        events.emit("listen_start", followup=followup, source=self._activation)
        rec = self.recorder
        if followup:
            rec = audio.UtteranceRecorder(self.mic, rec.silence_s, self.cfg["audio"]["followup_seconds"], rec.max_s,
                                          rec.silence_long_s, rec.long_after_s, rec.speculate_after_s)
            rec.smart_after_s = self.recorder.smart_after_s
        loop = asyncio.get_running_loop()
        early: list[asyncio.Future] = []  # раннее распознавание: последнее запущенное, годится ли — решает rec.speculated

        def speculate(pcm: np.ndarray) -> None:
            fut = loop.run_in_executor(None, self.stt.transcribe, pcm)
            fut.add_done_callback(lambda f: f.cancelled() or f.exception())  # брошенное не должно ругаться в журнал
            early.append(fut)

        def level(frame: np.ndarray) -> None:
            rms = float(np.sqrt((frame.astype(np.float32) ** 2).mean())) / 32768.0
            db = 20 * np.log10(rms + 1e-9)  # −50 dBFS (room) … −20 dBFS (loud speech) → 0…1, like a VU meter
            loop.call_soon_threadsafe(lambda: self.publish(level=round(min(1.0, max(0.0, (db + 50) / 30)), 3)))

        self.mic.subscribe(level)
        try:
            pcm = await rec.record(self._listen_cancel, prefill, speculate)
        finally:
            self.mic.unsubscribe(level)
        self._last_mic_use = time.monotonic()
        after = "thinking" if self.brain.busy else "idle"
        if self._discard_recording:
            events.emit("listen_cancelled")
            self.state = after
            return
        if pcm is None or len(pcm) < audio.RATE * 0.3:
            events.emit("listen_empty", source=self._activation)
            if carry:  # договаривать никто не стал: уходит то, что есть
                self.state = after
                await self.handle_utterance(carry)
                return
            # Разбудили и никто не заговорил — скорее всего, показалось. Следующие
            # полминуты слово пробуждения слушаем строже: ложные срабатывания идут
            # сериями (звук из колонок, чужой голос в ролике), а настоящий зов после
            # такого всё равно проходит — по кнопке или чуть громче.
            if self._activation == "wake":
                self._wake_strict_until = time.monotonic() + 30
            self.state = after
            return
        mode = self.cfg["voiceprint"]["mode"]
        if mode == "always" or (mode == "wake" and (followup or self._activation == "wake")):
            prof = voiceprint.profile()
            if prof:
                sc = await asyncio.get_running_loop().run_in_executor(None, voiceprint.score, pcm)
                if sc is not None and sc < prof["threshold"]:
                    events.emit("listen_rejected", score=round(sc, 2))
                    self.publish(kind="error", detail=t("Голос не узнан"))
                    self.state = after
                    return
        self.state = "transcribing"
        gen = self._cancel_gen
        text = None
        if rec.speculated is not None and early:
            try:
                text = await early[-1]  # распознано, пока доходила пауза: человек после этого не заговорил
                events.emit("heard_early")
            except Exception as e:  # раннее не вышло (видеокарта, память) — обычный путь ещё впереди
                log.info("раннее распознавание упало (%s): распознаю заново", type(e).__name__)
        if text is None:
            text = await asyncio.get_running_loop().run_in_executor(None, self.stt.transcribe, pcm)
        if gen != self._cancel_gen:  # cancelled while transcribing: forget what was said
            events.emit("listen_cancelled", text=text)
            return
        self.state = "thinking" if self.brain.busy else "idle"
        if self._activation == "wake" and self._names:
            text = namespot.strip_name(text, self._names)
        events.emit("heard", text=text, seconds=round(len(pcm) / audio.RATE, 1))
        if carry and text:
            text = f"{carry} {text}"   # продолжение: одна просьба из двух кусков
        if not text:
            if carry:
                await self.handle_utterance(carry)
                return
            # Пустое после слова пробуждения или в разговоре — чужой звук, а не просьба: молчим.
            # Звук ошибки уместен, только если человек сам нажал кнопку и ждёт ответа.
            if self._activation == "button" and not followup:
                await self.earcon("error")
            return
        if not carry and self._activation == "wake" and text.strip(" .,!?…").lower() in ("э", "эм", "м", "мм", "ну", "а", "ага", "угу", "хм", "ой", "эх", "ах"):
            events.emit("heard_ignored", text=text)  # «э», «ну», обрывок чужой речи — не просьба
            return
        if not carry and fastpath.unfinished(text):
            # «поставь таймер на…» — пауза пришла раньше конца мысли: слушаем ещё раз и склеиваем
            events.emit("heard_unfinished", text=text)
            await self._listen_body(True, None, carry=text)
            return
        await self.handle_utterance(text)

    # ---------------- background: wake word, mic idle, worker reports ----------------
    def _wake_threshold(self) -> float:
        """Насколько уверенно должно прозвучать слово пробуждения прямо сейчас.

        Пока играет музыка или видео, микрофон слышит колонки — «Джарвис» из ролика
        будил ассистента наравне с хозяином. И сразу после пустого пробуждения планка
        тоже выше: такие срабатывания приходят сериями."""
        w = self.cfg["wakeword"]
        base = float(w["threshold"])
        loud = bool(self.island_video) or bool(self._player_state and not self._player_state.get("paused"))
        if loud:
            base = max(base, float(w.get("threshold_while_playing") or base))
        if time.monotonic() < self._wake_strict_until:
            base = min(0.95, base + 0.15)
        return base

    def _name_spotting_allowed(self) -> bool:
        """В игре и при выключенном голосе Whisper имён не слушает: он занимал бы видеопамять игры (Р-30).
        Кадры идут каждые 80 мс, а `silent()` обходит /proc — поэтому ответ живёт две секунды."""
        now = time.monotonic()
        if now - self._name_gate[0] > 2.0:
            self._name_gate = (now, not self.silent())
        return self._name_gate[1]

    def _name_min_prob(self) -> float:
        """Та же строгость, что и у слова пробуждения, но для имени, услышанного в речи."""
        loud = bool(self.island_video) or bool(self._player_state and not self._player_state.get("paused"))
        base = namespot.MIN_NAME_PROB
        if loud:
            base = 0.65
        if time.monotonic() < self._wake_strict_until:
            base = max(base, 0.7)
        return base

    def _setup_wakeword(self) -> None:
        w = self.cfg["wakeword"]
        if not w["enabled"] or not self.mic_on():
            return
        from openwakeword.model import Model

        path = audio.onnx_model(f"{w['model']}_v0.1.onnx")
        feature_models = {"melspec_model_path": audio.onnx_model("melspectrogram.onnx"),
                          "embedding_model_path": audio.onnx_model("embedding_model.onnx")}
        prof = voiceprint.profile() or {}
        verifier = prof.get("wake_verifier") or ""
        if verifier and os.path.exists(verifier):  # trained on the user's own "Hey Jarvis"
            self._wake = Model(wakeword_models=[path], inference_framework="onnx", **feature_models,
                               custom_verifier_models={os.path.basename(path).rsplit(".onnx", 1)[0]: verifier},
                               custom_verifier_threshold=0.3)
        else:
            self._wake = Model(wakeword_models=[path], inference_framework="onnx", **feature_models)
        loop = asyncio.get_running_loop()

        def on_frame(frame: np.ndarray) -> None:
            if self.state == "listening" or time.monotonic() < self._wake_cooldown:
                self._wake_score = 0.0
                return
            score = self._wake_score = float(max(self._wake.predict(frame).values()))
            if score >= self._wake_threshold():
                self._wake_cooldown = time.monotonic() + 2.5
                self._wake.reset()
                events.emit("wakeword", score=round(float(score), 2))
                loop.call_soon_threadsafe(lambda: asyncio.ensure_future(self.toggle(source="wake")))

        self.mic.subscribe(on_frame)
        if w.get("names", True):
            u = self.cfg["user"]
            # only the main name wakes it («Джарвис»); the other names are for talking, not for waking
            names = self._wake_names(self.cfg)
            self._names = namespot.spellings([n for n in [u["assistant_name"], *u.get("assistant_aliases", [])] if n])

            def on_name(clip, continuing, take_tail) -> None:  # Whisper thread
                self._wake_cooldown = time.monotonic() + 2.5  # "Hey Jarvis" must not toggle it off again
                events.emit("wakeword", name=True, continuing=continuing)
                if continuing:
                    prefill = lambda: [(-1, clip), *take_tail()]  # noqa: E731
                else:
                    take_tail()
                    prefill = None
                loop.call_soon_threadsafe(self._wake_by_name, prefill, lambda: prefill and prefill())

            spotter = namespot.NameSpotter(self.stt.transcribe_head, names, lambda: self.mic.seq, on_name,
                                           min_prob=self._name_min_prob,
                                           floor=lambda: float(self.cfg["wakeword"].get("name_candidate", 0.0)))
            self._spotter = spotter
            self.mic.subscribe(lambda f: spotter.feed(
                f, self.state in ("idle", "thinking") and time.monotonic() > max(self._quiet_until, self._wake_cooldown)
                and self._name_spotting_allowed(), self._wake_score))
        self.mic.start()

    # Сколько держать паузу между двумя рассылками списка окон. Буря геометрии (окно тянут за
    # угол) присылает десятки списков в секунду, и каждый — перерисовка дока.
    WINDOWS_QUIET = 0.18
