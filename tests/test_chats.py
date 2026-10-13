"""Чат: беда — id из окна мог вывести запись за папку чатов, а оборванная строка — потерять весь чат."""
from pathlib import Path

import pytest

from justday import chats, config


@pytest.fixture(autouse=True)
def _dir(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)


def test_id_cannot_leave_the_chats_folder():
    with pytest.raises(ValueError):
        chats.messages("../../x")


def test_a_torn_last_line_does_not_lose_the_chat():
    cid = chats.create()
    chats.append(cid, "user", "привет")
    with chats._path(cid).open("a") as f:
        f.write('{"role": "assi')  # выключили посреди записи
    assert [m["text"] for m in chats.messages(cid)] == ["привет"]
    assert chats.listing()[0]["title"] == "привет"


def test_chat_reply_is_never_spoken():
    """Беда: сообщение с телефона проговаривалось вслух. Мозг чата не шлёт событие «say», которое слушает голос."""
    import asyncio

    from justday import events
    from justday.brain import Brain

    got, emitted = [], []

    async def on_text(t):
        got.append(t)

    async def nope(*a):
        return True

    b = Brain({}, on_text=on_text, approver=nope, asker=nope, persist=False, chat=True)
    orig = events.emit
    events.emit = lambda kind, **kw: emitted.append(kind)
    try:
        asyncio.run(b._speak("Вот **список**"))
    finally:
        events.emit = orig
    assert got == ["Вот **список**"] and "say" not in emitted


def test_chat_model_overrides_voice_model_only_when_chosen():
    """Хотел спросить в чате посильнее, а мозг чата всегда шёл на модели голоса (Р2-42)."""
    cfg = {"brain": {"model": "haiku", "effort": "low"}}
    assert chats.cfg_with_model(cfg, "") is cfg
    assert chats.cfg_with_model(cfg, "gpt-5")["brain"]["model"] == "haiku"
    got = chats.cfg_with_model(cfg, "opus")
    assert got["brain"] == {"model": "opus", "effort": "low"} and cfg["brain"]["model"] == "haiku"


def test_write_to_chat_by_voice_lands_in_the_open_chat(monkeypatch, tmp_path):
    """«Запиши в чат: …» голосом уходило мозгу, и тот отвечал вслух вместо того, чтобы записать (Р2-42, п.16)."""
    from justday import events, fastpath
    from justday.daemon import Daemon

    assert fastpath.to_chat("Джарвис, запиши в чат: купить Молоко!") == "купить Молоко!"
    assert fastpath.to_chat("запиши в чат") is None
    assert fastpath.to_chat("запиши в планы купить молоко") is None

    state = {}
    monkeypatch.setattr(events, "load_state", lambda: dict(state))
    monkeypatch.setattr(events, "save_state", lambda **kw: state.update(kw))
    d = Daemon.__new__(Daemon)
    d.publish = lambda **kw: None
    d._chat_last = ""
    first = d.chat_note("без окна")            # окна не открывали — постоянный чат «Джарвис»
    assert chats.meta(first)["title"] == "Джарвис" and d.chat_note("ещё") == first
    opened = chats.create("Работа")
    d._chat_last = opened
    d.chat_note("в открытый")
    assert [m["text"] for m in chats.messages(opened)] == ["в открытый"]


def test_dictation_in_the_chat_window_fills_the_field_and_says_nothing(monkeypatch):
    """Кнопка микрофона в чате: сказанное должно лечь в поле ввода, а не уйти мозгу и не прозвучать (Р2-42).

    Сразу в мозг — значит отправить то, что Whisper расслышал криво; вслух — то, ради чего чат и
    отделён от голоса."""
    import asyncio
    import types

    import numpy as np

    from justday import audio, events
    from justday.daemon import Daemon

    monkeypatch.setattr(events, "emit", lambda *a, **kw: None)
    d = Daemon.__new__(Daemon)
    d._state, d._dictating, d._listen_cancel, d._discard_recording = "idle", False, None, False
    d.publish = lambda **kw: None
    d._warm_models = lambda value: None
    d.music = types.SimpleNamespace(alive=False)
    d.brain = types.SimpleNamespace(busy=False, ask=None)
    d.mic_on = lambda: True
    d.stop_speaking = lambda: None
    d.mic = types.SimpleNamespace(start=lambda: None)
    d.stt = types.SimpleNamespace(transcribe=lambda pcm: " привет из чата ")

    async def quiet(*a, **kw):
        return None

    async def record(cancel, prefill=None, speculate=None):
        return np.zeros(audio.RATE, dtype=np.int16)

    async def never(*a, **kw):
        raise AssertionError("диктовка в чат заговорила или ушла мозгу")

    d.earcon, d.say, d.run_turn = quiet, never, never
    d.recorder = types.SimpleNamespace(record=record)
    got = asyncio.run(d._cmd_chat_dictate({}, None))
    assert got == {"ok": True, "dictated": "привет из чата"}
    assert d.state == "idle" and not d._dictating, "после диктовки микрофон остался занят"


def test_a_screenshot_pasted_into_the_chat_reaches_the_brain_as_a_file(monkeypatch):
    """Беда: Ctrl+V со снимком экрана в окне чата не вставлял ничего — QML видит в буфере только текст.
    Демон кладёт картинку в файл, и в сообщение уходит путь, который мозг откроет через Read."""
    import subprocess
    import types

    png = b"\x89PNG\r\n\x1a\nimage"

    def run(cmd, **kw):
        if "--list-types" in cmd:
            return types.SimpleNamespace(stdout="text/plain\nimage/png\n")
        assert cmd[-1] == "image/png"
        return types.SimpleNamespace(stdout=png)

    monkeypatch.setattr(chats.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(subprocess, "run", run)
    path = chats.paste_image()
    assert path.endswith(".png") and Path(path).read_bytes() == png
    assert chats.paste_image() == path          # вставили второй раз — та же картинка, без копии

    monkeypatch.setattr(subprocess, "run", lambda cmd, **kw: types.SimpleNamespace(stdout="text/plain\n"))
    assert chats.paste_image() == ""            # в буфере текст: окно вставит его само
