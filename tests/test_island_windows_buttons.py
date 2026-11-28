"""На Windows половина кнопок островка молчала (19 нояб., у друга): они звали xdg-open, wl-copy,
nmcli — программ, которых там нет, а execDetached без программы тихо ничего не делал."""
import importlib.util
import json
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


def test_settings_window_gets_its_answer(tmp_path):
    """Окно настроек на Windows писало «settings-data: не отвечает» (28 нояб., у подруги): процесс,
    созданный createObject, стартовал раньше, чем получал команду, а конец процесса не доходил до QML."""
    host = _host()
    from PySide6.QtCore import QTimer, QUrl
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtQml import QQmlApplicationEngine

    qml = tmp_path / "t.qml"
    qml.write_text("""import QtQuick
import Quickshell.Io
Item {
    property string got: ""
    Component { id: pc
        Process { id: p; running: true
            stdout: StdioCollector { id: so }
            onExited: (c) => got = c + ":" + so.text.trim() } }
    Component.onCompleted: pc.createObject(this, { command: [@EXE@, "-c", "print('ok')"] })
}""".replace("@EXE@", json.dumps(sys.executable)), encoding="utf-8")
    app = QGuiApplication.instance() or QGuiApplication([])
    host._register_qml()
    eng = QQmlApplicationEngine()
    eng.load(QUrl.fromLocalFile(str(qml)))
    root = eng.rootObjects()[0]
    QTimer.singleShot(15000, app.quit)
    root.gotChanged.connect(app.quit)
    app.exec()
    assert root.property("got") == "0:ok"
