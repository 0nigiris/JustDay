// Вынесено из shell.qml (Р-80).
import QtQuick

// equaliser bars in the cover's colour; they settle down when the music pauses
Item {
    id: eq
    property color tint: JD.accentPink
    property bool playing: true
    property real t: 0
    implicitWidth: 22
    implicitHeight: 18
    // 30 кадров в секунду, а не по кадру монитора: четыре столбика по 3 пикселя, ради которых окно острова
    // (1920×880) перерисовывалось 165 раз в секунду (Р-44). Глазу на столбиках разницы нет.
    Timer { interval: 33; repeat: true; running: eq.visible && eq.playing && JD.animOn; onTriggered: eq.t += 0.033 }
    Row {
        anchors.centerIn: parent
        spacing: 2.5
        Repeater {
            model: 4
            Rectangle {
                required property int index
                width: 3
                radius: 1.5
                color: eq.tint
                anchors.verticalCenter: parent.verticalCenter
                height: eq.playing ? 4 + 13 * Math.abs(Math.sin(eq.t * (3.1 + index * 1.7) + index * 1.9) * Math.sin(eq.t * (1.3 + index * 0.6) + index))
                                   : 3 + (index % 2)
                Behavior on height { enabled: !eq.playing && JD.animOn; NumberAnimation { duration: JD.durBase; easing.type: JD.easeOut } }
            }
        }
    }
}

// ▶ / ❚❚ drawn in any colour (theme icons are light-only)
