"""Правка одной настройки не должна ломать весь конфиг.

Это проверка на уже случившуюся поломку, а не на воображаемую. `set_value` узнавал секцию только
по строке ровно `[island]`, а в нашем же `config.example.toml` почти у каждой секции в той же
строке стоит пояснение. Поэтому `justday config set island.enabled false` не находил секцию и
дописывал вторую такую же в конец файла — а TOML с двумя одинаковыми секциями не читается вовсе.
Одна настройка, и конфиг перестаёт открываться целиком: ни островка, ни дока, ни голоса.
"""
from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from justday import config

EXAMPLE = Path(__file__).resolve().parents[1] / "config.example.toml"


@pytest.fixture
def conf(tmp_path, monkeypatch):  # type: ignore[no-untyped-def]
    path = tmp_path / "config.toml"
    path.write_text(EXAMPLE.read_text(encoding="utf-8"), encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_FILE", path)
    return path


def read(path: Path) -> dict:
    with path.open("rb") as fh:
        return tomllib.load(fh)


def test_section_with_comment_is_found(conf):
    """[island] с пояснением в строке — та же секция, а не повод создать вторую."""
    config.set_value("island", "enabled", False)
    data = read(conf)                      # падает, если файл стал невалидным
    assert data["island"]["enabled"] is False
    assert conf.read_text(encoding="utf-8").count("[island]") == 1


def test_three_parts_in_a_row(conf):
    """Установщик гасит сразу несколько частей; каждая следующая правка не ломает предыдущую."""
    for part in ("island", "dock", "tray"):
        config.set_value(part, "enabled", False)
    data = read(conf)
    assert [data[p]["enabled"] for p in ("island", "dock", "tray")] == [False, False, False]


def test_untouched_sections_keep_their_values(conf):
    """Правим одно — остальное остаётся как было, вместе с пояснениями человека."""
    before = read(conf)
    config.set_value("dock", "enabled", False)
    after = read(conf)
    assert after["island"] == before["island"]
    assert after["tray"] == before["tray"]
    assert "# spoken name → desktop id" in conf.read_text(encoding="utf-8")


def test_new_key_lands_inside_its_section(conf):
    """Ключа в секции нет — он появляется в ней, а не в следующей."""
    config.set_value("dock", "quiet", True)
    assert read(conf)["dock"]["quiet"] is True


def test_unknown_section_is_appended(conf):
    """Секции нет вовсе — её можно создать, и файл остаётся читаемым."""
    config.set_value("weather", "city", "Прага")
    assert read(conf)["weather"]["city"] == "Прага"
