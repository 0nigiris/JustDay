"""Spotlight при пустом запросе: закреплённые, недавние и сетка программ в настоящем движке.

Беда: режим «Приложения» с первой выкладки ссылался на несуществующие `grid`, `mv` и `currentCategory` —
qmllint видит это лишь предупреждениями «про JD», компиляция проходит, а в окне при каждом открытии сыпались
ReferenceError, сетка не рисовалась и стрелки не двигались. Здесь файл поднимается живым Quickshell с
выдуманным каталогом: ни одной ошибки в журнале и верный порядок выбора."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ISLAND = Path(__file__).resolve().parent.parent / "src" / "justday" / "island"

PROBE = """import QtQuick
import Quickshell

ShellRoot {
    Component.onCompleted: {
        JD.menuCatalog = ({
            groups: [{id: "tools", name: "Инструменты", icon: "tools"}, {id: "web", name: "Сеть", icon: "web"}],
            apps: [
                {kind: "app", id: "a", name: "Альфа", icon: "x", cat: "tools"},
                {kind: "app", id: "b", name: "Бета", icon: "x", cat: "tools"},
                {kind: "app", id: "c", name: "Гамма", icon: "x", cat: "web"}],
            favourites: ["app:b"], pinned: ["app:b"], recent: ["app:b", "app:a"], session: []
        })
        JD.menuSearchMode = true
    }
    Item {
        width: 720; height: 700
        SpotlightView { id: s; anchors.fill: parent }
        Timer { interval: 500; running: true; onTriggered: {
            const names = () => s.tileRows.map(r => r.apps.map(a => a.name).join("+")).join("|")
            console.warn("PROBE rows=" + names() + " h=" + s.implicitHeight)
            JD.menuPick = 0; s.moveApps(1, 0)
            console.warn("PROBE down=" + JD.menuPick + " " + s.tileAt(JD.menuPick).name)
            s.moveApps(0, 1); console.warn("PROBE right=" + JD.menuPick)
            JD.menuPick = 0; s.take()
            Qt.exit(0)
        } }
    }
}
"""


@pytest.mark.skipif(not shutil.which("quickshell"), reason="Quickshell не установлен")
def test_apps_mode_renders_without_errors_and_arrows_walk_all_tiles(tmp_path) -> None:
    work = tmp_path / "island"
    shutil.copytree(ISLAND, work, ignore=shutil.ignore_patterns("__pycache__", "kwin-effects", "icons", "i18n"))
    for sub in ("icons", "i18n"):
        (work / sub).symlink_to(ISLAND / sub)
    (work / "probe.qml").write_text(PROBE, encoding="utf-8")
    run = subprocess.run(["quickshell", "-p", str(work / "probe.qml")], capture_output=True, text=True, timeout=90,
                         env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})
    log = run.stdout + run.stderr
    bad = [ln for ln in log.splitlines() if "SpotlightView" in ln and any(
        w in ln for w in ("ReferenceError", "TypeError", "Binding loop", "is not defined"))]
    assert not bad, "\n".join(bad)
    # закреплённая «Бета» сверху; недавняя без неё — «Альфа»; сетка первой категории — Альфа+Бета
    assert "PROBE rows=Бета|Альфа|Альфа+Бета h=596" in log, log[-1500:]
    assert "PROBE down=1 Альфа" in log
    assert "PROBE right=2" in log
