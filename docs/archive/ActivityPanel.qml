// Живое дело, развёрнутое. Больше сведений и те действия, ради которых иначе пришлось бы открывать
// саму программу, — но не сама программа: это по-прежнему взгляд, а не рабочее место.
//
// Про непрерывность. Значок, название и прогресс стоят на тех же местах, что и в компактном виде, —
// просто крупнее и с воздухом. Так переход читается как «та же вещь развернулась», а не «одно окно
// сменилось другим»; спецификация настаивает на этом отдельно, и это верно: подменённое содержимое
// заставляет искать глазами заново.
import QtQuick
import QtQuick.Layouts

Item {
    id: apx

    property var item: null
    property var others: []
    signal acted(string what)

    readonly property bool has: !!item
    readonly property bool stale: has && item.stale === true
    readonly property string state: has ? (item.state || "active") : ""
    readonly property bool failed: state === "failed"
    readonly property bool done: state === "done"
    readonly property color tint: failed ? JD.accentRed
        : done ? JD.accentGreen
        : stale ? JD.text3
        : ({ green: JD.accentGreen, orange: JD.accentOrange, red: JD.accentRed, blue: JD.accentBlue,
             purple: JD.accentPurple, pink: JD.accentPink, grey: JD.text2 })[has ? item.tint : ""] || JD.accentBlue

    function clock(secs) {
        secs = Math.max(0, Math.round(secs || 0))
        const m = Math.floor(secs / 60), s = secs % 60
        return m >= 60 ? Math.floor(m / 60) + " ч " + (m % 60) + " мин"
             : m > 0 ? m + ":" + String(s).padStart(2, "0")
             : s + " с"
    }

    implicitWidth: 380
    implicitHeight: body.implicitHeight + 32

    ColumnLayout {
        id: body
        anchors { left: parent.left; right: parent.right; top: parent.top; margins: 16 }
        spacing: 12

        // ───────────── кто и что ─────────────
        RowLayout {
            Layout.fillWidth: true
            spacing: 12

            // Кольцо вокруг значка: тот же прогресс, что и полоской ниже, но читается издали и
            // держит значок на месте при любом числе процентов.
            Item {
                Layout.alignment: Qt.AlignVCenter
                implicitWidth: 40
                implicitHeight: 40
                ActivityProgress {
                    anchors.fill: parent
                    ring: true
                    thickness: 3
                    showValue: false
                    stale: apx.stale
                    tint: apx.tint
                    value: apx.has && item.progress !== null && item.progress !== undefined ? item.progress : -1
                    visible: !apx.failed && !apx.done
                }
                Icon {
                    anchors.centerIn: parent
                    name: apx.has ? (apx.failed ? "circle-alert" : apx.done ? "check" : item.icon) : "activity"
                    implicitSize: 18
                    tint: apx.tint
                }
            }

            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2
                Label1 {
                    Layout.fillWidth: true
                    font.pixelSize: 15
                    text: apx.has ? (item.title || "") : ""
                }
                Label2 {
                    Layout.fillWidth: true
                    visible: !!text
                    color: apx.stale ? JD.accentOrange : JD.text2
                    text: apx.stale ? "нет обновлений " + apx.clock(apx.has ? (item.elapsed || 0) : 0)
                                    : (apx.has ? (item.status || "") : "")
                }
            }

            Label1 {
                Layout.alignment: Qt.AlignVCenter
                visible: apx.has && !apx.failed && !apx.done && item.progress !== null && item.progress !== undefined
                font.pixelSize: 20
                color: apx.tint
                text: apx.has && item.progress !== null && item.progress !== undefined
                      ? Math.round(item.progress * 100) + "%" : ""
            }
        }

        // ───────────── сколько сделано ─────────────
        ActivityProgress {
            Layout.fillWidth: true
            Layout.preferredHeight: 6
            visible: !apx.failed && !apx.done
            thickness: 6
            showValue: false
            stale: apx.stale
            tint: apx.tint
            value: apx.has && item.progress !== null && item.progress !== undefined ? item.progress : -1
        }

        // ───────────── сколько это длится ─────────────
        RowLayout {
            Layout.fillWidth: true
            spacing: 16
            Label2 {
                color: JD.text3
                text: apx.has ? "идёт " + apx.clock(item.elapsed || 0) : ""
            }
            Label2 {
                visible: apx.has && item.left !== null && item.left !== undefined && item.left > 0 && !apx.done && !apx.failed
                color: JD.text3
                text: apx.has && item.left ? "осталось ~" + apx.clock(item.left) : ""
            }
            Item { Layout.fillWidth: true }
            Label2 {
                visible: apx.others.length > 0
                color: JD.text3
                text: apx.others.length === 1 ? "и ещё одно дело" : "и ещё " + apx.others.length
            }
        }

        // ───────────── что с этим можно сделать ─────────────
        RowLayout {
            Layout.fillWidth: true
            visible: apx.has && (item.actions || []).length > 0
            spacing: 8
            Repeater {
                model: apx.has ? (item.actions || []) : []
                delegate: PillButton {
                    required property var modelData
                    label: modelData.label || ""
                    tint: modelData.danger ? Qt.rgba(1, 0.27, 0.23, 0.22) : JD.fill2
                    labelColor: modelData.danger ? JD.accentRed : JD.text1
                    onClicked: apx.acted(modelData.id || "")
                }
            }
            Item { Layout.fillWidth: true }
        }
    }
}
