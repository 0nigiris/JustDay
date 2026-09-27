"""Сценарии: несколько привычных действий одной фразой."""

from __future__ import annotations

import pytest

from justday import scenes


@pytest.fixture
def настройки(monkeypatch):  # type: ignore[no-untyped-def]
    def подставить(список):  # type: ignore[no-untyped-def]
        from justday import config

        monkeypatch.setattr(config, "load", lambda: {
            "scenes": список,
            "apps": {"aliases": {"дискорд": "org.equicord.equibop"}},
        })
    return подставить


class TestОписание:
    def test_список_из_таблиц(self, настройки) -> None:  # type: ignore[no-untyped-def]
        настройки([{"name": "Работа", "phrases": ["я сел работать"], "open": ["code"]}])
        scene = scenes.all_scenes()[0]
        assert scene["name"] == "Работа"
        assert scene["id"] == "работа"
        assert scene["open"] == ["code"]

    def test_запись_словарём_тоже_понимается(self, настройки) -> None:  # type: ignore[no-untyped-def]
        """`[scenes.работа]` — такая же понятная запись, как и `[[scenes]]`."""
        настройки({"работа": {"name": "Работа", "phrases": ["рабочий режим"]}})
        assert scenes.all_scenes()[0]["phrases"] == ["рабочий режим"]

    def test_мусор_в_настройках_не_роняет(self, настройки) -> None:  # type: ignore[no-untyped-def]
        настройки(["строка вместо таблицы", {"name": "Норм"}])
        assert [s["name"] for s in scenes.all_scenes()] == ["Норм"]

    def test_команды_только_списком_аргументов(self, настройки) -> None:  # type: ignore[no-untyped-def]
        """Строка для оболочки сюда не попадёт: `rm -rf` из-за кавычки исключён."""
        настройки([{"name": "С", "run": ["rm -rf /", ["justday", "status"]]}])
        assert scenes.all_scenes()[0]["run"] == [["justday", "status"]]


class TestУзнаваниеФразы:
    def test_фраза_целиком(self, настройки) -> None:  # type: ignore[no-untyped-def]
        настройки([{"name": "Работа", "phrases": ["я сел работать", "рабочий режим"]}])
        assert scenes.match("Я сел работать")["name"] == "Работа"
        assert scenes.match("рабочий режим!")["name"] == "Работа"
        assert scenes.match("работа")["name"] == "Работа"  # само имя тоже зовёт

    def test_разговор_не_считается_кнопкой(self, настройки) -> None:  # type: ignore[no-untyped-def]
        настройки([{"name": "Работа", "phrases": ["я сел работать"]}])
        assert scenes.match("я сел работать, а ещё поставь музыку и скажи погоду") is None
        assert scenes.match("") is None

    def test_поиск_по_идентификатору(self, настройки) -> None:  # type: ignore[no-untyped-def]
        настройки([{"id": "work", "name": "Работа"}])
        assert scenes.by_id("work")["name"] == "Работа"
        assert scenes.by_id("нет такого") is None


class TestИсполнение:
    def test_что_сделал_сказано_словами(self) -> None:
        line = scenes.summary({"scene": "Работа", "opened": ["code"], "closed": ["steam"], "failed": []})
        assert "Работа" in line and "code" in line and "steam" in line

    def test_ненайденное_названо_честно(self) -> None:
        line = scenes.summary({"scene": "Работа", "opened": [], "closed": [], "failed": ["фотошоп"]})
        assert "фотошоп" in line
