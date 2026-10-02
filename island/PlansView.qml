// Планы: то, что отложено на потом, по пунктам и по порядку.
//
// Почему страница, а не разговор. Планы можно спросить голосом — и ассистент их перечислит, — но
// услышанный список живёт ровно до конца фразы: уже на четвёртом пункте первый забыт. Список
// существует для того, чтобы на него **смотреть**, и это единственное, чего разговором не заменишь.
//
// Чего здесь нарочно нет: своей жизни. Планы лежат в Obsidian обычным markdown, и человек правит их
// руками в чём угодно. Островок их показывает и отмечает сделанными — больше ничего. Второй список
// того же самого разошёлся бы с первым в тот же день.
import QtQuick
import QtQuick.Layouts

Item {
    id: pv

    readonly property var all: JD.plans || []
    readonly property var open: all.filter(p => p && !p.done)
    readonly property var done: all.filter(p => p && p.done)

    ColumnLayout {
        anchors.fill: parent
        spacing: 12

        // ───────────── добавить ─────────────
        //
        // Поле первым: страницу планов открывают, чтобы либо посмотреть, либо дописать, и второе
        // не должно требовать поисков.
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 38
            radius: 19
            color: field.activeFocus ? JD.fill2 : JD.fill1
            border.width: 1
            border.color: field.activeFocus ? Qt.rgba(1, 1, 1, 0.22) : "transparent"
            Behavior on color { enabled: JD.animOn; ColorAnimation { duration: 140 } }

            RowLayout {
                anchors { fill: parent; leftMargin: 14; rightMargin: 12 }
                spacing: 9
                Icon { name: "plus"; implicitSize: 15; tint: JD.text3 }
                TextInput {
                    id: field
                    Layout.fillWidth: true
                    color: JD.text1
                    font.family: JD.fontFamily
                    font.pixelSize: 14
                    selectByMouse: true
                    clip: true
                    onAccepted: { JD.planAdd(text); text = "" }
                    Text {
                        anchors.fill: parent
                        verticalAlignment: Text.AlignVCenter
                        visible: !field.text
                        font: field.font
                        color: JD.text3
                        text: JD.tr("Что отложить на потом")
                    }
                }
            }
        }

        // ───────────── список ─────────────
        Flickable {
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentHeight: rows.implicitHeight
            clip: true
            interactive: contentHeight > height
            boundsBehavior: Flickable.StopAtBounds

            ColumnLayout {
                id: rows
                width: parent.width
                spacing: 6

                // Пусто — так и сказано словами. Пустой список без объяснения читается как поломка.
                Item {
                    Layout.fillWidth: true
                    Layout.preferredHeight: pv.all.length ? 0 : 120
                    visible: pv.all.length === 0
                    Column {
                        anchors.centerIn: parent
                        spacing: 8
                        Icon {
                            anchors.horizontalCenter: parent.horizontalCenter
                            name: "clipboard"; implicitSize: 26; tint: JD.text3
                        }
                        Label2 {
                            anchors.horizontalCenter: parent.horizontalCenter
                            color: JD.text3
                            text: JD.tr("Планов пока нет")
                        }
                    }
                }

                Repeater {
                    model: pv.open.concat(pv.done)
                    delegate: Rectangle {
                        id: row
                        required property var modelData
                        readonly property bool finished: !!modelData.done
                        Layout.fillWidth: true
                        implicitHeight: Math.max(40, line.implicitHeight + 18)
                        radius: 12
                        color: rowHover.hovered ? JD.fill1 : Qt.rgba(1, 1, 1, 0.04)
                        Behavior on color { enabled: JD.animOn; ColorAnimation { duration: 120 } }
                        HoverHandler { id: rowHover }

                        RowLayout {
                            anchors { fill: parent; leftMargin: 12; rightMargin: 12 }
                            spacing: 11

                            // Галочка, а не крестик: отметить сделанным — это награда, и выглядеть
                            // она должна соответственно.
                            Rectangle {
                                Layout.alignment: Qt.AlignVCenter
                                implicitWidth: 21
                                implicitHeight: 21
                                radius: 7
                                color: row.finished ? JD.accentGreen : "transparent"
                                border.width: row.finished ? 0 : 1.5
                                border.color: markHover.hovered ? JD.accentGreen : JD.text3
                                Behavior on color { enabled: JD.animOn; ColorAnimation { duration: 140 } }
                                Icon {
                                    anchors.centerIn: parent
                                    visible: row.finished
                                    name: "check"
                                    implicitSize: 13
                                    tint: "#0b0b0f"
                                }
                                HoverHandler { id: markHover; cursorShape: Qt.PointingHandCursor }
                                TapHandler {
                                    enabled: !row.finished
                                    gesturePolicy: TapHandler.ReleaseWithinBounds
                                    onTapped: JD.planDone(row.modelData.n)
                                }
                            }

                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 2
                                Label1 {
                                    id: line
                                    Layout.fillWidth: true
                                    wrapMode: Text.Wrap
                                    maximumLineCount: 3
                                    color: row.finished ? JD.text3 : JD.text1
                                    font.strikeout: row.finished
                                    text: (row.modelData.n ? row.modelData.n + ". " : "") + (row.modelData.text || "")
                                }
                                Label2 {
                                    Layout.fillWidth: true
                                    visible: !!text
                                    font.pixelSize: 11
                                    color: JD.text3
                                    text: [row.modelData.day || "", row.modelData.note || ""].filter(s => !!s).join("  ·  ")
                                }
                            }
                        }
                    }
                }
            }
        }

        // Планы живут файлом, и это стоит показать: человек должен знать, где они на самом деле,
        // чтобы не искать их внутри ассистента.
        RowLayout {
            Layout.fillWidth: true
            spacing: 10
            Label2 {
                Layout.fillWidth: true
                color: JD.text3
                font.pixelSize: 11
                text: pv.open.length
                      ? JD.tr("Открыто: ") + pv.open.length + (pv.done.length ? JD.tr("  ·  сделано: ") + pv.done.length : "")
                      : pv.done.length ? JD.tr("Всё сделано") : ""
            }
            PillButton {
                label: JD.tr("Открыть в Obsidian")
                onClicked: JD.send({ cmd: "plan_open" })
            }
        }
    }
}
