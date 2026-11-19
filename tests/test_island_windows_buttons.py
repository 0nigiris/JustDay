"""На Windows половина кнопок островка молчала (19 нояб., у друга): они звали xdg-open, wl-copy,
nmcli — программ, которых там нет, а execDetached без программы тихо ничего не делал."""
import importlib.util
import os
import sys
from pathlib import Path

import pytest

pytest.importorskip("PySide6")


def _host():
    spec = importlib.util.spec_from_file_location("jd_host", Path(__file__).parent.parent / "island" / "host.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_linux_buttons_do_something_on_windows(monkeypatch):
    host = _host()
    opened = []
    monkeypatch.setattr(os, "startfile", opened.append, raising=False)
    assert host._on_windows(["xdg-open", "https://example.org"])
    assert host._on_windows(["xdg-open", "trash:///"])
    assert host._on_windows(["nmcli", "radio", "wifi", "off"])
    assert host._on_windows(["spectacle", "-r"])
    assert opened == ["https://example.org", "shell:RecycleBinFolder", "ms-settings:network-wifi", "ms-screenclip:"]
    # Неизвестная программа — не наша забота: пусть ищется как обычно.
    assert not host._on_windows(["notepad.exe"])
    assert sys.modules  # модуль загрузился без падения
