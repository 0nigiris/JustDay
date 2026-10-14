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


def test_spotlight_asked_kwin_for_windows_on_every_letter(monkeypatch):
    """Каждый запрос окон — скрипт, загруженный в KWin, и чтение журнала: 0,13 с и строка в системном
    журнале на каждую букву, хотя пока человек печатает, окна не меняются."""
    asked = []
    monkeypatch.setattr(desktop, "list_apps", lambda: [])
    monkeypatch.setattr(desktop, "list_games", lambda: [])
    monkeypatch.setattr(desktop, "windows", lambda *a: asked.append(a) or [{"app": "helium", "title": "Steam — Helium"}])
    monkeypatch.setattr(filesearch, "search", lambda *a, **k: [])
    monkeypatch.setattr(launcher, "recents", lambda: [])
    monkeypatch.setattr(launcher, "_WINDOWS_SEEN", (-1e9, []))

    for q in ("s", "st", "ste", "steam"):
        found = launcher.items(q)
    assert len(asked) == 1
    assert found[0]["kind"] == "window"
