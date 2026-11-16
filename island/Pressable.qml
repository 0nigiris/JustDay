import QtQuick

// Жест нажатия — один на все кнопки: затемнение подложки, его длительность и кривая лежат здесь, а не в
// девяти копиях с разным сжатием (0.88–0.97). Кнопки на macOS при нажатии не сжимаются, а темнеют;
// сжатие оставлено только значкам дока и трея (`JD.pressScaleSmall`), где оно и есть «нажали значок».
// Ловит и наведение, и нажатие.
Rectangle {
    id: p
    property bool pressEnabled: true
    property string sound: "click"      // "" — кнопка играет свой звук сама (переключатель)
    property alias hovered: hover.hovered
    property alias pressed: tap.pressed
    signal clicked()
    // Наведение: лёгкий свет поверх, одинаковый у всего, что нажимается. Он просил, чтобы любая
    // кнопка под курсором давала понять «на меня можно нажать» (16 нояб., «невероятно важно»).
    // Свой цвет при наведении у многих кнопок есть, но не у всех, и разный — этот слой общий.
    Rectangle {
        anchors.fill: parent
        radius: p.radius
        color: "white"
        opacity: hover.hovered && p.pressEnabled && !tap.pressed ? 0.07 : 0
        Behavior on opacity { enabled: JD.animOn; NumberAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
    }
    Rectangle {
        anchors.fill: parent
        radius: p.radius
        color: "black"
        opacity: tap.pressed ? 0.16 : 0
        Behavior on opacity { enabled: JD.animOn; NumberAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
    }
    HoverHandler { id: hover; cursorShape: p.pressEnabled ? Qt.PointingHandCursor : Qt.ArrowCursor }
    // Полиция жестов — не украшение. По умолчанию TapHandler берёт лишь пассивный захват, и нажатие
    // достаётся заодно всем обработчикам выше: стрелка «развернуть» на острове разворачивала текст
    // и тут же открывала поверх него панель управления. ReleaseWithinBounds берёт захват
    // исключительно — родитель молчит.
    TapHandler { id: tap; enabled: p.pressEnabled; gesturePolicy: TapHandler.ReleaseWithinBounds; onTapped: { if (p.sound) JD.sfx(p.sound); p.clicked() } }
}
