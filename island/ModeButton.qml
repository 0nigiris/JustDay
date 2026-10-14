// Вынесено из shell.qml (Р-80).
import QtQuick

// a round toggle for shuffle / repeat: lit in the cover's colour when on
Pressable {
    id: mb
    property string icon: ""
    property bool on: false
    property color tint: JD.accentPink
    property string badge: ""
    implicitWidth: 36
    implicitHeight: 36
    radius: 18
    color: on ? Qt.rgba(tint.r, tint.g, tint.b, 0.28) : (hovered ? JD.fill2 : "transparent")
    Behavior on color { enabled: JD.animOn; ColorAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
    Icon { anchors.centerIn: parent; name: mb.icon; implicitSize: 18; opacity: mb.on ? 1 : 0.55 }
    Rectangle {
        visible: !!mb.badge
        anchors { right: parent.right; top: parent.top; rightMargin: 3; topMargin: 3 }
        width: 13; height: 13; radius: 6.5
        color: mb.tint
        Text { anchors.centerIn: parent; text: mb.badge; color: "black"; font.family: JD.fontFamily; font.pixelSize: 9; font.weight: Font.Bold }
    }
}

// the big player: cover, title, progress, shuffle · prev · play · next · repeat, the queue
