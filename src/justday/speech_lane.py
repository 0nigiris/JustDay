"""Речь демона: голос вкл/выкл, очередь фраз, потоковый синтез, сигналы.

Вынесено из daemon.py (Р-80). Миксин: тела методов не менялись, `self` — демон."""
from __future__ import annotations

import asyncio
import logging
import re
import time

import numpy as np

from . import (
    audio,
    config,
    desktop,
    events,
)
from . import tts as tts_mod
from .i18n import t
from .tts import normalize, split_sentences

log = logging.getLogger("justday.daemon")

# Bare acknowledgements ("Готово.", "Открыл терминал.") are replaced by the "done" earcon.
ACK = re.compile(r"^\W*(?:(?:готово|окей|ок|хорошо|done|ok)\W+)?(готово|сделано|сделал|есть|окей|ок|хорошо|выполнено|принято|done|"
                 r"(открыл|запустил|включил|закрыл|свернул|переключил|поставил|выключил|включаю|ставлю|запускаю|"
                 r"включено|играет|играю|вот|now playing|playing)[\w\s«»\"'.,:—–-]{0,70})\W*$", re.I)
# «Выпало "…". Включаю.» — an announcement of a start is not an answer either, wherever the verb sits
ACK_TAIL = re.compile(r"(включаю|ставлю|запускаю|показываю|ищу|сейчас будет|playing|now playing)\s*[.!…]*$", re.I)


class SpeechMixin:
    async def set_voice(self, on: bool) -> None:
        """«молчи» / «говори»: only the voice stops — the island still shows every answer."""
        config.set_value("tts", "muted", not on)
        self.cfg["tts"]["muted"] = not on
        said = t("голос включён") if on else t("голос выключен")
        events.emit("fast", text=said, desc=said)
        self.publish(detail=said, kind="tool")
        self.brain.note(f"[Уже выполнено: {said}. Не повторяй.]")
        if on:
            await self.say(said)
        self.state = "thinking" if self.brain.busy else "idle"

    async def _on_brain_text(self, text: str, force: bool = False, private: bool = False) -> None:
        if not force and (why := self.silent()):
            events.emit("say_suppressed", text="" if private else text[:200], reason=why)
            return
        if ACK.match(text.strip()) and len(text) < 60:
            events.emit("ack_suppressed", text=text)
            return
        if ACK_TAIL.search(text.strip()) and len(text) < 140:
            events.emit("ack_suppressed", text=text)
            return
        # «включи…» is answered by the music itself. Whatever the model wants to add about the track
        # («это трек Тоби Фокса, включаю») answers nothing, so it is not spoken — unless it asks
        # something or is long enough to be a real answer.
        if time.monotonic() - self._music_started < 40 and "?" not in text and len(text) < 220:
            events.emit("ack_suppressed", text=text)
            return
        self._spoken += 1
        lang = self.cfg["user"].get("language", "ru")
        self.tts.cfg["lang"] = lang
        for s in split_sentences(normalize(text, lang, tts_mod.latin_mode(self.tts.cfg),
                                           bool(self.tts.cfg.get("numbers", True)))):
            self._speech_q.put_nowait(s)
            self._synth_in_advance(s)

    async def say(self, text: str, force: bool = False, private: bool = False) -> None:
        await self._on_brain_text(text, force, private)

    def _synth_in_advance(self, sentence: str) -> None:
        """Голос, который синтезирует фразу целиком (Silero, espeak), начинает следующую, пока играет
        предыдущая: раньше каждая ждала конца предыдущей и потом ещё 0,1–0,5 с собственного синтеза (Р-53).
        Потоковые голоса (Qwen, ElevenLabs) не тронуты: они и так играют по мере генерации."""
        engine = self.tts.cfg["engine"]
        if engine in ("qwen", "elevenlabs", "chatterbox", "none") or sentence in self._synth_ahead:
            return
        try:
            self._synth_ahead[sentence] = asyncio.get_running_loop().run_in_executor(None, self.tts.synth, sentence)
        except RuntimeError:  # цикла нет — синтезировать некому, воркер сделает сам
            pass

    def stop_speaking(self) -> None:
        self._synth_ahead.clear()  # не cancel: ждущий воркер получил бы CancelledError и умер бы вместе с голосом
        self._speech_gen += 1
        while not self._speech_q.empty():
            self._speech_q.get_nowait()
        self.player.stop()

    async def _speech_worker(self) -> None:
        loop = asyncio.get_running_loop()
        while True:
            sentence = await self._speech_q.get()
            gen = self._speech_gen
            try:
                engine = self.tts.cfg["engine"]
                # Отказ ElevenLabs (кончились кредиты, голос не для бесплатного тарифа) — сразу Silero.
                # Раньше запасным был Qwen: 3,4 ГБ видеопамяти и полминуты холодного старта на
                # каждый такой отказ. И не стучаться к нему каждой фразой, пока не остынет.
                if (engine == "elevenlabs" and time.monotonic() >= self._neural_cold_until
                        and await self._speak_stream(sentence, gen, "elevenlabs")):
                    continue
                if (engine == "qwen" and time.monotonic() >= self._neural_cold_until
                        and await self._speak_stream(sentence, gen, "qwen")):
                    continue
                if (engine == "chatterbox" and time.monotonic() >= self._neural_cold_until and not self._gpu_taken()
                        and await self._speak_stream(sentence, gen, "chatterbox")):
                    continue
                ahead = self._synth_ahead.pop(sentence, None)
                pcm = await (ahead or loop.run_in_executor(None, self.tts.synth, sentence))
                if gen != self._speech_gen or not len(pcm):
                    continue
                self.state = "speaking"
                # Перебивания голосом (Р2-35) здесь нет нарочно: 13 окт его добавили через VAD на
                # микрофоне во время ответа, и Silero замолчал совсем (TypeError на каждой фразе),
                # а потоковые голоса без эхоподавления слышали себя из колонок и обрывались.
                # Возвращать — только с эхоподавлением или настройкой «я в наушниках».
                await self.player.play(pcm, self.tts.rate)
                if self.state == "speaking":
                    self.state = "thinking" if self.brain.busy else "idle"
            except Exception:
                log.exception("speech failed")

    def _gpu_taken(self) -> bool:
        """Chatterbox делит видеокарту с игрой или монтажом — и тогда лагают оба. Его просьба 7 октября:
        «если видеокарта сильно используется — пусть переключается на Silero, чтобы не лагало»."""
        return bool(desktop.running_game() or self.tts.gpu_busy())

    async def _speak_stream(self, sentence: str, gen: int, engine: str) -> bool:
        """Stream one sentence from a voice that generates as it speaks (the local neural service or ElevenLabs).

        False = this voice is unavailable, and the caller falls back to the next one."""
        if engine == "elevenlabs":
            stream, rate, native = self.tts.eleven_stream(sentence), self.tts.ELEVEN_RATE, max(0.7, min(1.2, self.tts.speed))
        else:
            # Нейроголос набирает темп сам, по словесной просьбе (`instruct`), но
            # на глаз: от фразы к фразе выходит то быстрее, то медленнее. Поэтому
            # большую часть ускорения берёт на себя модель, а остаток — мягкое
            # растяжение: 1,07 вместо 1,2 слышно несравнимо меньше.
            stream, rate = self.tts.stream(sentence), self.tts.NEURAL_RATE
            native = self.tts.native_pace() if engine == "qwen" else 1.0  # Chatterbox просьб о темпе не понимает
        stretch = audio.Stretcher(self.tts.speed / native, rate)
        try:
            first = await stream.__anext__()
        except StopAsyncIteration:
            return True
        except OSError as e:
            if not self._voice_warned:
                self._voice_warned = True
                log.warning("%s voice unavailable (%s), falling back", engine, e)
            # И больше не стучаться к нему каждой фразой. Нейроголос падает не разово: кончилась
            # видеопамять — значит кончилась и на следующую фразу, а ожидание отказа человек
            # слышит как задержку перед каждым словом. Это и есть «голос лагает».
            self._neural_cold_until = time.monotonic() + 60 * float(
                self.cfg["tts"].get("retry_minutes", 10) or 0)
            return False
        self._voice_warned = False
        self._neural_cold_until = 0.0
        if gen != self._speech_gen:
            await stream.aclose()
            return True

        # jitter buffer: start playing only with ~0.4 s in hand, so a busy GPU doesn't tear the voice apart
        head = [first]
        buffered = len(first)
        try:
            while buffered < rate * 2 * 0.4:
                data = await stream.__anext__()
                head.append(data)
                buffered += len(data)
        except StopAsyncIteration:
            pass
        except OSError:
            log.warning("%s stream broke while buffering", engine)

        def faster(data: bytes) -> bytes:
            """The voice speaks at its own pace; this is the pace the user set."""
            if stretch.passthrough:
                return data
            return stretch.feed(np.frombuffer(data, dtype=np.int16)).tobytes()

        async def chunks():
            for data in head:
                out = faster(data)
                if out:
                    yield out
            async for data in stream:
                if gen != self._speech_gen:
                    break
                out = faster(data)
                if out:
                    yield out
            rest = stretch.drain()
            if rest.size:
                yield rest.tobytes()

        self.state = "speaking"
        try:
            await self.player.play_stream(chunks(), rate)
        except OSError:
            log.warning("%s stream broke", engine)
        if self.state == "speaking":
            self.state = "thinking" if self.brain.busy else "idle"
        return True

    async def wait_speech_done(self) -> None:
        while not self._speech_q.empty() or self.player.playing:
            await asyncio.sleep(0.1)

    async def earcon(self, kind: str) -> None:
        if self.cfg["audio"]["earcons"]:
            await self.player.play(audio.earcon(kind), 48000)
