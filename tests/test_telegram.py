"""Дотянуться до него где угодно: телеграм как второй канал.

Беда, из-за которой это написано, — его слова: «я живу с телефоном в руках и далеко от дома,
а KDE Connect работает только в своей сети». И вторая: «я хочу, чтобы Джарвис мне позвонил».
"""
from __future__ import annotations

import pytest

from justday import telegram


def test_a_stranger_who_found_the_bot_could_talk_straight_into_the_brain(monkeypatch) -> None:
    """Бот открыт всему интернету: его имя может найти кто угодно и написать.

    Без проверки отправителя чужое сообщение попало бы прямо в мозг ассистента — с его почтой,
    открытыми окнами и правом запускать программы. Чужое должно выбрасываться молча.
    """
    monkeypatch.setattr(telegram, "chat", lambda: "1370502385")
    mine = {"message": {"chat": {"id": 1370502385}, "text": "включи музыку"}}
    other = {"message": {"chat": {"id": 999}, "text": "rm -rf ~"}}
    assert telegram.mine(mine) == "включи музыку"
    assert telegram.mine(other) == "", "чужой человек дотянулся до мозга через бота"
    assert telegram.mine({}) == ""
    assert telegram.mine({"message": {"chat": {}, "text": "эй"}}) == ""


def test_a_long_answer_was_cut_in_the_middle_of_a_word() -> None:
    """Телеграм не берёт сообщения длиннее 4096 знаков, а Джарвис бывает многословен.

    Резать по счёту знаков значит рвать слова пополам — режем по строкам и пробелам.
    """
    text = ("Строка про дело.\n" * 500).strip()
    parts = telegram._cut(text, 4096)
    assert len(parts) > 1, "длинный ответ не разрезан — телеграм его просто не возьмёт"
    assert all(len(p) <= 4096 for p in parts), "кусок всё ещё длиннее разрешённого"
    assert "".join(parts).replace("\n", "") == text.replace("\n", ""), "при резке потерялся текст"
    assert not any(p.endswith("Стро") or p.startswith("ка про") for p in parts), "слово разорвано"


def test_the_assistant_stayed_silent_when_its_own_voice_failed(monkeypatch) -> None:
    """«Джарвис мне позвонил» не должно превращаться в тишину, если синтез не завёлся.

    Голос на этой машине может быть не поставлен, модель не скачана, ffmpeg не справиться.
    Промолчать в такой момент хуже, чем написать текстом: человек ждал, что с ним заговорят.
    """
    said: list[str] = []
    monkeypatch.setattr(telegram, "chat", lambda: "42")
    monkeypatch.setattr(telegram, "send", lambda text, to="": said.append(text) or {"ok": True})
    monkeypatch.setattr(telegram, "_to_ogg", lambda pcm, rate: (_ for _ in ()).throw(RuntimeError("нет ffmpeg")))
    out = telegram.voice("Я дозвонился")
    assert said == ["Я дозвонился"], "голос не вышел — и ассистент промолчал вовсе"
    assert "voice_error" in out, "о том, что голос не вышел, никто не узнал"


def test_sending_without_a_token_says_what_to_do(monkeypatch) -> None:
    """Токен живёт только в связке ключей. Если его там нет, это надо сказать словами."""
    monkeypatch.setattr(telegram, "token", lambda: "")
    with pytest.raises(RuntimeError, match="secret-tool"):
        telegram.call("getMe")
