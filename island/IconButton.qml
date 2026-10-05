import QtQuick

Pressable {
    id: ib
    property string icon: ""
    property real size: 30
    implicitWidth: size
    implicitHeight: size
    radius: size / 2
    color: hovered ? JD.fill2 : JD.fill1
    pressScale: JD.pressScaleSmall
    Icon { anchors.centerIn: parent; name: ib.icon; implicitSize: ib.size * 0.55 }
}
