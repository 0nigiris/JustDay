// Вынесено из shell.qml (Р-80).
import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Wayland

// ───────────── notification toast (Telegram-style corner on a chosen monitor) ─────────────
// Independent of the island pill: Settings → Виджеты → monitor + corner. Default: secondary,
// top-right. The island mode "notification" is suppressed while this window shows the toast.
PanelWindow {
    id: notifWin
    property bool show: !!JD.notification && JD.island.show_notifications !== false
    visible: show
    screen: JD.resolveNotifScreen()
    readonly property string nplace: JD.notifPlace
    readonly property bool natTop: !nplace.startsWith("bottom")
    readonly property string nside: nplace.split("-")[1] || "center"
    anchors {
        left: true
        right: true
        top: natTop
        bottom: !natTop
    }
    exclusionMode: ExclusionMode.Ignore
    WlrLayershell.layer: WlrLayer.Overlay
    WlrLayershell.namespace: "justday-notification"
    WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
    color: "transparent"
    implicitHeight: Math.min(screen ? screen.height : 800, 280)
    mask: Region { item: notifIsland }

    Rectangle {
        id: notifIsland
        anchors.top: notifWin.natTop ? parent.top : undefined
        anchors.bottom: notifWin.natTop ? undefined : parent.bottom
        anchors.topMargin: notifWin.natTop ? JD.topMargin : 0
        anchors.bottomMargin: notifWin.natTop ? 0 : JD.topMargin
        x: notifWin.nside === "left" ? JD.sideMargin
         : notifWin.nside === "right" ? parent.width - width - JD.sideMargin
         : (parent.width - width) / 2
        width: Math.max(120, notifToast.implicitWidth)
        height: notifToast.implicitHeight
        radius: Math.min(height / 2, 30)
        color: JD.ink
        border.width: 1
        border.color: Qt.rgba(1, 1, 1, 0.06)
        clip: true
        NotificationView {
            id: notifToast
            shown: notifWin.show
        }
    }
}
