// Прогресс живого дела: полоска или кольцо.
//
// Два правила, оба из-за того, что эта штука живёт на острове месяцами, а не мелькает секунду.
//
// Первое: цифра не должна дёргать раскладку. «9%» и «100%» разной ширины, и если дать им течь, то
// остров на каждом проценте чуть-чуть меняет форму — сам по себе, без всякого события. Поэтому под
// значение отводится ширина самого широкого варианта, раз и навсегда.
//
// Второе: неизвестный прогресс — это не «ноль процентов». Когда процентов нет вовсе, полоска не
// стоит на нуле, а показывает, что работа идёт: бегущий отрезок. Ноль означал бы «ничего не
// сделано», а это другое утверждение.
import QtQuick

Item {
    id: pg

    property real value: -1          // 0…1; меньше нуля — неизвестно
    property bool ring: false        // кольцо вместо полоски
    property bool stale: false       // данные могли протухнуть
    property color tint: "#0a84ff"
    property real thickness: 4
    property bool showValue: true

    readonly property bool unknown: value < 0
    readonly property color track: Qt.rgba(1, 1, 1, 0.16)
    readonly property color ink: stale ? Qt.rgba(1, 1, 1, 0.35) : tint

    implicitWidth: ring ? 22 : 96
    implicitHeight: ring ? 22 : thickness

    // ───────────── полоска ─────────────
    Item {
        anchors.fill: parent
        visible: !pg.ring

        Rectangle {
            id: bar
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width
            height: pg.thickness
            radius: height / 2
            color: pg.track
            clip: true

            Rectangle {
                height: parent.height
                radius: height / 2
                color: pg.ink
                width: pg.unknown ? parent.width * 0.32 : parent.width * Math.max(0, Math.min(1, pg.value))
                x: pg.unknown ? runner.at * (parent.width + width) - width : 0
                Behavior on width { enabled: !pg.unknown && JD.animOn
                                    NumberAnimation { duration: 320; easing.type: Easing.OutCubic } }
                Behavior on color { enabled: JD.animOn; ColorAnimation { duration: 200 } }
            }
        }
    }

    // Отрезок бегает, только пока процентов нет: постоянное движение без смысла — то, чего
    // спецификация просит избегать отдельным пунктом.
    QtObject { id: runner; property real at: 0 }
    NumberAnimation {
        target: runner
        property: "at"
        running: pg.unknown && pg.visible && JD.animOn
        loops: Animation.Infinite
        from: 0
        to: 1
        duration: 1400
        easing.type: Easing.InOutSine
    }

    // ───────────── кольцо ─────────────
    Item {
        anchors.fill: parent
        visible: pg.ring

        Canvas {
            id: ringCanvas
            anchors.fill: parent
            onPaint: {
                const ctx = getContext("2d")
                const w = width, h = height, r = Math.min(w, h) / 2 - pg.thickness / 2
                ctx.reset()
                ctx.lineWidth = pg.thickness
                ctx.lineCap = "round"
                ctx.beginPath()
                ctx.arc(w / 2, h / 2, r, 0, Math.PI * 2)
                ctx.strokeStyle = pg.track
                ctx.stroke()
                const part = pg.unknown ? 0.25 : Math.max(0, Math.min(1, pg.value))
                if (part <= 0) return
                const from = -Math.PI / 2 + (pg.unknown ? runner.at * Math.PI * 2 : 0)
                ctx.beginPath()
                ctx.arc(w / 2, h / 2, r, from, from + Math.PI * 2 * part)
                ctx.strokeStyle = pg.ink
                ctx.stroke()
            }
        }
        Connections {
            target: pg
            function onValueChanged() { ringCanvas.requestPaint() }
            function onStaleChanged() { ringCanvas.requestPaint() }
            function onTintChanged() { ringCanvas.requestPaint() }
        }
        Connections {
            target: runner
            function onAtChanged() { if (pg.unknown && pg.ring) ringCanvas.requestPaint() }
        }
    }

    // ───────────── значение ─────────────
    //
    // Ширина под «100%» занята всегда: иначе каждый процент двигал бы то, что стоит правее.
    Text {
        id: valueText
        visible: pg.showValue && !pg.ring && !pg.unknown
        anchors { left: parent.right; leftMargin: 8; verticalCenter: parent.verticalCenter }
        width: widest.implicitWidth
        horizontalAlignment: Text.AlignRight
        font.family: JD.fontFamily
        font.pixelSize: 12
        font.weight: Font.DemiBold
        color: pg.stale ? JD.text3 : JD.text2
        text: Math.round(Math.max(0, Math.min(1, pg.value)) * 100) + "%"
    }
    Text {
        id: widest
        visible: false
        font: valueText.font
        text: "100%"
    }
}
