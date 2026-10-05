import QtQuick

// Жест нажатия — один на все кнопки: сжатие, его длительность и кривая лежат здесь и в JD, а не в
// девяти копиях с разным сжатием (0.88–0.97) и без кривой. Ловит и наведение, и нажатие.
Rectangle {
    id: p
    property real pressScale: JD.pressScale     // значок мал и сжимается сильнее: JD.pressScaleSmall
    property bool pressEnabled: true
    property alias hovered: hover.hovered
    property alias pressed: tap.pressed
    signal clicked()
    scale: tap.pressed ? pressScale : 1
    Behavior on scale { enabled: JD.animOn; NumberAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
    HoverHandler { id: hover; cursorShape: Qt.PointingHandCursor }
    // Полиция жестов — не украшение. По умолчанию TapHandler берёт лишь пассивный захват, и нажатие
    // достаётся заодно всем обработчикам выше: стрелка «развернуть» на острове разворачивала текст
    // и тут же открывала поверх него панель управления. ReleaseWithinBounds берёт захват
    // исключительно — родитель молчит.
    TapHandler { id: tap; enabled: p.pressEnabled; gesturePolicy: TapHandler.ReleaseWithinBounds; onTapped: p.clicked() }
}
