// Вынесено из shell.qml (Р-80).
import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Wayland

// ───────────── genie minimize overlay ─────────────
// Scales a card from the window rect toward the dock icon, then the real window is
// minimized underneath. Avoids depending on KWin iconGeometry (empty without Plasma panel).
PanelWindow {
    id: genieWin
    visible: !!JD.genie
    anchors { top: true; bottom: true; left: true; right: true }
    exclusionMode: ExclusionMode.Ignore
    exclusiveZone: 0
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.namespace: "justday-genie"
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
    color: "transparent"
    mask: Region {}   // click-through

    property real t: 0
    onVisibleChanged: {
        if (visible) {
            t = 0
            genieAnim.restart()
        } else {
            t = 0
        }
    }
    NumberAnimation {
        id: genieAnim
        target: genieWin
        property: "t"
        from: 0; to: 1
        duration: JD.animOn ? 320 : 1
        easing.type: Easing.InCubic
        onFinished: JD.genie = null
    }

    readonly property var g: JD.genie
    readonly property real sx: g ? g.from.x + (g.to.x - g.from.x) * t : 0
    readonly property real sy: g ? g.from.y + (g.to.y - g.from.y) * t : 0
    readonly property real sw: g ? g.from.w + (g.to.w - g.from.w) * t : 0
    readonly property real sh: g ? g.from.h + (g.to.h - g.from.h) * t : 0

    Rectangle {
        visible: !!genieWin.g
        x: genieWin.sx - (genieWin.screen ? genieWin.screen.x : 0)
        y: genieWin.sy - (genieWin.screen ? genieWin.screen.y : 0)
        width: Math.max(8, genieWin.sw)
        height: Math.max(8, genieWin.sh)
        radius: Math.min(18, Math.min(width, height) * 0.18)
        color: Qt.rgba(0.08, 0.08, 0.1, 0.92 * (1 - genieWin.t * 0.35))
        border.width: 1
        border.color: Qt.rgba(1, 1, 1, 0.14 * (1 - genieWin.t))
        opacity: 1 - Math.pow(genieWin.t, 2.2)
        Icon {
            anchors.centerIn: parent
            theme: true
            name: genieWin.g ? (genieWin.g.icon || "") : ""
            implicitSize: Math.max(16, Math.min(parent.width, parent.height) * 0.42)
            opacity: 0.95
        }
    }
}
