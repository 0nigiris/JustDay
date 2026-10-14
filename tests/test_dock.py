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


def test_steam_games_showed_a_generic_joystick_instead_of_their_icon(monkeypatch, tmp_path):
    """Steam кладёт значок игры в hicolor, а док искал его в выбранной теме (MacTahoe) — у всех игр
    в доке и в поиске был один и тот же джойстик (жалоба Hikisey, 5 окт)."""
    for size in ("32x32", "256x256"):
        d = tmp_path / ".local/share/icons/hicolor" / size / "apps"
        d.mkdir(parents=True)
        (d / "steam_icon_570.png").write_bytes(b"png")
    monkeypatch.setattr(desktop, "HOME", tmp_path)
    assert desktop._steam_icon("570").endswith("256x256/apps/steam_icon_570.png")
    assert desktop._steam_icon("999") == "applications-games"
