"""Эмодзи не вставлялся сам: ydotool type печатает только латиницу, а с эмодзи молча отвечает «успех»."""
from justday import glyphs


def test_emoji_was_pasted_from_the_clipboard_not_typed_key_by_key(monkeypatch):
    calls = []
    monkeypatch.setattr(glyphs, "remember", lambda ch: None)
    monkeypatch.setattr(glyphs, "to_clipboard", lambda ch: True)
    monkeypatch.setattr(glyphs, "PASTE_DELAY", 0)
    monkeypatch.setattr(glyphs, "paste_chord", lambda: (calls.append("chord") or True, "ydotool-ctrl-v"))
    monkeypatch.setattr(glyphs, "type_out", lambda ch: (calls.append("type") or True, "ydotool"))
    got = glyphs.use("😀")
    assert calls == ["chord"] and got["typed"] and got["how"] == "ydotool-ctrl-v"


def test_plain_ascii_still_typed_directly(monkeypatch):
    calls = []
    monkeypatch.setattr(glyphs, "remember", lambda ch: None)
    monkeypatch.setattr(glyphs, "to_clipboard", lambda ch: True)
    monkeypatch.setattr(glyphs, "PASTE_DELAY", 0)
    monkeypatch.setattr(glyphs, "paste_chord", lambda: (calls.append("chord") or True, "x"))
    monkeypatch.setattr(glyphs, "type_out", lambda ch: (calls.append("type") or True, "ydotool"))
    glyphs.use("a")
    assert calls == ["type"]


def test_what_the_person_copied_came_back_after_the_emoji_was_pasted(monkeypatch):
    """На Windows выбранный эмодзи не занимает буфер; у нас занимал, и скопированный текст терялся."""
    board = {"v": "мой скопированный текст"}
    monkeypatch.setattr(glyphs, "remember", lambda ch: None)
    monkeypatch.setattr(glyphs, "_clipboard_text", lambda: board["v"])
    monkeypatch.setattr(glyphs, "to_clipboard", lambda s: board.update(v=s) or True)
    monkeypatch.setattr(glyphs, "PASTE_DELAY", 0)
    monkeypatch.setattr(glyphs.time, "sleep", lambda s: None)
    monkeypatch.setattr(glyphs, "paste_chord", lambda: (True, "ydotool-ctrl-v"))
    glyphs.use("😀")
    assert board["v"] == "мой скопированный текст"
