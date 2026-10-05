import QtQuick
import QtQuick.Effects

// Один значок трея на сплошной полосе и в карточке скрытых под шевроном: один и тот же жест
// в обоих местах, а не две копии с разными поправками.
Item {
    id: bt
    required property var modelData
    property real size: JD.barTraySize
    // Значок дали нажать: карточка скрытых по этому сигналу закрывается.
    signal used()
    implicitWidth: size + 10
    implicitHeight: size + 10
    // Те же движения, что у лотка (TrayView): рамка под рукой, значок подрастает, при нажатии
    // проседает до 0.88. Раньше на полосе значки не отвечали ничем, и было непонятно, попал ли курсор.
    Rectangle {
        anchors.centerIn: parent
        width: icon.width * icon.scale + 8
        height: width
        radius: Math.round(height * 0.3)
        color: "transparent"
        border.width: 1
        border.color: Qt.rgba(1, 1, 1, hit.pressed ? 0.34 : 0.22)
        opacity: hit.containsMouse && JD.trayCfg.hover_frame !== false ? 1 : 0
        Behavior on opacity { enabled: JD.animOn; NumberAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
    }
    Image {
        id: icon
        anchors.centerIn: parent
        width: bt.size
        height: bt.size
        sourceSize: Qt.size(bt.size * 2, bt.size * 2)
        source: bt.modelData.icon || ""
        fillMode: Image.PreserveAspectFit
        // без asynchronous: image://icon в фоновом потоке роняет KIconLoader (Icon.qml)
        scale: hit.pressed ? JD.pressScaleSmall : hit.containsMouse ? 1.15 : 1
        Behavior on scale { enabled: JD.animOn; NumberAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
        // Та же вуаль, что у значков дока и лотка (Icon.qml): цвета остаются, подтягивается яркость.
        readonly property string wash: JD.trayWash(bt.modelData)
        layer.enabled: wash !== "none"
        layer.effect: MultiEffect {
            colorization: icon.wash === "mono" ? 0 : icon.wash === "tinted" ? 0.42 : icon.wash === "clear" ? 0.28 : 0.18
            colorizationColor: icon.wash === "tinted" ? (String(JD.trayCfg.icon_tint || "").trim() || "#7AC8FF")
                               : icon.wash === "clear" ? "#FFFFFF" : "#E8EEF6"
            brightness: icon.wash === "clear" ? 0.22 : icon.wash === "light" ? 0.14 : icon.wash === "tinted" ? 0.06 : 0
            saturation: icon.wash === "mono" ? 0 : icon.wash === "tinted" ? 0.55 : icon.wash === "clear" ? 0.75 : 0.9
        }
    }
    MouseArea {
        id: hit
        anchors.fill: parent
        acceptedButtons: Qt.LeftButton | Qt.RightButton | Qt.MiddleButton
        hoverEnabled: true
        cursorShape: Qt.PointingHandCursor
        onClicked: mouse => {
            const it = bt.modelData
            if (mouse.button === Qt.MiddleButton) { it.secondaryActivate(); return }
            if (mouse.button === Qt.RightButton || (it.onlyMenu && it.hasMenu)) {
                if (JD.trayMenu === it) { JD.closeTrayMenu(); return }
                const p = bt.mapToItem(null, bt.width, bt.height + 8)
                JD.trayMenuFromBar = true
                JD.openTrayMenu(it, p.x, p.y)
                bt.used()
                return
            }
            JD.closeTrayMenu()
            it.activate()
            JD.trayWake(it)
            bt.used()
        }
        onWheel: wheel => bt.modelData.scroll(wheel.angleDelta.y, false)
    }
}
