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



def test_brain_woke_up_without_his_profile_and_memory(tmp_path, monkeypatch):
    """Мозг запускали из папки пакета (src/justday/brain): Claude Code не видел профиль CLAUDE.md и
    искал память под другим ключом — Джарвис просыпался, ничего не зная о человеке. Рабочая папка —
    данные (~/.local/share/justday/brain), PERSONA и settings.json — из пакета."""
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")

    async def nobody(*a):
        return False

    opts = brain_mod.Brain(config.load(), on_text=nobody, approver=nobody, asker=nobody)._options(None)
    assert opts.cwd == str(config.DATA_DIR / "brain")
    assert (brain_mod.BRAIN_PKG_DIR / "PERSONA.md").exists()
    assert (brain_mod.BRAIN_PKG_DIR / "settings.json").exists()

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


def test_the_persona_cost_nine_thousand_tokens_every_turn(tmp_path, monkeypatch):
    """PERSONA была 18,8 тыс. знаков (≈9 тыс. токенов в каждом ходе), а для «который час» нужны имя,
    характер, правила озвучки и безопасность. Подробные рецепты уехали в навык assistant (Р-23)."""
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")

    async def nobody(*a):
        return False

    cfg = config.load()
    cfg["brain"]["model"] = "haiku"
    prompt = brain_mod.Brain(cfg, on_text=nobody, approver=nobody, asker=nobody)._options(None).system_prompt["append"]
    assert len(prompt) < 10000
    for rule in ("confirm-message", "kwin_wayland", "gio trash", "НУЖНА", "justday job start", "assistant"):
        assert rule in prompt, rule
    skill = config.REPO_DIR / "plugin" / "skills" / "assistant" / "SKILL.md"
    assert "justday contacts find" in skill.read_text(encoding="utf-8")


def test_every_turn_after_a_pause_paid_for_the_whole_long_history(tmp_path, monkeypatch):
    """Голосовая сессия сжималась только на 200 тыс.: после пятиминутной паузы ход заново платил
    запись истории — медиана 124 тыс. токенов на ход (Р-25)."""
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")

    async def nobody(*a):
        return False

    env = brain_mod.Brain(config.load(), on_text=nobody, approver=nobody, asker=nobody)._options(None).env
    assert int(env["CLAUDE_CODE_AUTO_COMPACT_WINDOW"]) <= 80000
