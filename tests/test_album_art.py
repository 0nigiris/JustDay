"""Обложка песни — кадр из клипа с лицом на белом фоне; настоящая квадратная обложка должна её заменять."""
import io
import json

from justday import media


class _R(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def _fake(hit):
    def opener(url, timeout=0):
        if "itunes.apple.com/search" in url:
            return _R(json.dumps({"results": [hit]}).encode())
        return _R(b"A" * 5000)
    return opener


def test_clip_frame_is_replaced_by_album_art(tmp_path, monkeypatch):
    jpg = tmp_path / "x.jpg"
    jpg.write_bytes(b"frame")
    hit = {"trackName": "BRAIN", "artistName": "Kanaria", "artworkUrl100": "https://a/100x100bb.jpg"}
    monkeypatch.setattr("urllib.request.urlopen", _fake(hit))
    media.album_art(jpg, "BRAIN", "Kanaria")
    assert jpg.read_bytes() == b"A" * 5000


def test_other_artists_art_is_not_taken(tmp_path, monkeypatch):
    jpg = tmp_path / "x.jpg"
    jpg.write_bytes(b"frame")
    hit = {"trackName": "BRAIN", "artistName": "Somebody Else", "artworkUrl100": "https://a/100x100bb.jpg"}
    monkeypatch.setattr("urllib.request.urlopen", _fake(hit))
    media.album_art(jpg, "BRAIN", "Kanaria")
    assert jpg.read_bytes() == b"frame"
