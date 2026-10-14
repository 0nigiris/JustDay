// Вынесено из shell.qml (Р-80).
import QtQuick
import QtQuick.Shapes

// ▶ / ❚❚ drawn in any colour (theme icons are light-only)
Item {
    id: pg
    property bool paused: true
    property real size: 20
    property color tint: "black"
    implicitWidth: size
    implicitHeight: size
    Row {
        visible: !pg.paused
        anchors.centerIn: parent
        spacing: pg.size * 0.22
        Rectangle { width: pg.size * 0.26; height: pg.size * 0.8; radius: width * 0.3; color: pg.tint }
        Rectangle { width: pg.size * 0.26; height: pg.size * 0.8; radius: width * 0.3; color: pg.tint }
    }
    Shape {
        visible: pg.paused
        anchors.fill: parent
        preferredRendererType: Shape.CurveRenderer
        ShapePath {
            fillColor: pg.tint
            strokeColor: pg.tint
            strokeWidth: pg.size * 0.08
            joinStyle: ShapePath.RoundJoin
            startX: pg.size * 0.26; startY: pg.size * 0.12
            PathLine { x: pg.size * 0.9; y: pg.size * 0.5 }
            PathLine { x: pg.size * 0.26; y: pg.size * 0.88 }
            PathLine { x: pg.size * 0.26; y: pg.size * 0.12 }
        }
    }
}
