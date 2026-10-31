// Галерея виджетов островка: что стоит на полоске и что можно добавить.
//
// Зачем отдельная страница, а не кнопки на самой полоске: на полоске места мало, и «+ Погода»
// рядом с дрожащими виджетами превращало режим правки в кашу. Порядок здесь не меняется — его
// двигают перетаскиванием на самой полоске; тут только «есть / нет».
import QtQuick
import QtQuick.Layouts

Item {
    id: wv
    readonly property var all: [
        { id: "assistant", name: "Ассистент", hint: "Шар или существо: слушает ли он и занят ли" },
        { id: "cat", name: "Кошка", hint: "Живёт на полоске, сидит на окнах" },
        { id: "clock", name: "Часы", hint: "Время" },
        { id: "date", name: "Дата", hint: "День недели и число" },
        { id: "player", name: "Плеер", hint: "Что играет, только пока играет" },
        { id: "event", name: "Событие", hint: "Ближайшая встреча, работа Клода, задача" },
        { id: "timer", name: "Таймер", hint: "Виден, пока идёт" },
        { id: "muted", name: "Без звука", hint: "Метка, когда звук выключен" },
        { id: "focus", name: "Фокус", hint: "Окно тишины по расписанию" },
        { id: "weather", name: "Погода", hint: "Температура за окном" },
    ]
    // Свои виджеты из island.custom («имя:путь») идут в галерее после встроенных.
    readonly property var customs: (Array.isArray(JD.island.custom) ? JD.island.custom : [])
        .map(e => String(e).split(":")[0].trim()).filter(n => n)
        .map(n => ({ id: "custom:" + n, name: n, hint: JD.tr("Первая строка файла, обновляется раз в 5 секунд") }))
    function has(id) { return JD.peekLayout.indexOf(id) >= 0 }
    function toggle(id) {
        JD.setConfig("island.peek", has(id) ? JD.peekLayout.filter(k => k !== id) : JD.peekLayout.concat([id]))
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 8
        Label2 { color: JD.text2; text: JD.tr("Нажмите, чтобы добавить или убрать. Порядок меняется перетаскиванием на островке.") }
        Flickable {
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentHeight: col.implicitHeight
            clip: true
            Column {
                id: col
                width: parent.width
                spacing: 6
                Repeater {
                    model: wv.all.concat(wv.customs)
                    delegate: Rectangle {
                        required property var modelData
                        readonly property bool on: wv.has(modelData.id)
                        width: col.width; height: 48; radius: 14
                        color: rowHover.hovered ? JD.fill2 : JD.fill1
                        RowLayout {
                            anchors.fill: parent; anchors.leftMargin: 14; anchors.rightMargin: 14
                            spacing: 10
                            ColumnLayout {
                                Layout.fillWidth: true; spacing: 0
                                Label1 { text: JD.tr(modelData.name) }
                                Label2 { color: JD.text2; font.pixelSize: 12; text: JD.tr(modelData.hint) }
                            }
                            Rectangle {
                                width: 40; height: 24; radius: 12
                                color: on ? JD.accentBlue : JD.fill2
                                Rectangle {
                                    width: 20; height: 20; radius: 10; y: 2; color: "white"
                                    x: on ? 18 : 2
                                    Behavior on x { enabled: JD.animOn; NumberAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
                                }
                            }
                        }
                        HoverHandler { id: rowHover; cursorShape: Qt.PointingHandCursor }
                        TapHandler { gesturePolicy: TapHandler.ReleaseWithinBounds; onTapped: wv.toggle(modelData.id) }
                    }
                }
            }
        }
    }
}
