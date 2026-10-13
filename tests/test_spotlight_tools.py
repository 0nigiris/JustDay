"""Свои окна JustDay в поиске: беда — «звук» и «чат» в Spotlight не находили ничего своего,
и до микшера надо было идти через меню островка (Р2-48, п.7d)."""
from justday import desktop, filesearch, launcher


def test_sound_and_chat_are_found_by_name(monkeypatch):
    monkeypatch.setattr(desktop, "list_apps", lambda: [{"id": "org.kde.plasma-pa", "name": "Audio Volume",
                                                        "name_ru": "Громкость", "keywords": "sound;звук"}])
    monkeypatch.setattr(desktop, "list_games", lambda: [])
    monkeypatch.setattr(desktop, "windows", lambda *a: [])
    monkeypatch.setattr(filesearch, "search", lambda *a, **k: [])
    monkeypatch.setattr(launcher, "recents", lambda: [])

    assert launcher.items("звук")[0] == {"kind": "tool", "id": "mixer", "name": "Звук",
                                         "icon": "audio-volume-high", "sub": "JustDay"}
    assert launcher.items("микшер")[0]["id"] == "mixer"
    assert launcher.items("чат")[0]["id"] == "chat"
    assert all(r["kind"] != "tool" for r in launcher.items(""))   # пустой поиск — только недавнее
