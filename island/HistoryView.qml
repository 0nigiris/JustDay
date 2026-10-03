// История разговоров: что человек сказал, что ответили и когда.
//
// Зачем страница. Всё сказанное и так пишется в журнал, но журнал человеку не виден: он наговорил
// длинную задачу и не нашёл её нигде. Поиск по словам — общий, в шапке панели (`JD.toolsQuery`).
//
// Чего здесь нет нарочно: писем и паролей. Это отсекает демон (`history.py`), не страница.
import QtQuick
import QtQuick.Layouts

Item {
    id: hv

    readonly property var all: JD.talk || []

    ColumnLayout {
        anchors.fill: parent
        spacing: 8

        Label2 {
            Layout.fillWidth: true
            color: JD.text3
            text: hv.all.length === 0
                  ? (JD.toolsQuery ? JD.tr("Ничего не нашлось") : JD.tr("Пока ничего не говорили"))
                  : JD.tr("Без писем и паролей · можно выделить и скопировать")
        }

        ListView {
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: 8
            model: hv.all
            boundsBehavior: Flickable.StopAtBounds
            delegate: Rectangle {
                id: row
                required property var modelData
                readonly property bool mine: modelData.who === "you"
                width: ListView.view.width
                implicitHeight: col.implicitHeight + 20
                radius: 14
                color: mine ? Qt.rgba(JD.accentBlue.r, JD.accentBlue.g, JD.accentBlue.b, 0.12)
                            : Qt.rgba(1, 1, 1, 0.05)

                ColumnLayout {
                    id: col
                    anchors { left: parent.left; right: parent.right; top: parent.top
                              leftMargin: 14; rightMargin: 14; topMargin: 10 }
                    spacing: 4
                    Label2 {
                        font.pixelSize: 11
                        color: JD.text3
                        font.features: ({ "tnum": 1 })
                        // 2026-10-03T10:32:00 → «10-03 10:32»: год в истории за недели не нужен.
                        text: (row.mine ? JD.tr("Вы") : JD.tr("Джарвис")) + " · "
                              + String(row.modelData.ts).slice(5, 10) + " " + String(row.modelData.ts).slice(11, 16)
                    }
                    SelectableText {
                        Layout.fillWidth: true
                        font.pixelSize: 13
                        text: row.modelData.text
                    }
                }
            }
        }
    }
}
