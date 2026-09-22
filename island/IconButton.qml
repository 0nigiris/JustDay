import QtQuick

Rectangle {
    id: ib
    property string icon: ""
    property real size: 30
    signal clicked()
    implicitWidth: size
    implicitHeight: size
    radius: size / 2
    color: ibHover.hovered ? JD.fill2 : JD.fill1
    scale: ibTap.pressed ? 0.9 : 1
    Behavior on scale { NumberAnimation { duration: 120 } }
    Icon { anchors.centerIn: parent; name: ib.icon; implicitSize: ib.size * 0.55 }
    HoverHandler { id: ibHover; cursorShape: Qt.PointingHandCursor }
    TapHandler { id: ibTap; onTapped: ib.clicked() }
}

// ───────────── compact views ─────────────
