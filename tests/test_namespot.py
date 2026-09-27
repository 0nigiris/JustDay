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
