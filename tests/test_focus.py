"""Тишина по расписанию: в школе Джарвис не должен говорить вслух, а ночное окно не должно обрываться полуночью."""
from __future__ import annotations

from datetime import datetime

from justday import focus

ШКОЛА = {"name": "Школа", "days": "пн-пт", "from": "08:30", "to": "15:00"}
НОЧЬ = {"name": "Ночь", "from": "23:00", "to": "07:00"}


def в(день: str, время: str) -> datetime:
    # 5 октября 2026 — понедельник
    d = {"пн": 5, "вт": 6, "пт": 9, "сб": 10, "вс": 11}[день]
    h, m = map(int, время.split(":"))
    return datetime(2026, 10, d, h, m)


def test_в_школе_тихо_а_в_субботу_нет() -> None:
    assert focus.active([ШКОЛА], в("пн", "10:00")) == "Школа"
    assert focus.active([ШКОЛА], в("пн", "15:00")) == ""
    assert focus.active([ШКОЛА], в("сб", "10:00")) == ""


def test_ночное_окно_не_обрывается_полуночью() -> None:
    assert focus.active([НОЧЬ], в("пн", "23:30")) == "Ночь"
    assert focus.active([НОЧЬ], в("вт", "03:00")) == "Ночь"
    assert focus.active([НОЧЬ], в("вт", "07:00")) == ""


def test_ночное_окно_пятницы_кончается_в_субботу_утром() -> None:
    ночь_будней = {**НОЧЬ, "days": "пн-пт"}
    assert focus.active([ночь_будней], в("сб", "03:00")) == "Ночь"   # началось в пятницу
    assert focus.active([ночь_будней], в("вс", "03:00")) == ""       # началось бы в субботу


def test_битая_запись_не_включает_тишину_и_не_роняет() -> None:
    assert focus.active([{"name": "x", "from": "утро", "to": "вечер"}, {"from": "10:00"}], в("пн", "10:00")) == ""
    assert focus.active([], в("пн", "10:00")) == ""


def test_чужой_пароль_флешки_всегда_честная_ошибка(monkeypatch) -> None:
    """Расшифровка с чужим паролем в одном случае из 256 давала мусор с годным заполнением и падала не тем."""
    import pytest

    from justday import portable

    monkeypatch.setattr(portable, "_openssl", lambda args, data, pw: b"\xff\xfe junk")
    with pytest.raises(RuntimeError):
        portable.unseal(b"x", "чужой")
