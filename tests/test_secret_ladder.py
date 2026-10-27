"""Свой ключ ElevenLabs кончился — голос не должен замолчать, если у человека есть запасной (например, ключ друга)."""
from justday import config


def test_spare_keys_come_after_main_and_skip_empty(monkeypatch):
    vals = {"ELEVENLABS_API_KEY": "mine", "ELEVENLABS_API_KEY_2": "friend", "ELEVENLABS_API_KEY_3": "mine"}
    monkeypatch.setattr(config, "secret", lambda n: vals.get(n, ""))
    assert config.secrets("ELEVENLABS_API_KEY") == ["mine", "friend"]
