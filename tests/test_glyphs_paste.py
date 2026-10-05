"""Эмодзи не вставлялся сам: ydotool type печатает только латиницу, а с эмодзи молча отвечает «успех»."""
from justday import glyphs


def test_emoji_was_pasted_from_the_clipboard_not_typed_key_by_key(monkeypatch):
    calls = []
    monkeypatch.setattr(glyphs, "remember", lambda ch: None)
    monkeypatch.setattr(glyphs, "to_clipboard", lambda ch: True)
    monkeypatch.setattr(glyphs, "PASTE_DELAY", 0)
    monkeypatch.setattr(glyphs, "paste_chord", lambda *a: (calls.append("chord") or True, "ydotool-ctrl-v"))
    monkeypatch.setattr(glyphs, "type_out", lambda ch: (calls.append("type") or True, "ydotool"))
    got = glyphs.use("😀")
    assert calls == ["chord"] and got["typed"] and got["how"] == "ydotool-ctrl-v"


def test_plain_ascii_still_typed_directly(monkeypatch):
    calls = []
    monkeypatch.setattr(glyphs, "remember", lambda ch: None)
    monkeypatch.setattr(glyphs, "to_clipboard", lambda ch: True)
    monkeypatch.setattr(glyphs, "PASTE_DELAY", 0)
    monkeypatch.setattr(glyphs, "paste_chord", lambda *a: (calls.append("chord") or True, "x"))
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
    monkeypatch.setattr(glyphs, "paste_chord", lambda *a: (True, "ydotool-ctrl-v"))
    glyphs.use("😀")
    assert board["v"] == "мой скопированный текст"


def test_emoji_waited_for_the_window_not_for_a_fixed_pause(monkeypatch):
    """Вставка эмодзи была заметно медленной: полсекунды пауз вслепую перед Ctrl+V. Теперь она ждёт
    сообщения «окно снова активно» и не спит, если оно уже пришло."""
    slept, calls = [], []
    monkeypatch.setattr(glyphs, "remember", lambda ch: None)
    monkeypatch.setattr(glyphs, "_clipboard_text", lambda: None)
    monkeypatch.setattr(glyphs, "to_clipboard", lambda ch: True)
    monkeypatch.setattr(glyphs.time, "sleep", slept.append)
    monkeypatch.setattr(glyphs, "paste_chord", lambda *a: (calls.append("chord") or True, "ydotool-ctrl-v"))
    got = glyphs.use("😀", ready=lambda: True)
    assert calls == ["chord"] and got["typed"] and slept == []


def test_emoji_stayed_in_the_clipboard_when_no_window_took_the_focus_back(monkeypatch):
    """Окно не вернуло фокус — Ctrl+V ушёл бы в никуда, а ответ «вставлено» был бы враньём."""
    calls = []
    monkeypatch.setattr(glyphs, "remember", lambda ch: None)
    monkeypatch.setattr(glyphs, "_clipboard_text", lambda: None)
    monkeypatch.setattr(glyphs, "to_clipboard", lambda ch: True)
    monkeypatch.setattr(glyphs, "paste_chord", lambda *a: (calls.append("chord") or True, "x"))
    got = glyphs.use("😀", ready=lambda: False)
    assert calls == [] and not got["typed"] and got["copied"] and "буфере" in got["note"]


def test_daemon_waits_for_the_typing_window_to_come_back(monkeypatch):
    """После клика по панели фокус уходит к ней; вставка ждёт события KWin, а не угадывает паузу."""
    import threading
    import time
    from types import SimpleNamespace

    from justday import desktop
    from justday.daemon import Daemon

    asked = []
    monkeypatch.setattr(desktop, "windows", lambda action="list", **kw: asked.append(action) or [])
    me = SimpleNamespace(_last_active_id="w1", _windows=[{"id": "w1", "active": False}])
    threading.Timer(0.08, lambda: me._windows.__setitem__(0, {"id": "w1", "active": True})).start()
    start = time.monotonic()
    assert Daemon._focus_back(me)
    assert time.monotonic() - start < 0.3 and asked == []      # окно вернулось само, KWin не просили

    me._windows = [{"id": "w1", "active": False}]              # так и не вернулось
    assert not Daemon._focus_back(me) and asked == ["focus"]   # один раз попросили явно, потом честный отказ
    assert not Daemon._focus_back(SimpleNamespace(_last_active_id="", _windows=[]))


def test_emoji_into_a_terminal_was_pasted_with_ctrl_shift_v(monkeypatch):
    """В kitty/konsole Ctrl+V — это ^V, а не вставка: эмодзи не появлялся, ответ был «вставлено»."""
    chords = []
    monkeypatch.setattr(glyphs, "remember", lambda ch: None)
    monkeypatch.setattr(glyphs, "_clipboard_text", lambda: None)
    monkeypatch.setattr(glyphs, "to_clipboard", lambda ch: True)
    monkeypatch.setattr(glyphs, "paste_chord", lambda terminal=False: (chords.append(terminal) or True, "x"))
    glyphs.use("😀", ready=lambda: True, app="org.kde.konsole")
    glyphs.use("😀", ready=lambda: True, app="firefox")
    assert chords == [True, False]


def test_paste_chord_keys_for_terminal(monkeypatch):
    from justday import face
    ran = []
    monkeypatch.setattr(face, "session", lambda: "wayland")
    monkeypatch.setattr(glyphs.shutil, "which", lambda n: n if n == "ydotool" else None)
    monkeypatch.setattr(glyphs, "_ydotool_ready", lambda: True)
    monkeypatch.setattr(glyphs.subprocess, "run",
                        lambda cmd, **kw: ran.append(cmd) or type("P", (), {"returncode": 0})())
    assert glyphs.paste_chord(True) == (True, "ydotool-ctrl-shift-v")
    assert ran[-1] == ["ydotool", "key", "29:1", "42:1", "47:1", "47:0", "42:0", "29:0"]
    assert glyphs.paste_chord()[1] == "ydotool-ctrl-v"
    assert ran[-1] == ["ydotool", "key", "29:1", "47:1", "47:0", "29:0"]
    assert all(glyphs.is_terminal(a) for a in ("kitty", "org.wezfurlong.wezterm", "footclient", "Alacritty"))
    assert not glyphs.is_terminal("firefox")
