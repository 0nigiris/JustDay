"""Настройки одни на весь демон: после щелчка в островке их видят и мозг, и голос (Р-5, Р-18)."""

import asyncio

import pytest

from justday import config, daemon, events, island


@pytest.fixture
def live(tmp_path, monkeypatch):
    """Настоящий Daemon (не подделка) на своём config.toml; события и снимок для островка — мимо."""
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    monkeypatch.setattr(events, "emit", lambda *a, **k: None)
    monkeypatch.setattr(island, "settings_snapshot", lambda cfg: {})
    config.CONFIG_FILE.write_text('[brain]\nprovider = "claude"\nmodel = "sonnet"\nauto_model = true\n'
                                  'ask_judge = "never"\n')
    d = daemon.Daemon()

    async def reconnect():
        pass

    monkeypatch.setattr(d.brain, "reconnect", reconnect)
    return d


def _click_in_settings(d, text: str) -> list[str]:
    config.CONFIG_FILE.write_text(config.CONFIG_FILE.read_text() + text)

    async def go():
        return d.reload_settings()

    return asyncio.run(go())


def test_model_choice_kept_working_after_a_click_in_settings(live):
    """По журналу: до reload применились 70 смен модели из 70, после — 0 из 16. Демон писал выбор
    в новый словарь настроек, а мозг читал старый."""
    _click_in_settings(live, '[user]\nname = "Вася"\n')
    asyncio.run(live._pick_model("привет"))
    assert live.brain.cfg["brain"]["model"] == "haiku"
    assert live.brain.cfg["user"]["name"] == "Вася"
    assert live.tts.cfg is live.cfg["tts"] and live.stt.cfg is live.cfg["stt"]


def test_a_volume_click_did_not_pull_the_brain_back_from_the_fallback(live):
    """Лимит кончился, мозг ушёл на запасного — щелчок по другой настройке не возвращает его туда,
    где лимита нет; а смену модели в самом файле перезагрузка берёт."""
    live.cfg["brain"].update(provider="openrouter", model="qwen/qwen3-coder")
    _click_in_settings(live, '[tts]\nspeed = 1.1\n')
    assert live.brain.cfg["brain"]["provider"] == "openrouter"
    config.CONFIG_FILE.write_text(config.CONFIG_FILE.read_text().replace('model = "sonnet"', 'model = "opus"'))
    _click_in_settings(live, "")
    assert live.brain.cfg["brain"]["model"] == "opus"


def test_without_a_config_file_the_defaults_stayed_defaults(tmp_path, monkeypatch):
    """Без config.toml load() отдавал сами DEFAULTS: выбор модели правил умолчания процесса."""
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "нет.toml")
    was = config.DEFAULTS["brain"]["model"]
    cfg = config.load()
    cfg["brain"]["model"] = "что-то своё"
    assert config.DEFAULTS["brain"]["model"] == was
    assert config.load() == {**config.DEFAULTS}
