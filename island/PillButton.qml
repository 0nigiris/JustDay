import QtQuick

Rectangle {
    id: pb
    property string label: ""
    property color tint: JD.fill2
    property color labelColor: JD.text1
    signal clicked()
    implicitWidth: Math.max(88, lbl.implicitWidth + 28)
    implicitHeight: 32
    radius: 16
    color: pbHover.hovered ? Qt.lighter(tint, 1.25) : tint
    scale: pbTap.pressed ? 0.95 : 1
    Behavior on scale { NumberAnimation { duration: 120 } }
    Behavior on color { ColorAnimation { duration: 120 } }
    Text { font.family: JD.fontFamily; id: lbl; anchors.centerIn: parent; text: pb.label; color: pb.labelColor; font.pixelSize: 13; font.weight: Font.DemiBold }
    HoverHandler { id: pbHover; cursorShape: Qt.PointingHandCursor }
    TapHandler { id: pbTap; onTapped: pb.clicked() }
}
