"""Окна на X11: разбор wmctrl — тем же форматом, что отдаёт путь через KWin."""
import subprocess

from justday import desktop

WMCTRL = (
    "0x03400003  0 4242   0    0    2560 1400 discord.discord  Vasya  Discord — общий\n"
    "0x03a00007  0 5151   100  50   1200 800  code.Code        Vasya  daemon.py — JustDay\n"
    "0x01000002 -1 900    0    0    2560 40   plasmashell.plasmashell Vasya Панель\n"
)


def _fake_run(monkeypatch, active="0x03a00007"):
    def run(cmd, *a, **kw):
        if cmd[0] == "wmctrl" and "-l" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout=WMCTRL, stderr="")
        if cmd[0] == "xprop":
            return subprocess.CompletedProcess(cmd, 0, stdout=f"_NET_ACTIVE_WINDOW(WINDOW): window id # {active}\n", stderr="")
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(desktop.subprocess, "run", run)
    monkeypatch.setattr(desktop, "_BACKEND", "x11")


def test_list_skips_panels_and_marks_the_active_one(monkeypatch):
    _fake_run(monkeypatch)
    got = desktop.windows("list")
    assert [w["app"] for w in got] == ["discord", "Code"]          # рабочий стол (-1) — не окно программы
    assert [w["active"] for w in got] == [False, True]
    assert got[0]["w"] == 2560 and got[1]["x"] == 100
    assert got[1]["pid"] == 5151


def test_query_filters_by_title_and_class(monkeypatch):
    _fake_run(monkeypatch)
    assert [w["app"] for w in desktop.windows("list", "дискорд")] == []
    assert [w["app"] for w in desktop.windows("list", "discord")] == ["discord"]
    assert [w["title"] for w in desktop.windows("list", "justday")] == ["daemon.py — JustDay"]


def test_active_returns_only_the_focused_window(monkeypatch):
    _fake_run(monkeypatch, active="0x03400003")
    got = desktop.windows("active")
    assert len(got) == 1 and got[0]["app"] == "discord"


def test_click_uses_xdotool_with_sync_and_button(monkeypatch):
    seen = []

    def run(cmd, *a, **kw):
        seen.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(desktop.subprocess, "run", run)
    monkeypatch.setattr(desktop, "_BACKEND", "x11")
    monkeypatch.setattr("justday.face.session", lambda: "x11")
    monkeypatch.setattr(desktop.shutil, "which", lambda name: "/usr/bin/" + name)
    assert desktop.pointer(300, 420, button=3)["ok"]
    assert seen[0] == ["xdotool", "mousemove", "--sync", "300", "420", "click", "3"]
    assert desktop.pointer(10, 20, double=True)["ok"]
    assert "--repeat" in seen[1] and seen[1][-1] == "1"


def test_keys_clears_modifiers(monkeypatch):
    seen = []
    monkeypatch.setattr(desktop.subprocess, "run",
                        lambda cmd, *a, **kw: (seen.append(cmd), subprocess.CompletedProcess(cmd, 0, stdout="", stderr=""))[1])
    monkeypatch.setattr(desktop, "_BACKEND", "x11")
    monkeypatch.setattr("justday.face.session", lambda: "x11")
    monkeypatch.setattr(desktop.shutil, "which", lambda name: "/usr/bin/" + name)
    assert desktop.keys("ctrl+s")["ok"]
    assert seen[0] == ["xdotool", "key", "--clearmodifiers", "ctrl+s"]


def test_on_wayland_the_click_explains_where_it_lives(monkeypatch):
    monkeypatch.setattr(desktop, "_BACKEND", "kwin")
    monkeypatch.setattr("justday.face.session", lambda: "wayland")
    r = desktop.pointer(1, 1)
    assert not r["ok"] and "kwin-mcp" in r["error"]


def test_with_nothing_available_it_says_so(monkeypatch):
    monkeypatch.setattr(desktop, "_BACKEND", "")
    monkeypatch.setattr("justday.face.session", lambda: "")
    assert "xdotool" in desktop.keys("Return")["error"]


def test_kde_on_x11_clicks_with_xdotool_not_a_refusal(monkeypatch):
    """KDE бывает и на X11: там backend() отвечает «kwin» (скрипты KWin работают и в иксах), но
    щёлкать надо через xdotool. Раньше эта команда отвечала «на Wayland щелчки идут через kwin-mcp»
    — на машине, где никакого Wayland в этом сеансе и нет."""
    seen = []
    monkeypatch.setattr(desktop.subprocess, "run",
                        lambda cmd, *a, **kw: (seen.append(cmd), subprocess.CompletedProcess(cmd, 0, stdout="", stderr=""))[1])
    monkeypatch.setattr(desktop, "_BACKEND", "kwin")
    monkeypatch.setattr("justday.face.session", lambda: "x11")
    monkeypatch.setattr(desktop.shutil, "which", lambda name: "/usr/bin/" + name)
    assert desktop.pointer(5, 6)["ok"]
    assert seen[0][0] == "xdotool"
