"""Пробуждение по имени: когда «Джарвис» — это зов, а когда послышалось."""

from __future__ import annotations

from justday import namespot

VARIANTS = namespot.spellings(["Джарвис", "JustDay"])


class TestРазборИмени:
    def test_имя_с_командой_в_одном_дыхании(self) -> None:
        hit, rest = namespot.split_name("Джарвис, открой калькулятор", VARIANTS)
        assert hit and rest == "открой калькулятор"

    def test_одно_имя_без_команды(self) -> None:
        hit, rest = namespot.split_name("Джарвис", VARIANTS)
        assert hit and rest == ""

    def test_обращение_посреди_фразы_не_будит(self) -> None:
        hit, _ = namespot.split_name("я сказал ему джарвис и он ответил", VARIANTS)
        assert not hit

    def test_похожие_написания_распознаются(self) -> None:
        for текст in ("джарвиз, что там", "jarvis, hello", "джастдей, привет"):
            hit, _ = namespot.split_name(текст, VARIANTS)
            assert hit, текст

    def test_эй_и_окей_перед_именем_разрешены(self) -> None:
        hit, rest = namespot.split_name("эй джарвис поставь таймер", VARIANTS)
        assert hit and rest == "поставь таймер"

    def test_имя_вырезается_с_сохранением_вида_фразы(self) -> None:
        assert namespot.strip_name("Джарвис, включи Rammstein!", VARIANTS) == "включи Rammstein!"


class TestДовериеКРаспознанному:
    """Whisper выдумывает имена в бормотании и фоне — на это и проверка."""

    def сделать(self, min_prob: float = namespot.MIN_NAME_PROB) -> namespot.NameSpotter:
        spotter = namespot.NameSpotter.__new__(namespot.NameSpotter)
        spotter.variants = VARIANTS
        spotter.min_prob = lambda: min_prob
        return spotter

    def test_тишина_не_будит(self) -> None:
        assert not self.сделать().believable("джарвис", [("джарвис", 0.9)], no_speech=0.8)

    def test_неуверенное_первое_слово_не_будит(self) -> None:
        assert not self.сделать().believable("джарвис", [("джарвис", 0.2)], no_speech=0.1)

    def test_повторённое_имя_это_галлюцинация(self) -> None:
        слова = [("джарвис", 0.9), ("джарвис", 0.8), ("джарвис", 0.8)]
        assert not self.сделать().believable("джарвис джарвис джарвис", слова, no_speech=0.1)

    def test_чёткий_зов_проходит(self) -> None:
        слова = [("джарвис", 0.8), ("открой", 0.9)]
        assert self.сделать().believable("джарвис открой", слова, no_speech=0.05)

    def test_повышенная_планка_отсекает_пограничное(self) -> None:
        """Пока играет музыка, микрофон слышит и её: планка выше."""
        слова = [("джарвис", 0.5), ("стоп", 0.9)]
        assert self.сделать().believable("джарвис стоп", слова, no_speech=0.05)
        assert not self.сделать(min_prob=0.65).believable("джарвис стоп", слова, no_speech=0.05)


class TestШпионНеГонитWhisperНаВсякуюРечь:
    """Прогон Whisper на каждый всплеск речи в комнате (5–7 тыс. в сутки) держал его в видеопамяти вечно
    (Р-30): шпион обязан будить его только там, где openWakeWord услышал что-то похожее на имя."""

    class Голос:
        level = 0.9

        def predict(self, frame, frame_size=0) -> float:
            return self.level

        def reset_states(self) -> None:
            pass

    def прогон(self, monkeypatch, score: float, floor: float, active: bool = True) -> int:
        import time

        import numpy as np

        from justday import audio

        голос = self.Голос()
        monkeypatch.setattr(audio, "voice_activity_model", lambda: голос)
        calls: list[int] = []

        def transcribe(clip):
            calls.append(len(clip))
            return "", [], 1.0

        spotter = namespot.NameSpotter(transcribe, ["Джарвис"], lambda: 0, lambda *a: None, floor=lambda: floor)
        frame = np.zeros(audio.FRAME, dtype=np.int16)
        for _ in range(8):  # речь
            spotter.feed(frame, active, score)
        голос.level = 0.0
        for _ in range(10):  # пауза — отрывок закончился
            spotter.feed(frame, active, 0.0)
        time.sleep(0.3)  # поток Whisper разбирает очередь
        return len(calls)

    def test_болтовня_без_намёка_на_имя_не_будит_whisper(self, monkeypatch) -> None:
        assert self.прогон(monkeypatch, score=0.01, floor=0.05) == 0

    def test_похожее_на_имя_доходит_до_whisper(self, monkeypatch) -> None:
        assert self.прогон(monkeypatch, score=0.2, floor=0.05) == 1

    def test_нулевая_планка_это_прежнее_поведение(self, monkeypatch) -> None:
        assert self.прогон(monkeypatch, score=0.0, floor=0.0) == 1


def test_смена_имени_просыпается_на_новое_и_не_на_старое():
    """Сменил имя на «Пятница» — не просыпался: варианты написания были только у «Джарвиса»."""
    for имя, сказано in [("Пятница", "пятнеца включи свет"), ("Пятница", "pyatnitsa открой почту"),
                         ("hey jarvis", "джарвис который час"), ("Jarvis", "джарвиз включи"),
                         ("Пятница", "эй пятница, привет")]:
        assert namespot.split_name(сказано, namespot.spellings([имя]))[0], (имя, сказано)
    нов = namespot.spellings(["Пятница"])
    assert not namespot.split_name("джарвис включи свет", нов)[0]
