pragma ComponentBehavior: Bound
import QtQuick

// Число, у которого меняющиеся цифры прокатываются, а не мигают: громкость и таймер меняются
// по единице, и подмена всей строки разом выглядела дёрганьем («мелочи против слопа», план).
// Каждая цифра катится сама: при 59 → 60 двигаются обе, при 61 → 62 только последняя.
Row {
    id: roll
    property string text: ""
    property color color: JD.text1
    property int pixelSize: 13
    property int weight: Font.Normal

    Repeater {
        model: roll.text.length
        delegate: Item {
            id: cell
            required property int index
            readonly property string ch: roll.text.charAt(index)
            property string was: ch
            implicitWidth: now.implicitWidth
            implicitHeight: now.implicitHeight
            clip: true

            Text {
                id: now
                text: cell.ch
                color: roll.color; font.family: JD.fontFamily; font.pixelSize: roll.pixelSize
                font.weight: roll.weight; font.features: { "tnum": 1 }
            }
            Text {
                id: old
                visible: false
                color: roll.color; font.family: JD.fontFamily; font.pixelSize: roll.pixelSize
                font.weight: roll.weight; font.features: { "tnum": 1 }
            }
            onChChanged: {
                if (!JD.animOn || was === ch) { was = ch; return }
                // Больше — новая приходит снизу, как на счётчике; меньше — сверху.
                const up = ch > was
                old.text = was
                was = ch
                const h = now.implicitHeight
                old.visible = true
                oldMove.from = 0; oldMove.to = up ? -h : h
                nowMove.from = up ? h : -h; nowMove.to = 0
                go.restart()
            }
            ParallelAnimation {
                id: go
                NumberAnimation { id: oldMove; target: old; property: "y"; duration: JD.durBase; easing.type: JD.easeOut }
                NumberAnimation { id: nowMove; target: now; property: "y"; duration: JD.durBase; easing.type: JD.easeOut }
                onFinished: old.visible = false
            }
        }
    }
}
