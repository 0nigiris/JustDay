"""Страница «Что где показывать»: погода и события выключались только целиком, не по месту."""
from justday import config


def test_weather_and_events_can_be_hidden_per_place_and_default_to_shown(tmp_path, monkeypatch):
    cfg = tmp_path / "config.toml"
    cfg.write_text("[island]\nshow_weather = false\n", encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_FILE", cfg)
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)

    # Старый общий выключатель остаётся в силе, новые разрезы по умолчанию включены.
    island = config.load()["island"]
    assert island["show_weather"] is False
    assert all(island[k] is True for k in ("weather_peek", "weather_expanded", "events_peek", "events_expanded"))

    # Страница включает общий обратно и прячет одну клетку — файл это переживает.
    config.set_value("island", "show_weather", True)
    config.set_value("island", "weather_expanded", False)
    island = config.load()["island"]
    assert island["show_weather"] is True and island["weather_expanded"] is False and island["weather_peek"] is True
