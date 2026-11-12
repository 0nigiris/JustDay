// Пример своего значка состояния. Скопируйте в ~/.config/justday/orbs/pulse.qml и выберите
// «pulse» в Настройки → Вид → Значок состояния. Островок сам задаёт три свойства ниже.
import QtQuick

Item {
    id: me
    property string orbState: "working"   // listening | searching | solving | working
    property real size: 20
    property real voice: 0                // 0..1 — громкость голоса, пока он слушает

    Rectangle {
        anchors.centerIn: parent
        width: me.size * (0.55 + 0.45 * me.voice + 0.1 * pulse.v)
        height: width
        radius: width / 2
        color: me.orbState === "listening" ? "#5ac8fa" : me.orbState === "searching" ? "#ffd60a" : "#ffffff"
    }
    // Своё дыхание: QtObject с анимацией, чтобы не тянуть таймер.
    QtObject { id: pulse; property real v: 0 }
    SequentialAnimation {
        running: true; loops: Animation.Infinite
        NumberAnimation { target: pulse; property: "v"; to: 1; duration: me.orbState === "solving" ? 400 : 900; easing.type: Easing.InOutSine }
        NumberAnimation { target: pulse; property: "v"; to: 0; duration: me.orbState === "solving" ? 400 : 900; easing.type: Easing.InOutSine }
    }
}
