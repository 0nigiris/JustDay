"""Лимит Claude не читается вслух, а включает запасного поставщика (Р-6 ревизии)."""

import asyncio

import pytest
from claude_agent_sdk import AssistantMessage, ResultMessage, TextBlock

from justday import brain as brain_mod
from justday import config, daemon, events, fallback

LIMIT = "You've hit your session limit · resets 2:30am"


def _result(is_error: bool, text: str = "") -> ResultMessage:
    return ResultMessage(subtype="error_during_execution" if is_error else "success", duration_ms=1,
                         duration_api_ms=1, is_error=is_error, num_turns=1, session_id="s", result=text)


class FakeClient:
    """SDK-клиент, который отвечает заранее заданными сообщениями."""

    def __init__(self, brain, messages):
        self.brain, self.messages = brain, messages

    async def query(self, _text):
        for m in self.messages:
            await self.brain._handle(m)


@pytest.fixture(autouse=True)
def quiet(monkeypatch):
    monkeypatch.setattr(events, "emit", lambda *a, **k: None)
    monkeypatch.setattr(events, "save_state", lambda **k: None)


def _brain(messages):
    spoken: list[str] = []

    async def on_text(text):
        spoken.append(text)

    async def nobody(*a):
        return False

    b = brain_mod.Brain(config.load(), on_text=on_text, approver=nobody, asker=nobody)
    b.client = FakeClient(b, messages)
    return b, spoken


def test_the_session_limit_was_read_aloud_as_an_answer():
    """«You've hit your session limit» дважды прозвучало голосом, а ask вернул его как ответ."""
    b, spoken = _brain([AssistantMessage(content=[TextBlock(LIMIT)], model="m", error="rate_limit"),
                        _result(True, LIMIT)])
    with pytest.raises(brain_mod.BrainError, match="rate_limit"):
        asyncio.run(b.ask("привет"))
    assert spoken == []


def test_a_normal_answer_is_still_spoken():
    b, spoken = _brain([AssistantMessage(content=[TextBlock("Привет!")], model="m"), _result(False)])
    assert asyncio.run(b.ask("привет")) == "Привет!"
    assert spoken == ["Привет!"]


def test_the_limit_moved_the_brain_to_the_next_provider(tmp_path, monkeypatch):
    """provider_fallback — ноль раз за месяц журнала: лестница не видела лимита. Живой Daemon."""
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    d = daemon.Daemon()
    asked: list[str] = []

    async def ask(text, source="voice"):
        asked.append(d.cfg["brain"]["provider"])
        if len(asked) == 1:
            raise brain_mod.BrainError("rate_limit: " + LIMIT)
        return "ответ от запасного"

    async def nothing(*a, **k):
        return None

    monkeypatch.setattr(d.brain, "ask", ask)
    monkeypatch.setattr(d.brain, "reconnect", nothing)
    monkeypatch.setattr(d, "earcon", nothing)
    monkeypatch.setattr(d, "_settle_model", nothing)
    monkeypatch.setattr(d, "notify", lambda *a, **k: None)
    monkeypatch.setattr(fallback, "next_provider", lambda cfg: ("openrouter", "qwen/qwen3-coder"))

    async def go():
        return await d.run_turn("сделай сайт", source="cli")

    assert asyncio.run(go()) == "ответ от запасного"
    assert asked == ["claude", "openrouter"]
