"""Чат: беда — id из окна мог вывести запись за папку чатов, а оборванная строка — потерять весь чат."""
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
