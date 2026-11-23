"""На Windows «открой ютуб» и «заблокируй экран» молча ничего не делали: xdg-open и loginctl там нет."""
import os

from justday import winaudio


def test_open_site_by_voice_on_windows_opens_it(monkeypatch):
    opened = []
    monkeypatch.setattr(os, "startfile", opened.append, raising=False)
    assert winaudio.run(("xdg-open", "https://youtube.com"))
    assert opened == ["https://youtube.com"]
