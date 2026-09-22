// Arc-reactor ring: pulses with the voice, spins while thinking
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
        Behavior on width { NumberAnimation { duration: 90 } }
        SequentialAnimation on opacity {
            running: JD.dstate === "speaking"
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
                Behavior on sweepAngle { NumberAnimation { duration: 300 } }
            }
        }
        RotationAnimation on rotation { running: ring.spinning; loops: Animation.Infinite; from: 0; to: 360; duration: 900 }
    }
}

// One icon language for the whole island: lucide strokes from island/icons (JD.glyphs),
// with the desktop's own icon theme left for the things the theme owns — app icons.
