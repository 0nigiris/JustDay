"""Игра Steam в доке называлась steam_app_3393110 и носила чужой значок (Р2-43)."""
from justday import desktop, dock


def test_steam_game_window_gets_the_games_name_and_key(monkeypatch):
    monkeypatch.setattr(desktop, "list_apps", lambda: [])
    monkeypatch.setattr(desktop, "list_games",
                        lambda: [{"source": "steam", "id": "3393110", "name": "Моя Игра"}])
    monkeypatch.setattr(dock, "pinned", lambda: [])
    monkeypatch.setattr(dock, "_save_catalog", lambda out: None)
    monkeypatch.setattr(dock, "find_icon", lambda name, theme="": "")
    got = dock.catalog()["match"]["steam_app_3393110"]
    assert got["name"] == "Моя Игра" and got["key"] == "game:3393110"
    assert got["icon"] == "applications-games" or got["icon"].endswith("applications-games")
