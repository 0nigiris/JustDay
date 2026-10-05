"""Обещания (пункт 20, ступень 5): «что я обещал Илье?» должно отвечаться списком, а не поиском по памяти."""
from __future__ import annotations

from justday import config, promises


def test_обещание_записывается_и_находится(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(promises, "FILE", tmp_path / "promises.jsonl")
    promises.add("скинуть ссылку на статью", to="Илье", due="до пятницы")
    promises.add("забрать посылку", to="маме")
    assert [i["to"] for i in promises.open_items()] == ["Илье", "маме"]
    assert [i["text"] for i in promises.open_items("илье")] == ["скинуть ссылку на статью"]
    assert promises.find("ссылку")[0]["due"] == "до пятницы"
    assert oct((tmp_path / "promises.jsonl").stat().st_mode & 0o777) == "0o600"


def test_выполненное_уходит_из_открытых_но_находится(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(promises, "FILE", tmp_path / "promises.jsonl")
    promises.add("скинуть ссылку", to="Илье")
    assert promises.done("ссылку")["ok"]
    assert promises.open_items() == []
    assert promises.find("ссылку")  # «я же это сделал?»


def test_неоднозначное_слово_не_закрывает_чужое_обещание(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(promises, "FILE", tmp_path / "promises.jsonl")
    promises.add("скинуть ссылку", to="Илье")
    promises.add("скинуть деньги", to="маме")
    got = promises.done("скинуть")
    assert not got["ok"] and len(got["candidates"]) == 2
    assert len(promises.open_items()) == 2


def test_битая_строка_не_уносит_список(tmp_path, monkeypatch) -> None:
    f = tmp_path / "promises.jsonl"
    monkeypatch.setattr(promises, "FILE", f)
    promises.add("позвонить")
    f.write_text(f.read_text(encoding="utf-8") + "{обрыв\n", encoding="utf-8")
    assert len(promises.open_items()) == 1
    assert config.DATA_DIR  # модуль живёт в данных пользователя, а не в репозитории
