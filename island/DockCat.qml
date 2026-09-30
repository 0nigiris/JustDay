// Бегущая кошка: чем сильнее занят процессор, тем быстрее она бежит.
//
// Смысл её не в украшении. Число в процентах надо прочитать и сравнить с тем, каким оно было
// минуту назад; кошка же показывает занятость скоростью, а скорость видно боковым зрением — не
// глядя на док и не отвлекаясь от работы. Поэтому она и живёт в доке, а не в мониторе нагрузки.
//
// Кадры берутся у виджета CatWalk (Юрий Сауров, GPL-2.0+), если он стоит на этой машине: это та
// самая кошка, к которой человек привык, и рисовать похожую значило бы сделать хуже. Свои кадры
// остаются запасными. Формула скорости — оттуда же, а туда пришла из RunCat.
import QtQuick
import Quickshell

Item {
    id: cat
    property real cpu: 0
    property real size: 22
    // Ниже этого процента кошка спит. Ноль — не спит никогда, как в эталоне.
    property real sleepBelow: 0
    property bool awake: true            // док на виду; уехавший за край док кошку останавливает

    readonly property var frames: JD.dockCat.run || []
    readonly property bool own: frames.length === 0
    readonly property bool sleeping: sleepBelow > 0 && cpu < sleepBelow
    readonly property int period: Math.max(25, Math.ceil(5000 / Math.sqrt(cpu + 35) - 400))
    property int frame: 0

    implicitWidth: Math.round(size * (own ? 32 / 22 : 1.15))
    implicitHeight: size

    Timer {
        interval: cat.period
        running: cat.visible && cat.awake && JD.animOn && !cat.sleeping
        repeat: true
        onTriggered: cat.frame = (cat.frame + 1) % 5
    }

    // Все кадры лежат готовыми и только показываются по очереди: подгружать их по одному значит
    // получить рывок на первом же круге, а круг у кошки под нагрузкой — тридцатая доля секунды.
    Repeater {
        model: 5
        delegate: Image {
            required property int index
            anchors.fill: parent
            visible: !cat.sleeping && cat.frame === index
            source: cat.own ? Quickshell.shellDir + "/icons/cat/run" + index + ".svg"
                            : "file://" + cat.frames[index]
            sourceSize: Qt.size(cat.implicitHeight * 3, cat.implicitHeight * 3)
            fillMode: Image.PreserveAspectFit
            mipmap: true
            smooth: true
        }
    }

    Image {
        anchors.fill: parent
        visible: cat.sleeping && !!JD.dockCat.idle
        source: JD.dockCat.idle ? "file://" + JD.dockCat.idle : ""
        sourceSize: Qt.size(cat.implicitHeight * 3, cat.implicitHeight * 3)
        fillMode: Image.PreserveAspectFit
        mipmap: true
        smooth: true
    }
}
