"""Человек хотел видеть лестницу целиком: кто сейчас думает, кто подхватит и почему ступень не сработает."""
from justday import config, ladders


def test_cards_show_missing_key_and_spare_voice_keys(monkeypatch):
    cfg = config.load()
    cfg["tts"]["engine"] = "elevenlabs"
    monkeypatch.setattr(config, "secrets", lambda name: ["a", "b"])
    voice = next(c for c in ladders.cards(cfg) if c["id"] == "voice")
    assert [r["name"] for r in voice["rungs"]][:2] == ["ElevenLabs", "ElevenLabs"]
    assert voice["rungs"][0]["now"] and not voice["rungs"][1]["now"]
    brain = next(c for c in ladders.cards(cfg) if c["id"] == "brain")
    assert brain["rungs"][0]["name"]
