"""Lightweight home file index for Spotlight-like menu search."""
from __future__ import annotations

import pytest

from justday import filesearch


@pytest.fixture
def index_home(monkeypatch, tmp_path):
    docs = tmp_path / "Documents"
    docs.mkdir()
    (docs / "report-q3.pdf").write_text("x", encoding="utf-8")
    (docs / "notes.txt").write_text("hello", encoding="utf-8")
    dl = tmp_path / "Downloads"
    dl.mkdir()
    (dl / "photo.png").write_bytes(b"\x89PNG\r\n")
    skip = docs / "node_modules" / "pkg"
    skip.mkdir(parents=True)
    (skip / "secret.js").write_text("no", encoding="utf-8")

    monkeypatch.setattr(filesearch, "_home", lambda: tmp_path)
    monkeypatch.setattr(filesearch, "INDEX_FILE", tmp_path / "file-index.json")
    monkeypatch.setattr(filesearch.config, "STATE_DIR", tmp_path)
    filesearch._cache = None
    filesearch._cache_at = 0.0
    monkeypatch.setattr(filesearch.desktop, "recent", lambda **k: {"files": [], "apps": [], "claude_projects": []})
    monkeypatch.setattr(filesearch, "_plocate", lambda *a, **k: [])
    monkeypatch.setattr(filesearch, "_fd", lambda *a, **k: [])
    return tmp_path


def test_rebuild_indexes_common_dirs(index_home):
    got = filesearch.rebuild()
    names = {i["name"] for i in got["items"]}
    assert "notes.txt" in names
    assert "report-q3.pdf" in names
    assert "photo.png" in names
    assert "secret.js" not in names  # node_modules skipped


def test_search_by_name(index_home):
    filesearch.rebuild()
    hits = filesearch.search("notes")
    assert hits and hits[0]["name"] == "notes.txt"
    assert hits[0]["kind"] == "file"


def test_search_finds_pdf(index_home):
    filesearch.rebuild()
    hits = filesearch.search("report")
    assert any(h["name"] == "report-q3.pdf" for h in hits)


def test_open_path_missing(index_home):
    got = filesearch.open_path(str(index_home / "nope.txt"))
    assert got["ok"] is False
