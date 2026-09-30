// Arc-reactor ring: pulses with the voice, spins while thinking
//
// Каждая здешняя анимация спрашивает `visible` — и это не перестраховка, а починка. Кольцо стоит в
// десятке мест сразу, и некоторые из них показываются раз в неделю: кружок «грузится» в проигрывателе,
// кольцо в развёрнутом виде. Вид скрыт, а кольцо в нём крутилось всё время: Qt анимирует и невидимое,
// поворот шёл шестьдесят раз в секунду, окно островка каждый раз считалось изменившимся и рисовалось
// заново. Само рисование занимало ноль миллисекунд — платили за то, что кадр вообще собирали, и это
// была треть процессорного ядра круглые сутки, из-за которой «бар чуть лагает».
//
// `visible` в QML — видимость настоящая, с учётом всех родителей. Поэтому одной проверки внутри
// кольца хватает на все места, где оно стоит.
import QtQuick
import QtQuick.Shapes

Item {
    id: ring
    property color tint: JD.accentFor(JD.dstate)
    property real size: 22
    property bool spinning: JD.dstate === "thinking" || JD.dstate === "transcribing"
    implicitWidth: size
    implicitHeight: size
    Rectangle {
        anchors.centerIn: parent
        width: ring.size * (0.42 + 0.3 * Math.min(1, JD.level * (JD.dstate === "listening" ? 1 : 0)))
        height: width
        radius: width / 2
        color: ring.tint
        opacity: 0.9
        Behavior on width { enabled: ring.visible; NumberAnimation { duration: 90 } }
        SequentialAnimation on opacity {
            running: ring.visible && JD.dstate === "speaking"
            loops: Animation.Infinite
            NumberAnimation { to: 0.45; duration: 420; easing.type: Easing.InOutSine }
            NumberAnimation { to: 0.95; duration: 420; easing.type: Easing.InOutSine }
        }
    }
    Shape {
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            strokeColor: ring.tint
            strokeWidth: 2
            fillColor: "transparent"
            capStyle: ShapePath.RoundCap
            PathAngleArc {
                centerX: ring.size / 2; centerY: ring.size / 2
                radiusX: ring.size / 2 - 1.5; radiusY: radiusX
                startAngle: 0
                sweepAngle: ring.spinning ? 250 : 360
                Behavior on sweepAngle { enabled: ring.visible; NumberAnimation { duration: 300 } }
            }
        }
        RotationAnimation on rotation {
            running: ring.visible && ring.spinning
            loops: Animation.Infinite
            from: 0
            to: 360
            duration: 900
        }
    }
}

// One icon language for the whole island: lucide strokes from island/icons (JD.glyphs),
// with the desktop's own icon theme left for the things the theme owns — app icons.
