"""Горячий путь голоса: хайку отвечает сразу, а сильную зовёт сама."""
import asyncio

from justday import daemon, dispatch


class Fake:
    def __init__(self):
        self.cfg = {"brain": {"provider": "claude", "home_provider": "claude", "model": "haiku",
                              "light_model": "haiku", "strong_model": "sonnet", "huge_model": "opus", "effort": "low"}}
        self.reconnects = 0
        self.brain = self
        self.published = []

    async def reconnect(self):
        self.reconnects += 1

    def publish(self, **kw):
        self.published.append(kw)


def test_simple_request_never_asks_the_judge(monkeypatch):
    """Судья съедал секунду и карту перед каждым «который час»: простая просьба его не зовёт."""
    def boom(*a, **k):
        raise AssertionError("судья на горячем пути")
    monkeypatch.setattr(dispatch, "level_for", boom)
    f = Fake()
    asyncio.run(daemon.Daemon._pick_model(f, "который час"))
    assert f.cfg["brain"]["model"] == "haiku" and f.reconnects == 0


def test_light_model_calls_strong_by_itself():
    """«Сделай сайт» → хайку отвечает «НУЖНА: opus», демон пересаживается на опус."""
    f = Fake()
    assert dispatch.hands_up("НУЖНА: opus") == "opus"
    assert asyncio.run(daemon.Daemon._lift(f, "opus")) is True
    assert f.cfg["brain"]["model"] == "opus" and f.cfg["brain"]["effort"] == "high"


def test_garbage_name_does_not_reach_config():
    """Слово из ответа модели не должно подставлять в конфиг что попало."""
    f = Fake()
    assert asyncio.run(daemon.Daemon._lift(f, "../../etc")) is False
    assert f.cfg["brain"]["model"] == "haiku"


def test_hand_up_is_not_spoken():
    """Просьба к демону не должна прозвучать вслух."""
    from justday import brain
    spoken = []

    async def on_text(t):
        spoken.append(t)
    b = brain.Brain.__new__(brain.Brain)
    b.cancelled, b.on_text, b._spoke_in_turn = False, on_text, False
    asyncio.run(b._speak("НУЖНА: sonnet"))
    assert spoken == []


def test_each_model_gets_only_its_own_role():
    """Хайку должна знать про «НУЖНА», опус — про большую работу, и чужого в системной части нет."""
    h, s, o = (dispatch.role_for(m) for m in ("claude-haiku-4-5-20251001", "sonnet", "opus"))
    assert "роль: быстрая" in h and "роль: быстрая" not in s + o
    assert "роль: рабочая" in s and "роль: рабочая" not in h + o
    assert "роль: для большой" in o and "роль: для большой" not in h + s
    assert "НУЖНА: opus" in h
    assert dispatch.role_for("qwen3:8b") == "" and dispatch.role_for("") == ""
