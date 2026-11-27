"""Филин в JustDay: о срабатывании он узнавал, только открыв папку со снимками."""
import sys
import types

from justday import filin


def _setup(tmp_path, monkeypatch):
    out = tmp_path / "Филин"
    out.mkdir()
    monkeypatch.setitem(sys.modules, "filin", types.SimpleNamespace(OUT=out))
    monkeypatch.setattr(filin, "SEEN", tmp_path / "state" / "filin-seen")
    return out / "журнал.txt"


def test_touch_while_away_is_told_once(tmp_path, monkeypatch):
    """Новое срабатывание — одна весть, и не повторяется каждую минуту."""
    log = _setup(tmp_path, monkeypatch)
    log.write_text("2026-11-20_10-00-00  тронули: Logitech; экран заперт; фото …\n", encoding="utf-8")
    assert filin.news() == []  # старое он уже видел в папке: не вываливать при первом запуске
    with open(log, "a", encoding="utf-8") as f:
        f.write("2026-11-27_23-10-00  тронули: Keychron; экран заперт; фото …\n"
                "2026-11-27_23-10-00  в телеграм не ушло: нет сети\n")
    assert [ln.split("  ")[1] for ln in filin.news()] == ["тронули: Keychron; экран заперт; фото …"]
    assert filin.news() == []
