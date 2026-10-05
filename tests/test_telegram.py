"""Дотянуться до него где угодно: телеграм как второй канал.

Беда, из-за которой это написано, — его слова: «я живу с телефоном в руках и далеко от дома,
а KDE Connect работает только в своей сети». И вторая: «я хочу, чтобы Джарвис мне позвонил».
"""
from __future__ import annotations

import asyncio
import json

import pytest

from justday import telegram, telegram_shell


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
    # Настоящий синтез тут не нужен: он грузил Silero через torch (2 с, SyntaxWarning, а раз — и падение
    # процесса по SIGSEGV посреди прогона). Падать должен ffmpeg, а голос просто что-то отдаёт.
    import numpy as np

    from justday import tts

    monkeypatch.setattr(tts.TTS, "synth", lambda self, text: np.ones(100, dtype=np.int16))
    out = telegram.voice("Я дозвонился")
    assert said == ["Я дозвонился"], "голос не вышел — и ассистент промолчал вовсе"
    assert "voice_error" in out, "о том, что голос не вышел, никто не узнал"


def test_sending_without_a_token_says_what_to_do(monkeypatch) -> None:
    """Токен живёт только в связке ключей. Если его там нет, это надо сказать словами."""
    monkeypatch.setattr(telegram, "token", lambda: "")
    with pytest.raises(RuntimeError, match="secret-tool"):
        telegram.call("getMe")


def test_terminal_answers_kept_code_monospace_and_within_telegram_limit(monkeypatch) -> None:
    """Ответ оболочки с кодом нельзя превращать в нечитаемый обычный текст или рвать на лимите."""
    sent = []
    monkeypatch.setattr(telegram, "chat", lambda: "42")
    monkeypatch.setattr(telegram, "call", lambda method, params: sent.append(params) or {})
    source = "Собрал:\n```python\nprint('<ok>')\n```\n" + "x" * 5000

    telegram.send_shell(source)

    assert len(sent) >= 3
    assert all(len(item["text"]) <= 4096 for item in sent)
    assert sent[0]["parse_mode"] == "HTML"
    assert sent[1]["text"].startswith("<pre>print('&lt;ok&gt;')")
    assert sent[1]["text"].endswith("</pre>")


def test_remote_terminal_kept_queued_phone_tasks_in_order(monkeypatch, tmp_path) -> None:
    """Задачи с телефона должны пройти той же лестницей по одной, не затерев друг друга."""
    from types import SimpleNamespace

    ran, replies = [], []

    class Work:
        def __init__(self, _cfg):
            self.now = SimpleNamespace(model="haiku", label="Claude Code · haiku")
            self.rungs = [SimpleNamespace(engine="claude")]
            self.skipped = []
            self.step = 0

        async def send(self, task):
            ran.append(task)
            return SimpleNamespace(text=f"готово: {task}", error="")

    monkeypatch.setattr(telegram_shell.terminal, "Work", Work)
    monkeypatch.setattr(telegram_shell.config, "load", lambda: {})
    monkeypatch.setattr(telegram_shell.config, "STATE_DIR", tmp_path)
    async def reply(text):
        replies.append(text)
    async def send_shell(_text):
        return {}
    monkeypatch.setattr(telegram_shell.TelegramShell, "reply", lambda self, text: reply(text))
    monkeypatch.setattr(telegram, "send_shell", send_shell)

    async def run():
        shell = telegram_shell.TelegramShell(SimpleNamespace())
        await shell.message({"message": {"text": "/задача первая", "chat": {"id": 42}}})
        await shell.message({"message": {"text": "/задача вторая", "chat": {"id": 42}}})
        await shell.worker
        return shell

    shell = asyncio.run(run())
    assert ran == ["первая", "вторая"]
    assert len(replies) == 2
    assert "Ответ: готово: вторая" in shell.journal.read_text(encoding="utf-8")


def test_dangerous_terminal_action_waited_for_its_telegram_button(monkeypatch) -> None:
    """Опасное действие из оболочки нельзя считать разрешённым по молчанию или чужой кнопке."""
    from types import SimpleNamespace

    monkeypatch.setattr(telegram_shell.config, "load", lambda: {})
    monkeypatch.setattr(telegram, "chat", lambda: "42")
    calls = []
    monkeypatch.setattr(telegram, "call", lambda method, params: calls.append((method, params)) or {})

    async def run():
        shell = telegram_shell.TelegramShell(SimpleNamespace())
        request = asyncio.create_task(shell.approve("удалить файл", "нужен доступ"))
        while not calls:
            await asyncio.sleep(0)
        ident = next(iter(shell.pending))
        buttons = json.loads(calls[0][1]["reply_markup"])["inline_keyboard"][0]
        assert buttons[0]["callback_data"] == f"approve:{ident}:yes"
        assert buttons[1]["callback_data"] == f"approve:{ident}:no"
        wrong = {"callback_query": {"id": "foreign", "data": f"approve:{ident}:yes",
                                    "message": {"chat": {"id": 999}}}}
        assert telegram.mine_callback(wrong) is None
        right = {"callback_query": {"id": "owner", "data": f"approve:{ident}:yes",
                                     "message": {"chat": {"id": 42}}}}
        assert await shell.callback(right)
        return await request

    assert asyncio.run(run()) is True


def test_remote_ladder_keeps_opencode_but_only_through_the_permission_bridge(monkeypatch) -> None:
    """Запасная ступень с правом исполнять инструменты не должна обходить Telegram-подтверждение: она идёт
    через мост (`ocbridge`), где опасный шаг ждёт кнопки, а не через `opencode run`, который не спрашивает."""
    from types import SimpleNamespace

    class Work:
        def __init__(self, _cfg):
            self.now = SimpleNamespace(model="opus", label="Claude Code · opus")
            self.rungs = [SimpleNamespace(engine="claude"), SimpleNamespace(engine="opencode")]
            self.skipped = []
            self.step = 0
            self.bridge = False

    monkeypatch.setattr(telegram_shell.terminal, "Work", Work)
    monkeypatch.setattr(telegram_shell.config, "load", lambda: {})
    shell = telegram_shell.TelegramShell(SimpleNamespace())
    assert [r.engine for r in shell.work.rungs] == ["claude", "opencode"]
    assert shell.work.bridge is True and shell.work.skipped == []
