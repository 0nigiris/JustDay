// Живое дело в компактном виде — то, что остров показывает, пока дело идёт.
//
// Устройство ровно то, что описывает спецификация: ведущая часть говорит, **что** это, ведомая —
// **где оно сейчас**. Вместе они одна поверхность, а не две половины, поэтому и разделителя между
// ними нет: всё держится расстоянием.
//
// Правило, из-за которого половина кода: остров не должен шевелиться сам по себе. Меняются проценты
// — форма стоит. Меняется строка состояния — форма стоит. Двигаться остров имеет право только
// тогда, когда меняется само дело.
import QtQuick
import QtQuick.Layouts

Item {
    id: ap

    property var item: null                  // одно дело, как его отдаёт демон
    property var others: []                  // остальные — точками справа
    property bool compact: true

    readonly property bool has: !!item
    readonly property bool stale: has && item.stale === true
    readonly property string state: has ? (item.state || "active") : ""
    readonly property bool failed: state === "failed"
    readonly property bool done: state === "done"

    // Цвет здесь — сообщение, а не украшение: он значит состояние и ничего больше.
    readonly property color tint: failed ? JD.accentRed
        : done ? JD.accentGreen
        : stale ? JD.text3
        : tintOf(has ? item.tint : "")
    function tintOf(name) {
        return ({ green: JD.accentGreen, orange: JD.accentOrange, red: JD.accentRed,
                  blue: JD.accentBlue, purple: JD.accentPurple, pink: JD.accentPink,
                  grey: JD.text2 })[name] || JD.accentBlue
    }

    readonly property string valueText: {
        if (!has) return ""
        if (failed) return "не вышло"
        if (done) return "готово"
        if (item.left !== null && item.left !== undefined && item.left > 0) return leftAsWords(item.left)
        return ""
    }
    function leftAsWords(secs) {
        secs = Math.round(secs)
        if (secs < 60) return secs + " с"
        if (secs < 3600) return Math.round(secs / 60) + " мин"
        return Math.round(secs / 3600) + " ч"
    }

    implicitWidth: row.implicitWidth + 26
    implicitHeight: 30

    RowLayout {
        id: row
        anchors.centerIn: parent
        spacing: 10

        // ───────────── ведущая часть: что это ─────────────
        Icon {
            Layout.alignment: Qt.AlignVCenter
            name: ap.has ? (ap.failed ? "circle-alert" : ap.done ? "check" : item.icon) : "activity"
            implicitSize: 15
            tint: ap.tint
        }

        ColumnLayout {
            Layout.alignment: Qt.AlignVCenter
            spacing: 0
            Label1 {
                Layout.fillWidth: true
                font.pixelSize: 13
                color: ap.stale ? JD.text2 : JD.text1
                text: ap.has ? (item.title || "") : ""
            }
            Label2 {
                Layout.fillWidth: true
                visible: !!text
                font.pixelSize: 11
                color: JD.text3
                // Несвежее говорит об этом само: показывать старые проценты как сегодняшние —
                // это враньё, и спецификация запрещает его отдельным пунктом.
                text: ap.stale ? "нет обновлений" : (ap.has ? (item.status || "") : "")
            }
        }

        // ───────────── ведомая часть: где оно сейчас ─────────────
        ActivityProgress {
            Layout.alignment: Qt.AlignVCenter
            Layout.preferredWidth: 72
            visible: ap.has && !ap.failed && !ap.done
            value: ap.has && item.progress !== null && item.progress !== undefined ? item.progress : -1
            stale: ap.stale
            tint: ap.tint
            thickness: 4
            showValue: true
        }
        // Место под проценты занято всегда — оно уходит вместе с полоской, а не схлопывается.
        Item {
            Layout.alignment: Qt.AlignVCenter
            Layout.preferredWidth: 30
            Layout.preferredHeight: 1
            visible: ap.has && !ap.failed && !ap.done
        }

        Label1 {
            Layout.alignment: Qt.AlignVCenter
            visible: !!ap.valueText
            font.pixelSize: 12
            color: ap.tint
            text: ap.valueText
        }

        // ───────────── остальные дела: точками ─────────────
        //
        // Второстепенное занимает ровно столько места, сколько нужно, чтобы понять, что оно есть.
        // Спецификация зовёт это minimal, и смысл именно такой: узнаваемость без подробностей.
        Row {
            Layout.alignment: Qt.AlignVCenter
            Layout.leftMargin: ap.others.length ? 2 : 0
            spacing: 5
            Repeater {
                model: ap.others
                delegate: Rectangle {
                    required property var modelData
                    width: 7
                    height: 7
                    radius: 3.5
                    anchors.verticalCenter: parent.verticalCenter
                    color: ap.tintOf(modelData.tint)
                    opacity: modelData.stale ? 0.4 : 0.85
                    scale: 1
                    Behavior on opacity { enabled: JD.animOn; NumberAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
                }
            }
        }
    }

    // Тонкая цветная кромка — только когда состояние того стоит. Спецификация: подкраска не должна
    // перебивать содержимое, поэтому в обычном ходе дела её нет вовсе.
    Rectangle {
        anchors.fill: parent
        radius: height / 2
        color: "transparent"
        border.width: 1
        border.color: ap.failed ? Qt.rgba(1, 0.27, 0.23, 0.45)
                    : ap.done ? Qt.rgba(0.19, 0.82, 0.35, 0.40) : "transparent"
        Behavior on border.color { enabled: JD.animOn; ColorAnimation { duration: JD.durBase; easing.type: JD.easeOut } }
    }
}
