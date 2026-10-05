"""Пункт 16: «от конца фразы до первого слова» не измерено — в журнале время шло с точностью до секунды.
Теперь у каждого события есть `t` в секундах с долями, и задержку между событиями можно посчитать."""
import time

from justday import events


def test_events_carry_a_millisecond_clock(state_dir) -> None:
    before = time.time()
    events.emit("heard", text="привет")
    time.sleep(0.02)
    events.emit("say", text="здравствуйте")
    first, second = events.read()[-2:]
    assert before - 0.001 <= first["t"] < second["t"]     # t округлён до миллисекунды
    assert 0.015 < second["t"] - first["t"] < 1.0       # разницу видно и она не округлена до секунды


def test_nudges_lists_only_what_the_assistant_said_first(state_dir) -> None:
    """Мерка пункта 20 — «ни одного лишнего»: чтобы её применить, надо видеть, что он сказал первым."""
    from justday import observer

    events.emit("heard", text="привет")
    events.emit("nudge", text="Встреча через 20 минут")
    events.emit("say", text="здравствуйте")
    assert [n["text"] for n in observer.nudges()] == ["Встреча через 20 минут"]
    assert observer.nudges("2001-01-01") == []
