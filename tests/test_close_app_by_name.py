"""«Закрой Files» закрывал и редактор с files.py: имя программы искалось ещё и в заголовках окон (Р-22)."""
import json
import shutil
import subprocess

import pytest

from justday import desktop, fastpath

WMCTRL = (
    "0x03400003  0 4242   0    0    800 600 org.kde.kate.kate      Vasya  files.py — Kate\n"
    "0x03a00007  0 5151   0    0    800 600 org.gnome.Nautilus.Files Vasya  Загрузки\n"
)


def test_closing_an_app_by_name_leaves_windows_that_only_mention_it(monkeypatch):
    closed = []

    def run(cmd, *a, **kw):
        if cmd[0] == "wmctrl" and "-l" in cmd:
            return subprocess.CompletedProcess(cmd, 0, stdout=WMCTRL, stderr="")
        if cmd[:3] == ["wmctrl", "-i", "-c"]:
            closed.append(cmd[3])
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(desktop.subprocess, "run", run)
    monkeypatch.setattr(desktop, "_BACKEND", "x11")
    desktop.windows("close_app", "files")
    assert closed == ["0x03a00007"]


@pytest.mark.skipif(not shutil.which("node"), reason="нет node")
def test_the_kwin_script_closes_by_class_not_by_title():
    """Тот же разбор внутри KWin — его человек и запускает на Wayland."""
    js = desktop._KWIN_JS % {"query": json.dumps("files"), "action": json.dumps("close_app"),
                             "tag": json.dumps("T "), "wid": json.dumps("")}
    fake = """
const closed = [];
const mk = (id, cls, caption) => ({internalId: id, normalWindow: true, resourceClass: cls, resourceName: cls,
  caption, minimized: false, frameGeometry: {x: 0, y: 0, width: 1, height: 1}, closeWindow() { closed.push(id) }});
const workspace = {activeWindow: null, windowList: () => [mk("kate", "org.kde.kate", "files.py — Kate"),
                                                          mk("naut", "org.gnome.Nautilus.Files", "Загрузки")]};
const console = {warn() {}};
"""
    out = subprocess.run(["node", "-e", fake + js + "\nprocess.stdout.write(JSON.stringify(closed))"],
                         capture_output=True, text=True, timeout=10)
    assert json.loads(out.stdout) == ["naut"], out.stderr


def test_the_voice_shortcut_closes_the_app_not_every_title(monkeypatch):
    calls = []
    monkeypatch.setattr(fastpath, "_app", lambda t: {"name": "Files", "id": "org.gnome.Nautilus"})
    monkeypatch.setattr(fastpath.desktop, "windows", lambda action, term: calls.append(action) or [{}])
    assert fastpath.try_handle("закрой files") == "закрыл Files"
    assert calls and set(calls) == {"close_app"}
