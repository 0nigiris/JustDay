// Бегущая кошка: чем сильнее занят процессор, тем быстрее она бежит.
//
// Смысл её не в украшении. Число в процентах надо прочитать и сравнить с тем, каким оно было
// минуту назад; кошка же показывает занятость скоростью, а скорость видно боковым зрением — не
// глядя на док и не отвлекаясь от работы. Поэтому она и живёт в доке, а не в мониторе нагрузки.
import QtQuick
import Quickshell

Item {
    id: cat
    property real cpu: 0
    property real size: 22

    // Как у оригинала: от числа, а не от красоты. В покое — трусцой, под полной нагрузкой — спринт.
    readonly property int period: Math.round(Math.max(48, 270 - cpu * 2.2))
    property int frame: 0

    implicitWidth: Math.round(size * 32 / 22)
    implicitHeight: size

    Timer {
        interval: cat.period
        running: cat.visible && JD.animOn
        repeat: true
        onTriggered: cat.frame = (cat.frame + 1) % 5
    }

    // Все пять кадров лежат готовыми и только показываются по очереди: подгружать их по одному
    // значит получить рывок на первом же круге, а круг у кошки — двадцатая доля секунды.
    Repeater {
        model: 5
        delegate: Image {
            required property int index
            anchors.fill: parent
            visible: cat.frame === index
            source: Quickshell.shellDir + "/icons/cat/run" + index + ".svg"
            sourceSize: Qt.size(cat.implicitWidth * 3, cat.implicitHeight * 3)
            fillMode: Image.PreserveAspectFit
            mipmap: true
            smooth: true
        }
    }
}
