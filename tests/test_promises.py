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


def test_параллельные_обещания_не_теряются_и_не_делят_номер(tmp_path) -> None:
    """Голос и CLI писали одновременно: оба читали один список, брали один номер, и вторая запись затирала первую."""
    import subprocess
    import sys

    f = tmp_path / "promises.jsonl"
    code = ("import sys; from pathlib import Path; from justday import promises; promises.FILE = Path(sys.argv[1]); "
            "[promises.add(f'дело {sys.argv[2]}-{k}') for k in range(15)]")
    procs = [subprocess.Popen([sys.executable, "-c", code, str(f), str(n)]) for n in range(6)]
    assert all(p.wait() == 0 for p in procs)
    promises.FILE = f
    try:
        ids = [i["id"] for i in promises._all()]
    finally:
        promises.FILE = config.DATA_DIR / "promises.jsonl"
    assert sorted(ids) == list(range(1, 91))
