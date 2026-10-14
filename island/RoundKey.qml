// Вынесено из shell.qml (Р-80).
import QtQuick

// a small round button that takes the click for itself (the rest of the notification opens the app)
Pressable {
    id: rk
    property string icon: ""
    implicitWidth: 28
    implicitHeight: 28
    radius: 14
    color: hovered ? JD.fill2 : JD.fill1
    Icon { anchors.centerIn: parent; name: rk.icon; implicitSize: 14 }
}

// a desktop notification: ⌄ unfolds the whole text, ✕ lets it go, a tap anywhere else opens the app
