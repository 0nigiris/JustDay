"""Все страницы настроек в настоящем движке: ни одного ReferenceError, Binding loop и пропавшей иконки.

Беда та же, что у Spotlight (и тут нашлись: `acc` в строке «Аккаунт Ollama» не виден из дочерних кнопок,
стрелки порядка шагов цикла ссылались на несуществующие иконки и были пустыми кнопками): qmllint про неверные ссылки внутри делегатов молчит, test_qml_loads только
компилирует, а в окне страница молча остаётся пустой. Здесь SettingsView поднимается живым Quickshell
(демона нет — `win.get` отдаёт пустое), и по очереди открывается каждая страница."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ISLAND = Path(__file__).resolve().parent.parent / "island"
PAGES = ["general", "character", "model", "dock", "notifications", "voice", "media", "mail", "people",
         "buttons", "memory", "cycle", "privacy", "about"]

PROBE = """import QtQuick
import Quickshell

ShellRoot {
    Item {
        id: root
        width: 900; height: 700
        SettingsView { id: s; anchors.fill: parent }
        property var pages: PAGES_JSON
        property int i: 0
        Timer { interval: 250; running: true; repeat: true; onTriggered: {
            if (root.i >= root.pages.length) { Qt.exit(0); return }
            JD.settingsPage = root.pages[root.i]; console.warn("PROBE page=" + root.pages[root.i]); root.i++
        } }
    }
}
""".replace("PAGES_JSON", str(PAGES).replace("'", '"'))


@pytest.mark.skipif(not shutil.which("quickshell"), reason="Quickshell не установлен")
def test_every_settings_page_opens_without_qml_errors(tmp_path) -> None:
    work = tmp_path / "island"
    shutil.copytree(ISLAND, work, ignore=shutil.ignore_patterns("__pycache__", "kwin-effects", "icons", "i18n"))
    for sub in ("icons", "i18n"):
        (work / sub).symlink_to(ISLAND / sub)
    (work / "probe.qml").write_text(PROBE, encoding="utf-8")
    run = subprocess.run(["quickshell", "-p", str(work / "probe.qml")], capture_output=True, text=True, timeout=120,
                         env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})
    log = run.stdout + run.stderr
    assert "PROBE page=about" in log, log[-2000:]
    bad = [ln for ln in log.splitlines() if "SettingsView" in ln and any(
        w in ln for w in ("ReferenceError", "TypeError", "Binding loop", "is not defined", "Unable to assign", "Cannot open"))]
    assert not bad, "\n".join(bad[:15])
