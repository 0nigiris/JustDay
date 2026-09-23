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
    // Полиция жестов — не украшение. По умолчанию TapHandler берёт лишь
    // пассивный захват, и нажатие достаётся заодно всем обработчикам выше:
    // стрелка «развернуть» на острове разворачивала текст и тут же открывала
    // поверх него панель управления, так что развёрнутого никто не видел.
    // ReleaseWithinBounds берёт захват исключительно — родитель молчит.
    TapHandler { id: ibTap; gesturePolicy: TapHandler.ReleaseWithinBounds; onTapped: ib.clicked() }
}

// ───────────── compact views ─────────────
