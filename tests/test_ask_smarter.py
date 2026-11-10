"""«Перейди на более умную модель» не переключало ничего: фразу получала хайку, а смену модели
через настройки держит система разрешений (10 нояб., «в любом случае… реально мог переключить»)."""
import asyncio

from justday import dispatch
from justday.ladder import LadderMixin


class _Brain:
    def __init__(self):
        self.reconnects = 0

    async def reconnect(self):
        self.reconnects += 1


class _D(LadderMixin):
    def __init__(self, model="haiku", auto=True):
        self.cfg = {"brain": {"provider": "claude", "home_provider": "claude", "model": model,
                              "light_model": "haiku", "strong_model": "sonnet", "huge_model": "opus",
                              "auto_model": auto, "auto_effort": True, "ask_judge": "never"}}
        self.brain = _Brain()
        self.published = []

    def publish(self, **kw):
        self.published.append(kw)


def test_his_words_are_caught_before_the_model_and_nothing_else_is():
    assert dispatch.asked_model("Перейди на более умную модель") == ("up", True)
    assert dispatch.asked_model("Джарвис, переключись на опус") == (dispatch.BIG, True)
    assert dispatch.asked_model("перейди на сонет и разбери ошибку") == (dispatch.STRONG, False)
    assert dispatch.asked_model("вернись на обычную модель") == (dispatch.LIGHT, True)
    for other in ("включи умную розетку", "опус лучше пишет?", "открой дискорд", "умный дом"):
        assert dispatch.asked_model(other) is None, other


def test_smarter_climbs_one_step_and_holds_even_with_auto_model_off():
    d = _D(auto=False)
    assert "Sonnet" in asyncio.run(d.ask_model("up"))
    assert d.cfg["brain"]["model"] == "sonnet"
    assert "Opus" in asyncio.run(d.ask_model("up"))
    # Следующая просьба не скатывается обратно на хайку, хотя лестница выключена.
    asyncio.run(d._pick_model("а теперь открой браузер"))
    assert d.cfg["brain"]["model"] == "opus"
    assert "Haiku" in asyncio.run(d.ask_model(dispatch.LIGHT))
    assert d.cfg["brain"]["model"] == "haiku"


def test_work_mode_never_drops_to_haiku_and_sends_big_work_to_opus(monkeypatch):
    """«Роутер, настроенный именно под работу»: в работе хайку и была бедой — отвечала не тем."""
    from justday import config
    monkeypatch.setattr(config, "set_value", lambda *a: None)
    assert dispatch.asked_work("Джарвис, включи рабочий режим") is True
    assert dispatch.asked_work("выключи рабочий режим") is False
    assert dispatch.asked_work("что такое рабочий режим") is None
    d = _D()
    asyncio.run(d.work_mode(True))
    asyncio.run(d._pick_model("открой браузер"))
    assert d.cfg["brain"]["model"] == "sonnet"
    asyncio.run(d._pick_model("спроектируй с нуля сервис уведомлений"))
    assert d.cfg["brain"]["model"] == "opus"
    asyncio.run(d.ask_model(dispatch.LIGHT))          # его слово сильнее режима
    asyncio.run(d._pick_model("открой браузер"))
    assert d.cfg["brain"]["model"] == "haiku"
