import QtQuick

Pressable {
    id: pb
    property string label: ""
    property color tint: JD.fill2
    property color labelColor: JD.text1
    implicitWidth: Math.max(88, lbl.implicitWidth + 28)
    implicitHeight: 32
    radius: 16
    color: hovered ? Qt.lighter(tint, 1.25) : tint
    Behavior on color { enabled: JD.animOn; ColorAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
    Text { font.family: JD.fontFamily; id: lbl; anchors.centerIn: parent; text: pb.label; color: pb.labelColor; font.pixelSize: 13; font.weight: Font.DemiBold }
}
