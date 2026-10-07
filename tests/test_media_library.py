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


def test_ссылка_из_микса_отличается_от_плейлиста_и_одной_песни():
    """Из микса вставляли ссылку «хочу одну песню» — и запускался бесконечный список."""
    pf = media.parse_youtube
    kinds = {
        "https://www.youtube.com/watch?v=abc123&t=42s": ("abc123", "", "track"),
        "https://youtu.be/abc123?si=xx": ("abc123", "", "track"),
        "https://www.youtube.com/shorts/abc123": ("abc123", "", "track"),
        "https://music.youtube.com/watch?v=abc123": ("abc123", "", "track"),
        "https://www.youtube.com/watch?v=abc123&list=RDabc123&start_radio=1": ("abc123", "RDabc123", "track_in_mix"),
        "https://www.youtube.com/playlist?list=PLxyz": ("", "PLxyz", "playlist"),
        "https://www.youtube.com/watch?v=abc123&list=PLxyz": ("abc123", "PLxyz", "track_in_playlist"),
    }
    for url, (v, lst, kind) in kinds.items():
        assert pf(url) == {"video": v, "list": lst, "kind": kind}, url
    assert pf("https://example.com/watch?v=1") is None
