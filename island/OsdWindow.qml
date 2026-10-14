// Вынесено из shell.qml (Р-80).
import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Wayland
import Quickshell.Services.Pipewire

// ───────────── system OSD (volume / layout / brightness) — Noctalia-like, not app toasts ─────────────
// Own monitor + corner (island.osd_screen / osd_position). Telegram toasts stay on notification_*.
PanelWindow {
    id: osdWin
    property bool show: JD.osdShow && JD.island.show_osd !== false
    visible: show
    screen: JD.resolveOsdScreen()
    readonly property string oplace: JD.osdPlace
    readonly property bool oatTop: !oplace.startsWith("bottom")
    readonly property string oside: oplace.split("-")[1] || "center"
    anchors {
        left: true
        right: true
        top: oatTop
        bottom: !oatTop
    }
    exclusionMode: ExclusionMode.Ignore
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.namespace: "justday-osd"
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
    color: "transparent"
    implicitHeight: Math.min(screen ? screen.height : 800, 160)
    mask: Region { item: osdCard }

    Rectangle {
        id: osdCard
        anchors.top: osdWin.oatTop ? parent.top : undefined
        anchors.bottom: osdWin.oatTop ? undefined : parent.bottom
        anchors.topMargin: osdWin.oatTop ? JD.topMargin + (JD.islandStyle === "bar" && JD.atTop ? JD.barHeight + 10 : 0) : 0
        anchors.bottomMargin: osdWin.oatTop ? 0 : JD.topMargin
        x: osdWin.oside === "left" ? JD.sideMargin
         : osdWin.oside === "right" ? parent.width - width - JD.sideMargin
         : (parent.width - width) / 2
        width: Math.max(168, osdInner.implicitWidth + 28)
        height: osdInner.implicitHeight + 20
        radius: Math.min(height / 2, 22)
        color: JD.ink
        border.width: 1
        border.color: Qt.rgba(1, 1, 1, 0.08)
        opacity: osdWin.show ? 1 : 0
        Behavior on opacity { enabled: JD.animOn; NumberAnimation { duration: JD.dur(140); easing.type: JD.easeOut } }
        // Щелчок по плашке громкости открывает микшер: до него раньше было не добраться (Р2-48)
        TapHandler { enabled: JD.osdKind === "volume"; onTapped: JD.openTools("mixer") }

        Column {
            id: osdInner
            anchors.centerIn: parent
            spacing: 8
            width: Math.max(140, layoutRow.implicitWidth, barRow.visible ? 180 : 0)

            Row {
                id: layoutRow
                spacing: 10
                anchors.horizontalCenter: parent.horizontalCenter
                Icon {
                    name: JD.osdIcon || (JD.osdKind === "layout" ? "keyboard"
                                      : JD.osdKind === "brightness" ? "sun"
                                      : (JD.osdMuted || JD.osdValue <= 0.001) ? "volume-x" : "volume-1")
                    implicitSize: 22
                    tint: JD.text1
                    anchors.verticalCenter: parent.verticalCenter
                }
                Text {
                    text: JD.osdLabel || (JD.osdKind === "layout" ? JD.layoutShort : Math.round(JD.osdValue * 100) + "%")
                    color: JD.text1
                    font.family: JD.fontFamily
                    font.pixelSize: JD.osdKind === "layout" ? 18 : 14
                    font.weight: Font.DemiBold
                    anchors.verticalCenter: parent.verticalCenter
                }
            }
            Row {
                id: barRow
                visible: JD.osdKind === "volume" || JD.osdKind === "brightness"
                spacing: 0
                width: 180
                height: 6
                anchors.horizontalCenter: parent.horizontalCenter
                Rectangle {
                    width: parent.width
                    height: parent.height
                    radius: 3
                    color: Qt.rgba(1, 1, 1, 0.12)
                    Rectangle {
                        width: parent.width * (JD.osdMuted ? 0 : JD.osdValue)
                        height: parent.height
                        radius: 3
                        color: JD.osdKind === "brightness" ? JD.accentOrange : JD.accentBlue
                        Behavior on width { enabled: JD.animOn; NumberAnimation { duration: JD.dur(120); easing.type: JD.easeOut } }
                    }
                }
            }
        }
    }

    // Volume OSD: Pipewire default sink (hardware keys / mixer). Debounced; skips first snapshot.
    Item {
        id: osdVolWatch
        readonly property var sink: Pipewire.defaultAudioSink
        PwObjectTracker { objects: osdVolWatch.sink ? [osdVolWatch.sink] : [] }
        property real _lastVol: -1
        property bool _muted: false
        readonly property real sinkVol: sink && sink.audio ? Number(sink.audio.volume) || 0 : 0
        readonly property bool sinkMuted: !!(sink && sink.audio && sink.audio.muted)
        onSinkVolChanged: osdVolDebounce.restart()
        onSinkMutedChanged: osdVolDebounce.restart()
        onSinkChanged: Qt.callLater(osdVolWatch.push)
        function push() {
            if (!sink || !sink.audio) return
            const muted = sinkMuted
            const vol = muted ? 0 : Math.max(0, Math.min(1, sinkVol))
            if (!JD._osdPrimed) {
                JD._osdPrimed = true
                _lastVol = vol
                _muted = muted
                return
            }
            if (Math.abs(vol - _lastVol) < 0.004 && muted === _muted) return
            _lastVol = vol
            _muted = muted
            const pct = Math.round(vol * 100)
            const icon = muted || vol <= 0.001 ? "volume-x" : (vol < 0.5 ? "volume-1" : "volume-2")
            JD.showOsd("volume", vol, (muted ? JD.tr("Без звука") : (pct + "%")), icon, muted)
        }
        Timer { id: osdVolDebounce; interval: 60; onTriggered: osdVolWatch.push() }
        Component.onCompleted: Qt.callLater(osdVolWatch.push)
    }
}
