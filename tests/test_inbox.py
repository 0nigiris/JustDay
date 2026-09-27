"""Сообщения, оставленные с телефона, пока компьютера не было."""

from __future__ import annotations

import time

import pytest


@pytest.fixture
def inbox(state_dir, monkeypatch):  # type: ignore[no-untyped-def]
    from justday import inbox as module

    monkeypatch.setattr(module, "FILE", state_dir / "inbox.jsonl")
    return module


def test_сообщение_сохраняет_время_набора(inbox) -> None:  # type: ignore[no-untyped-def]
    """Час в дороге — важная часть смысла: «поставь таймер» тогда и сейчас разное."""
    записали = time.time() - 3600
    item = inbox.add("поставь обновление", created=записали)
    assert item["created"] == pytest.approx(записали)
    assert item["received"] > item["created"]


def test_пустое_сообщение_отвергается(inbox) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(ValueError):
        inbox.add("   ")


def test_доложенное_больше_не_всплывает(inbox) -> None:  # type: ignore[no-untyped-def]
    first = inbox.add("первое")
    inbox.add("второе")
    assert len(inbox.pending()) == 2
    assert inbox.mark_reported([first["id"]]) == 1
    assert [i["text"] for i in inbox.pending()] == ["второе"]
    # История остаётся: доложенное видно в списке, просто не ждёт доклада.
    assert len(inbox.recent()) == 2


def test_повторный_доклад_ничего_не_меняет(inbox) -> None:  # type: ignore[no-untyped-def]
    item = inbox.add("раз")
    inbox.mark_reported([item["id"]])
    assert inbox.mark_reported([item["id"]]) == 0


def test_битые_строки_не_ломают_чтение(inbox) -> None:  # type: ignore[no-untyped-def]
    """Файл дописывается построчно: оборванная запись не должна ронять всё."""
    inbox.add("целое")
    with inbox.FILE.open("a", encoding="utf-8") as fh:
        fh.write('{"id": "обор\n')
    assert [i["text"] for i in inbox.pending()] == ["целое"]


def test_сводка_читается_человеком(inbox) -> None:  # type: ignore[no-untyped-def]
    inbox.add("купить хлеб", created=time.mktime((2026, 9, 27, 14, 30, 0, 0, 0, -1)))
    line = inbox.summary(inbox.pending())
    assert "27.09 14:30" in line
    assert "купить хлеб" in line


def test_список_не_растёт_без_края(inbox) -> None:  # type: ignore[no-untyped-def]
    for i in range(210):
        inbox.add(f"сообщение {i}")
    assert len(inbox.recent(1000)) == 200
