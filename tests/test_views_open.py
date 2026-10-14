"""Каждый вид острова создаётся в настоящем Quickshell без ReferenceError и TypeError.

Беда та же, что у Spotlight и настроек: qmllint про неверные ссылки внутри делегатов молчит, а
`test_qml_loads` только компилирует. Демона нет, данные пустые — этого хватает, чтобы всплыла ссылка на
несуществующее имя при самой первой отрисовке. BarTrayIcon здесь нет: это делегат с required modelData."""
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ISLAND = Path(__file__).resolve().parent.parent / "src" / "justday" / "island"
VIEWS = ["MenuView", "ToolsView", "SessionsView", "HistoryView", "PlansView", "MixerView", "TrayView", "QrView",
         "MusicLibrary", "ControlTiles", "DockAudio", "DockClock", "DockCat", "Buddy", "Mascot",
         "DockView", "TrayMenu", "ChatWindow",
         # Вынесены из shell.qml (Р-80): внутри shell.qml они видели id главного окна (`island.mode`,
         # `videoView`), а в своём файле такая ссылка — ReferenceError при первой же отрисовке.
         "AnswerView", "ApprovalView", "Art", "CardHeader", "CardView", "CatCarry", "Chip", "ComposeView",
         "EqBars", "FlashView", "ListeningView", "ModeButton", "NotificationView", "PlayGlyph", "PlayerView",
         "RoundKey", "ThinkingView", "Tile", "VideoView", "VolumeRow", "Waveform", "PeekView", "AlarmView",
         "MusicView", "VideoPillView", "SectionLabel", "ExpandedView"]
# Окна дока, лотка, меню, тоста и OSD (PanelWindow) сюда не попадают: без layer-shell, в offscreen,
# Quickshell их не создаёт вовсе («No PanelWindow backend loaded»).

PROBE = """import QtQuick
import Quickshell

ShellRoot {
    id: r
    property var names: VIEWS_JSON
    property int i: 0
    property var cur: null
    Item { id: host; width: 900; height: 700 }
    Timer { interval: 600; running: true; repeat: true; onTriggered: {
        if (r.cur) { r.cur.destroy(); r.cur = null }
        if (r.i >= r.names.length) { Qt.exit(0); return }
        const n = r.names[r.i++]
        console.warn("PROBE view=" + n)
        const c = Qt.createComponent(Qt.resolvedUrl(n + ".qml"))
        if (c.status !== Component.Ready) { console.warn("PROBE FAIL " + n + " " + c.errorString()); return }
        r.cur = c.createObject(host, {})
    } }
}
""".replace("VIEWS_JSON", str(VIEWS).replace("'", '"'))


@pytest.mark.skipif(not shutil.which("quickshell"), reason="Quickshell не установлен")
def test_every_view_is_created_without_reference_errors(tmp_path) -> None:
    work = tmp_path / "island"
    shutil.copytree(ISLAND, work, ignore=shutil.ignore_patterns("__pycache__", "kwin-effects", "icons", "i18n"))
    for sub in ("icons", "i18n"):
        (work / sub).symlink_to(ISLAND / sub)
    (work / "probe.qml").write_text(PROBE, encoding="utf-8")
    run = subprocess.run(["quickshell", "-p", str(work / "probe.qml")], capture_output=True, text=True, timeout=150,
                         env={**os.environ, "QT_QPA_PLATFORM": "offscreen"})
    log = run.stdout + run.stderr
    assert f"PROBE view={VIEWS[-1]}" in log, log[-2000:]
    bad = [ln for ln in log.splitlines() if "PROBE FAIL" in ln or any(
        w in ln for w in ("ReferenceError", "TypeError", "is not defined"))]
    assert not bad, "\n".join(bad[:15])
