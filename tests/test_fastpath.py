"""Мгновенный путь: что выполняется без модели, а что обязано до неё дойти.

Цена ошибки здесь несимметричная. Пропустить сложную просьбу в мгновенный путь
значит сделать не то, что просили; отдать простую модели — всего лишь потратить
секунду и немного денег. Поэтому проверок «этого делать не должен» больше.
"""

from __future__ import annotations

import pytest

from justday import fastpath


class TestНовыйРазговор:
    def test_понимает_разные_формулировки(self) -> None:
        for фраза in ("начни заново", "начнём с нуля", "сбрось контекст",
                      "новый разговор", "новая тема", "забудь разговор",
                      "start over", "new chat"):
            assert fastpath.wants_fresh_session(фраза), фраза

    def test_не_срабатывает_на_похожем(self) -> None:
        for фраза in ("заново", "переделай заново", "начни заново делать домашку",
                      "забудь про хлеб", "новая тема для видео про котов"):
            assert not fastpath.wants_fresh_session(фраза), фраза


class TestГолос:
    def test_молчи_и_говори(self) -> None:
        assert fastpath.voice_switch("молчи") is False
        assert fastpath.voice_switch("выключи голос") is False
        assert fastpath.voice_switch("говори") is True
        assert fastpath.voice_switch("включи голос") is True

    def test_остальное_не_про_голос(self) -> None:
        assert fastpath.voice_switch("включи музыку") is None
        assert fastpath.voice_switch("выключи свет") is None


class TestУходИВозвращение:
    def test_фразы_про_уход(self) -> None:
        assert fastpath.session_switch("я ушёл") == "close"
        assert fastpath.session_switch("закрой все программы") == "close"
        assert fastpath.session_switch("я вернулся") == "restore"

    def test_обычная_просьба_не_закрывает_всё(self) -> None:
        assert fastpath.session_switch("закрой дискорд") is None
        assert fastpath.session_switch("я ушёл в магазин, купи хлеб") is None


class TestОчисткаФразы:
    def test_вежливость_и_обращения_выбрасываются(self) -> None:
        assert fastpath._clean("Джарвис, пожалуйста, открой дискорд") == "открой дискорд"

    def test_ё_и_знаки_не_мешают(self) -> None:
        assert fastpath._clean("Молчи!!!") == "молчи"


class TestЧтоНеДолжноИдтиМимоМодели:
    @pytest.mark.parametrize("фраза", [
        "открой мой проект на гитхабе",
        "включи ту музыку, что вчера",
        "закрой все вкладки в браузере",
        "открой файл с отчётом",
        "запусти то, что я просил утром",
    ])
    def test_сложное_уходит_модели(self, фраза: str) -> None:
        """`_app` отказывается угадывать, когда в просьбе есть контекст."""
        assert fastpath.try_handle(фраза) is None

    def test_слишком_длинная_фраза_не_мгновенная(self) -> None:
        assert fastpath.try_handle("открой " + "очень " * 20 + "длинное") is None
