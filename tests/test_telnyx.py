"""Настоящий звонок: Джарвис набирает номер и говорит в трубку.

Беды, ради которых написаны эти проверки, стоят денег. Звонок — единственное место в JustDay,
где ошибка в коде списывается с карты, поэтому проверяется не «работает ли», а «не разорит ли».
"""
from __future__ import annotations

import pytest

from justday import telnyx


def test_the_assistant_must_never_dial_a_premium_line() -> None:
    """Платные справочные (900, 902, 803, 806…) стоят не центы, а до 68 центов за минуту.

    Ассистент, который сам ищет номер в картах, однажды найдёт именно такой. Это не настройка
    и не предупреждение — такие номера он не набирает вовсе.
    """
    for bad in ("+34902123456", "+34900112233", "+34803555666", "+34806111222"):
        with pytest.raises(RuntimeError, match="справочная"):
            telnyx.check_number(bad)


def test_a_number_without_a_country_code_would_dial_somewhere_else() -> None:
    """«600111222» без кода страны — это не испанский мобильный, а неизвестно что.

    Набирать такое значит звонить наугад за чужой счёт. Проверка требует международного вида.
    """
    for bad in ("600111222", "8 800 555", "", "кебабня"):
        with pytest.raises(RuntimeError, match="международном"):
            telnyx.check_number(bad)


def test_an_ordinary_mobile_goes_through_untouched() -> None:
    """Обычный мобильный — это дешёвый случай ($0.023/мин), и ему мешать не надо."""
    assert telnyx.check_number("+34 612 345 678") == "+34612345678"
    assert telnyx.check_number("+1-555-010-9999") == "+15550109999"


def test_a_call_in_a_loop_would_run_for_an_hour_unnoticed() -> None:
    """Потолок по времени существует затем, что худший случай — шестьдесят центов, а не час.

    Разговор «вы сегодня открыты?» дольше полутора минут не бывает ни у кого.
    """
    assert telnyx.MAX_SECONDS <= 90, "потолок разговора вырос — незамеченный звонок станет дорогим"


def test_it_says_what_is_missing_instead_of_failing_silently(monkeypatch) -> None:
    """Без ключа, номера или туннеля звонок невозможен — и это надо сказать словами.

    Молчаливый отказ здесь означает, что человек ждёт звонка, которого не будет.
    """
    monkeypatch.setattr(telnyx, "key", lambda: "")
    ok, why = telnyx.ready()
    assert not ok and "secret-tool" in why, "про отсутствующий ключ никто не сказал"
    monkeypatch.setattr(telnyx, "key", lambda: "KEY")
    monkeypatch.setattr(telnyx, "settings", dict)
    ok, why = telnyx.ready()
    assert not ok and "номер" in why, "про отсутствующий свой номер никто не сказал"


def test_the_webhook_listener_binds_to_localhost_only() -> None:
    """Слушатель событий звонка не должен появляться на внешнем интерфейсе.

    Правило проекта: наружу не смотрит ничего. Публичный адрес даёт туннель — соединение,
    которое наша машина открывает сама, — а не открытый порт.
    """
    import inspect

    src = inspect.getsource(telnyx.call)
    assert '("127.0.0.1", port)' in src, "слушатель событий больше не привязан к localhost"
    assert "0.0.0.0" not in src, "порт открылся на внешнем интерфейсе"


def test_a_premium_number_was_refused_only_after_the_key_was_set(monkeypatch) -> None:
    """«Эту цифру не набирать» — запрет, а не следствие того, что ключ ещё не положен.

    Сначала проверка готовности отвечала «нет ключа» даже на платную справочную: человек клал
    ключ, покупал номер и только тогда узнавал настоящую причину отказа.
    """
    monkeypatch.setattr(telnyx, "key", lambda: "")
    got = telnyx.call("+34902123456", "проверка")
    assert "справочная" in got.get("error", ""), "платный номер отклоняется не первым делом"
