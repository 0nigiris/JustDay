"""Что видно на экране: выбор между островом и полоской.

Проверяем ровно то, из-за чего это и появилось: решение принимается по сеансу, в котором программу
запустили, а не по тому, из которого её когда-то ставили."""
from __future__ import annotations

import subprocess

from justday import face


def _env(monkeypatch, **vars):
    for name in ("WAYLAND_DISPLAY", "XDG_SESSION_TYPE", "DISPLAY", "XDG_SESSION_ID"):
        monkeypatch.delenv(name, raising=False)
    for name, value in vars.items():
        monkeypatch.setenv(name, value)
    # loginctl в проверках не спрашиваем: ответ должен получаться из окружения.
    monkeypatch.setattr(face.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 1, stdout="", stderr=""))


def test_wayland_socket_beats_everything(monkeypatch):
    _env(monkeypatch, WAYLAND_DISPLAY="wayland-0", XDG_SESSION_TYPE="x11", DISPLAY=":0")
    assert face.session() == "wayland"     # сокет есть — значит Wayland, что бы ни говорили слова


def test_words_are_enough_without_the_socket(monkeypatch):
    _env(monkeypatch, XDG_SESSION_TYPE="x11", DISPLAY=":0")
    assert face.session() == "x11"


def test_display_alone_still_means_x11(monkeypatch):
    _env(monkeypatch, DISPLAY=":0")
    assert face.session() == "x11"


def test_nothing_known_is_admitted(monkeypatch):
    _env(monkeypatch)
    assert face.session() == ""


def test_logind_answers_when_the_service_started_too_early(monkeypatch):
    """Служба могла подняться раньше, чем сеанс донёс переменные до systemd."""
    _env(monkeypatch)
    monkeypatch.setattr(face.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 0, stdout="wayland\n", stderr=""))
    assert face.session() == "wayland"


def test_wayland_with_quickshell_gets_the_island(monkeypatch):
    monkeypatch.setattr(face, "session", lambda: "wayland")
    monkeypatch.setattr(face, "quickshell", lambda: "/usr/bin/qs")
    monkeypatch.setattr(face.config, "load", lambda: {"ui": {"face": "auto"}})
    what, why = face.pick()
    assert what == "island" and "Wayland" in why


def test_x11_gets_the_strip_and_says_why(monkeypatch):
    monkeypatch.setattr(face, "session", lambda: "x11")
    monkeypatch.setattr(face, "quickshell", lambda: "/usr/bin/qs")
    monkeypatch.setattr(face.config, "load", lambda: {"ui": {"face": "auto"}})
    what, why = face.pick()
    assert what == "panel" and "layer-shell" in why     # причина, а не просто отказ


def test_wayland_without_quickshell_falls_back(monkeypatch):
    monkeypatch.setattr(face, "session", lambda: "wayland")
    monkeypatch.setattr(face, "quickshell", lambda: "")
    monkeypatch.setattr(face.config, "load", lambda: {"ui": {"face": "auto"}})
    what, why = face.pick()
    assert what == "panel" and "Quickshell" in why


def test_the_setting_pins_the_choice(monkeypatch):
    monkeypatch.setattr(face, "quickshell", lambda: "/usr/bin/qs")
    monkeypatch.setattr(face, "session", lambda: "x11")
    monkeypatch.setattr(face.config, "load", lambda: {"ui": {"face": "island"}})
    assert face.pick()[0] == "island"          # остров на X11 — если человек хочет попробовать
    monkeypatch.setattr(face, "session", lambda: "wayland")
    monkeypatch.setattr(face.config, "load", lambda: {"ui": {"face": "panel"}})
    assert face.pick()[0] == "panel"           # полоска на Wayland — если остров мешает


def test_a_pinned_island_without_quickshell_still_shows_something(monkeypatch):
    monkeypatch.setattr(face, "session", lambda: "wayland")
    monkeypatch.setattr(face, "quickshell", lambda: "")
    monkeypatch.setattr(face.config, "load", lambda: {"ui": {"face": "island"}})
    what, why = face.pick()
    assert what == "panel" and "Quickshell" in why
