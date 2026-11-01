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
        { id: "assistant", name: "Ассистент", icon: "sparkles", hint: "Шар или существо: слушает ли он и занят ли" },
        { id: "cat", name: "Кошка", icon: "cat", hint: "Живёт на полоске, сидит на окнах" },
        { id: "clock", name: "Часы", sample: "14:14", hint: "Время" },
        { id: "date", name: "Дата", sample: "1 нояб.", hint: "День недели и число" },
        { id: "player", name: "Плеер", icon: "music", hint: "Что играет, только пока играет" },
        { id: "event", name: "Событие", icon: "calendar-clock", hint: "Ближайшая встреча, работа Клода, задача" },
        { id: "timer", name: "Таймер", icon: "timer", hint: "Виден, пока идёт" },
        { id: "muted", name: "Без звука", icon: "volume-x", hint: "Метка, когда звук выключен" },
        { id: "focus", name: "Фокус", icon: "moon", hint: "Окно тишины по расписанию" },
        { id: "weather", name: "Погода", sample: "+23°", hint: "Температура за окном" },
        { id: "cpu", name: "Процессор", sample: "12%", hint: "Нагрузка в процентах" },
        { id: "ram", name: "Память", sample: "34%", hint: "Занято в процентах" },
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
                        // Без RowLayout: переключатель там уезжал вслед за длиной текста.
                        // Крошечный предпросмотр: значок или то, что виджет показывает на полоске.
                        // Не настоящая отрисовка (она зависит от данных), а намёк, что это за штука.
                        Rectangle {
                            id: thumb
                            anchors.left: parent.left; anchors.leftMargin: 10
                            anchors.verticalCenter: parent.verticalCenter
                            width: 54; height: 30; radius: 15; color: "black"
                            border.width: 1; border.color: JD.fill2
                            opacity: on ? 1 : 0.55
                            Icon {
                                anchors.centerIn: parent
                                visible: !!modelData.icon || String(modelData.id).startsWith("custom:")
                                name: modelData.icon || "file-text"
                                implicitSize: 16
                            }
                            Label2 {
                                anchors.centerIn: parent
                                visible: !!modelData.sample
                                color: JD.text1; font.pixelSize: 12
                                text: modelData.sample || ""
                            }
                        }
                        Column {
                            anchors.left: thumb.right; anchors.leftMargin: 12
                            anchors.verticalCenter: parent.verticalCenter
                            Label1 { text: JD.tr(modelData.name) }
                            Label2 { color: JD.text2; font.pixelSize: 12; text: JD.tr(modelData.hint) }
                        }
                        Rectangle {
                            anchors.right: parent.right; anchors.rightMargin: 14
                            anchors.verticalCenter: parent.verticalCenter
                            width: 40; height: 24; radius: 12
                            color: on ? JD.accentBlue : JD.fill2
                            Rectangle {
                                width: 20; height: 20; radius: 10; y: 2; color: "white"
                                x: on ? 18 : 2
                                Behavior on x { enabled: JD.animOn; NumberAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
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
