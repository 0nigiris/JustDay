"""config.set_value must find `[section]  # comment` headers (no duplicate tables)."""
from __future__ import annotations

from justday import config


def test_set_value_respects_commented_section_header(tmp_path, monkeypatch):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        "[island]                    # Dynamic Island, applied live\n"
        "show_notifications = true   # mirror\n"
        "screen = \"DP-2\"\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "CONFIG_FILE", cfg)
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)

    config.set_value("island", "show_notifications", False)
    text = cfg.read_text(encoding="utf-8")
    assert text.count("[island]") == 1
    assert "show_notifications = false" in text

    config.set_value("island", "notification_screen", "secondary")
    text = cfg.read_text(encoding="utf-8")
    assert text.count("[island]") == 1
    assert 'notification_screen = "secondary"' in text


def test_heal_duplicate_island_sections(tmp_path, monkeypatch):
    cfg = tmp_path / "config.toml"
    cfg.write_text(
        "[island]  # first\n"
        "show_notifications = true\n"
        "screen = \"DP-2\"\n"
        "\n"
        "[dock]\n"
        "enabled = true\n"
        "\n"
        "[island]\n"
        "show_notifications = false\n",
        encoding="utf-8",
    )
    monkeypatch.setattr(config, "CONFIG_FILE", cfg)
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)

    assert config.heal_duplicate_tables() is True
    loaded = config.load()
    assert loaded["island"]["show_notifications"] is False  # later duplicate wins
    assert loaded["island"]["screen"] == "DP-2"
    assert cfg.read_text(encoding="utf-8").count("[island]") == 1
