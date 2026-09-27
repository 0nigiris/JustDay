"""Темп речи: сколько берёт на себя модель и сколько остаётся растяжению.

Растягивание готовой речи и есть тот металлический призвук, на который жалуются.
Проверяем главное: при обычных настройках растяжения почти нет, а просьба к
модели — есть.
"""

from __future__ import annotations

import pytest

from justday.tts import TTS


def голос(**cfg: object) -> TTS:
    tts = TTS.__new__(TTS)
    tts.cfg = {"speed": 1.0, "style": "", **cfg}
    return tts


class TestПросьбаКМодели:
    def test_быстрее_просится_словами(self) -> None:
        assert "faster" in голос(speed=1.2).instruct()

    def test_медленнее_тоже(self) -> None:
        assert "slower" in голос(speed=0.8).instruct()

    def test_обычный_темп_ничего_не_просит(self) -> None:
        assert голос(speed=1.0).instruct() == ""

    def test_свой_стиль_идёт_вперёд(self) -> None:
        got = голос(speed=1.2, style="спокойно, деловито").instruct()
        assert got.startswith("спокойно, деловито")
        assert "faster" in got


class TestОстатокРастяжения:
    @pytest.mark.parametrize("speed,предел", [(1.2, 1.08), (1.15, 1.04), (1.4, 1.18)])
    def test_растяжение_остаётся_мягким(self, speed: float, предел: float) -> None:
        """Раньше на 1,2 тянули всю речь целиком — отсюда и призвук."""
        tts = голос(speed=speed)
        assert speed / tts.native_pace() <= предел

    def test_обычный_темп_не_тянется_вовсе(self) -> None:
        tts = голос(speed=1.0)
        assert tts.native_pace() == 1.0
