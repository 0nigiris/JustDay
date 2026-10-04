"""Голосовой мозг не платит за чужую среду и не переподключается дважды за ход (Р-20, Р-24)."""

import asyncio

from justday import brain as brain_mod
from justday import config, daemon, events


def test_the_voice_brain_carried_the_developers_skills_and_hooks(tmp_path, monkeypatch):
    """С источником "user" в каждый ход ехали ~/.claude/CLAUDE.md, 43 навыка и хуки разработки."""
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")

    async def nobody(*a):
        return False

    opts = brain_mod.Brain(config.load(), on_text=nobody, approver=nobody, asker=nobody)._options(None)
    assert "user" not in opts.setting_sources
    assert opts.settings.endswith("brain/settings.json")


def test_each_turn_reconnected_the_brain_twice(tmp_path, monkeypatch):
    """sonnet в конфиге + auto_model: ход уходил на haiku, после ответа возвращался на sonnet —
    два `claude --resume` и холодный кэш промпта на каждом ходу (513 подключений на 303 запуска)."""
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    config.CONFIG_FILE.write_text('[brain]\nmodel = "sonnet"\nauto_model = true\nask_judge = "never"\n')
    monkeypatch.setattr(events, "emit", lambda *a, **k: None)
    d = daemon.Daemon()
    reconnects = []

    async def reconnect():
        reconnects.append(d.cfg["brain"]["model"])

    async def ask(text, source="voice"):
        return "ок"

    async def nothing(*a, **k):
        return None

    monkeypatch.setattr(d.brain, "reconnect", reconnect)
    monkeypatch.setattr(d.brain, "ask", ask)
    monkeypatch.setattr(d, "earcon", nothing)

    async def three_turns():
        for text in ("который час", "открой дискорд", "сделай погромче"):
            await d.run_turn(text, source="cli")
            await asyncio.sleep(0)

    asyncio.run(three_turns())
    assert reconnects == ["haiku"]
