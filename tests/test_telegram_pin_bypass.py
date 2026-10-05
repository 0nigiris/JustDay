"""Замок PIN обходился кнопкой «Разрешить» и геопозицией: их проверяли раньше PIN."""
from justday import telegram as tg


def test_locked_gate_is_not_open_for_buttons_and_location():
    gate = tg.PinGate(pin=lambda: "4821", clock=lambda: 100.0)
    assert not gate.is_open()


def test_gate_opens_after_the_pin_and_without_a_pin_at_all():
    now = [100.0]
    gate = tg.PinGate(pin=lambda: "4821", clock=lambda: now[0])
    assert gate.check("4821") == "unlocked" and gate.is_open()
    assert tg.PinGate(pin=lambda: "", clock=lambda: 0.0).is_open()
