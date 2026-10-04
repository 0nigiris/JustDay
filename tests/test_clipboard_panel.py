"""Clipboard pin / edit / screenshot-boilerplate filter."""
from __future__ import annotations

from pathlib import Path

import pytest

from justday import clipboard


@pytest.fixture(autouse=True)
def _iso(tmp_path, monkeypatch):
    monkeypatch.setattr(clipboard, "STORE", tmp_path / "clipboard.jsonl")
    monkeypatch.setattr(clipboard, "BLOBS", tmp_path / "clipboard")
    monkeypatch.setattr(clipboard, "PAUSE_FLAG", tmp_path / "clipboard.paused")
    monkeypatch.setattr(clipboard, "SKIPPED", tmp_path / "clipboard-skipped.json")
    monkeypatch.setattr(clipboard.config, "STATE_DIR", tmp_path)


def test_pin_floats_above_newer_unpinned():
    clipboard.store("alpha")
    clipboard.store("beta")
    a = clipboard.items()[1]  # older
    clipboard.pin(a["id"], True)
    got = clipboard.items()
    assert got[0]["pinned"] is True
    assert got[0]["preview"].startswith("alpha")
    assert got[1]["preview"].startswith("beta")


def test_edit_rewrites_text_and_id():
    clipboard.store("old text")
    iid = clipboard.items()[0]["id"]
    got = clipboard.edit(iid, "new text here")
    assert got["ok"]
    items = clipboard.items()
    assert items[0]["preview"] == "new text here"
    assert items[0]["id"] == got["id"]


def test_screenshot_boilerplate_not_stored():
    assert clipboard.store("Screenshot copied to clipboard").get("ok") is False
    assert clipboard.store("Снимок скопирован в буфер обмена").get("ok") is False
    assert clipboard.items() == []


def test_image_preview_mentions_shot_not_screenshot_copied(tmp_path):
    png = b"\x89PNG\r\n\x1a\n" + b"\0" * 200
    got = clipboard.store(image=png)
    assert got["ok"]
    item = clipboard.items()[0]
    assert item["kind"] == "image"
    assert "снимок" in item["preview"].lower() or "КБ" in item["preview"]
    assert item["file"]
    assert Path(item["file"]).is_file()


def test_put_back_uses_paste_chord_for_multiline(state_dir, monkeypatch):
    """Long / multiline clipboard entries paste via Ctrl+V, not per-character typing."""
    from justday import glyphs

    clipboard.store("line1\nline2\nline3")
    iid = clipboard.items()[0]["id"]
    monkeypatch.setattr(glyphs, "to_clipboard", lambda text: True)
    monkeypatch.setattr(glyphs, "type_out", lambda text: (_ for _ in ()).throw(AssertionError("must not type")))
    monkeypatch.setattr(glyphs, "paste_chord", lambda: (True, "test-ctrl-v"))
    monkeypatch.setattr(glyphs, "PASTE_DELAY", 0)
    got = clipboard.put_back(iid, paste=True)
    assert got["ok"] and got.get("pasted") is True


def test_russian_text_from_the_clipboard_panel_was_pasted_not_typed(state_dir, monkeypatch):
    """`ydotool type` не умеет кириллицу и отвечает «успех», ничего не вставив: короткая русская запись
    из буфера «вставлялась» в пустоту. Вставляем Ctrl+V из буфера."""
    from justday import glyphs

    clipboard.store("привет")
    iid = clipboard.items()[0]["id"]
    monkeypatch.setattr(glyphs, "to_clipboard", lambda text: True)
    monkeypatch.setattr(glyphs, "type_out", lambda text: (_ for _ in ()).throw(AssertionError("must not type")))
    monkeypatch.setattr(glyphs, "paste_chord", lambda: (True, "test-ctrl-v"))
    got = clipboard.put_back(iid, paste=True, ready=lambda: True)
    assert got["pasted"] is True and not got["typed"]
