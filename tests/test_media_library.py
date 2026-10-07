"""Медиатека в плеере: «Удалить» не должно трогать ничего вне папки музыки и не должно быть `rm`."""

from justday import media


def test_удалять_можно_только_из_папки_музыки(tmp_path, monkeypatch):
    music = tmp_path / "YouTube"
    music.mkdir()
    чужой = tmp_path / "паспорт.pdf"
    чужой.write_text("x")
    monkeypatch.setattr(media, "music_dir", lambda: music)
    assert media.trash_track(str(чужой)) is False
    assert media.trash_track(str(music / "нет.mp3")) is False
    assert чужой.exists()


def test_медиатека_берёт_название_из_индекса_и_сортируется(tmp_path, monkeypatch):
    a, b = tmp_path / "a.mp3", tmp_path / "b.mp3"
    a.write_text("1")
    b.write_text("22")
    monkeypatch.setattr(media, "library", lambda *x, **k: [
        {"file": str(b), "title": "Яблоко", "artist": "Кино"}, {"file": str(a), "title": "Арбуз", "artist": ""}])
    assert [r["title"] for r in media.library_view("title")] == ["Арбуз", "Яблоко"]
    assert media.library_view("artist")[0]["artist"] == "Кино"
    assert media.library_view()[0]["size"] in (1, 2)
