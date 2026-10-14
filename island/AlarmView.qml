// Вынесено из shell.qml (Р-80).
import QtQuick
import QtQuick.Layouts

// A timer or an alarm going off. One thing to read (what and when), one thing to press (Выключить):
// Live Activities › Offering interactivity — "prefer limiting it to a single element".
View {
    id: av
    readonly property var a: JD.alarm || ({})
    readonly property bool isAlarm: av.a.kind === "alarm"
    readonly property color tint: JD.accentOrange
    implicitWidth: Math.min(620, Math.max(430, alarmRow.implicitWidth + 40))
    implicitHeight: 96
    RowLayout {
        id: alarmRow
        anchors { fill: parent; leftMargin: 18; rightMargin: 14; topMargin: 16; bottomMargin: 16 }
        spacing: 14
        Item {
            implicitWidth: 52; implicitHeight: 52
            Rectangle {   // a ring that breathes while it rings; the label says the same thing in words
                anchors.centerIn: parent
                width: 52; height: 52; radius: 26
                color: Qt.rgba(av.tint.r, av.tint.g, av.tint.b, 0.22)
                SequentialAnimation on scale {
                    running: JD.animOn && JD.mode === "alarm"
                    loops: Animation.Infinite
                    NumberAnimation { to: 1.12; duration: 520; easing.type: Easing.OutCubic }
                    NumberAnimation { to: 1.0; duration: 520; easing.type: Easing.InCubic }
                }
            }
            Icon { anchors.centerIn: parent; name: av.isAlarm ? "bell-ring" : "timer"; implicitSize: 24; tint: av.tint }
        }
        ColumnLayout {
            spacing: 2
            Layout.fillWidth: true
            SectionLabel { text: (av.isAlarm ? JD.tr("БУДИЛЬНИК") : JD.tr("ТАЙМЕР")); color: av.tint }
            Label1 {
                text: av.a.label || (av.isAlarm ? av.a.time || "" : JD.tr("Время вышло"))
                font.pixelSize: 20; font.weight: Font.DemiBold
                Layout.fillWidth: true
            }
            Label2 { visible: !!av.a.label && !!av.a.time; text: av.a.time || ""; font.pixelSize: 12 }
        }
        PillButton {
            visible: av.isAlarm
            label: JD.tr("+5 минут")
            onClicked: { JD.send({ cmd: "reminder_set", kind: "alarm", seconds: 300, label: av.a.label || "" }); JD.dismissAlarm(av.a.id) }
        }
        PillButton {
            label: JD.tr("Выключить")
            tint: av.tint
            labelColor: "black"
            onClicked: JD.dismissAlarm(av.a.id)
        }
    }
}
