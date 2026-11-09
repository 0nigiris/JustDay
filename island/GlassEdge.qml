// Кромка «жидкого стекла» (Р3-17). Кладётся в карточку панели и видна, только когда выбран
// материал «Стекло»; у матового и сплошного её нет.
//
// Первая версия (8 нояб.) была ровной белой рамкой и отсветом на верхнюю половину карточки, и он
// сказал: «выглядит как Windows 7 с их Aero, а не Liquid Glass». Именно широкий отсвет и
// одинаковая по всему кругу рамка и есть Aero. У Liquid Glass свет ловит только тонкая кромка:
// ярко сверху, почти пропадает по бокам и чуть оживает снизу, будто свет прошёл сквозь толщу и
// отразился от нижней грани. Сама поверхность при этом почти чистая.
import QtQuick
import QtQuick.Effects

Item {
    id: edge
    property real radius: 0
    visible: JD.glassOn
    anchors.fill: parent

    // Кольцо толщиной полтора пикселя служит маской, а светит сквозь него вертикальный градиент.
    // Rectangle сам не умеет рамку с градиентом, отсюда маска.
    Rectangle {
        id: ring
        anchors.fill: parent
        radius: edge.radius
        color: "transparent"
        border.width: 1.5
        border.color: "white"
        visible: false
        layer.enabled: true
    }
    Rectangle {
        anchors.fill: parent
        radius: edge.radius
        visible: false
        id: light
        layer.enabled: true
        gradient: Gradient {
            GradientStop { position: 0.0; color: Qt.rgba(1, 1, 1, 0.62) }
            GradientStop { position: 0.12; color: Qt.rgba(1, 1, 1, 0.22) }
            GradientStop { position: 0.5; color: Qt.rgba(1, 1, 1, 0.05) }
            GradientStop { position: 0.88; color: Qt.rgba(1, 1, 1, 0.10) }
            GradientStop { position: 1.0; color: Qt.rgba(1, 1, 1, 0.30) }
        }
    }
    MultiEffect {
        anchors.fill: parent
        source: light
        maskEnabled: true
        maskSource: ring
    }

    // Блик на верхней грани: короткая яркая полоска посередине, к краям гаснет. По нему глаз и
    // понимает, что перед ним толща стекла, а не тонированная плёнка.
    Rectangle {
        anchors { top: parent.top; topMargin: 1.5; horizontalCenter: parent.horizontalCenter }
        width: parent.width * 0.6
        height: 1
        gradient: Gradient {
            orientation: Gradient.Horizontal
            GradientStop { position: 0; color: Qt.rgba(1, 1, 1, 0) }
            GradientStop { position: 0.5; color: Qt.rgba(1, 1, 1, 0.35) }
            GradientStop { position: 1; color: Qt.rgba(1, 1, 1, 0) }
        }
    }
}
