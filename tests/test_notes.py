"""Планы в Obsidian: файл принадлежит человеку, а не программе."""

from __future__ import annotations

import pytest


@pytest.fixture
def notes(vault):  # type: ignore[no-untyped-def]
    from justday import notes as module

    return module


def test_пункт_ложится_под_сегодняшнее_число(notes, vault) -> None:  # type: ignore[no-untyped-def]
    notes.add("забрать посылку")
    text = (vault / "Планы.md").read_text(encoding="utf-8")
    assert "- [ ] забрать посылку" in text
    assert text.startswith("# Планы")


def test_второй_пункт_идёт_под_тот_же_день(notes, vault) -> None:  # type: ignore[no-untyped-def]
    notes.add("первый")
    notes.add("второй")
    text = (vault / "Планы.md").read_text(encoding="utf-8")
    assert text.count("## ") == 1
    assert text.index("первый") < text.index("второй")


def test_пометка_видна_отдельно_от_текста(notes) -> None:  # type: ignore[no-untyped-def]
    notes.add("позвонить маме", note="с телефона")
    item = notes.items()[0]
    assert item["text"] == "позвонить маме"
    assert item["note"] == "с телефона"


def test_закрытие_по_номеру_и_по_словам(notes) -> None:  # type: ignore[no-untyped-def]
    notes.add("первый")
    notes.add("второй")
    assert notes.mark_done("1")["ok"] is True
    # После закрытия первого нумерация открытых сдвигается: «1» — уже второй.
    assert notes.mark_done("втор")["ok"] is True
    assert notes.items(only_open=True) == []


def test_закрытие_несуществующего_не_падает(notes) -> None:  # type: ignore[no-untyped-def]
    notes.add("единственный")
    assert notes.mark_done("такого нет")["ok"] is False


def test_правки_руками_не_теряются(notes, vault) -> None:  # type: ignore[no-untyped-def]
    """Человек пишет в тот же файл: его заголовки и строки должны уцелеть."""
    plans = vault / "Планы.md"
    plans.write_text("# Планы\n\nМои мысли, не трогать.\n\n## 2020-01-01\n- [ ] старое\n",
                     encoding="utf-8")
    notes.add("новое")
    text = plans.read_text(encoding="utf-8")
    assert "Мои мысли, не трогать." in text
    assert "- [ ] старое" in text
    assert "- [ ] новое" in text


def test_заметка_не_уходит_за_пределы_хранилища(notes) -> None:  # type: ignore[no-untyped-def]
    got = notes.note("../../побег", "текст")
    # Опасные символы вычищаются, файл остаётся внутри.
    assert "/побег" not in got["file"]


def test_пустой_план_отвергается(notes) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValueError):
        notes.add("   ")


def test_ссылка_для_obsidian(notes, vault) -> None:  # type: ignore[no-untyped-def]
    notes.add("что-нибудь")
    link = notes.open_in_obsidian(str(vault / "Планы.md"))
    assert link.startswith("obsidian://open?vault=")
    assert "file=" in link
