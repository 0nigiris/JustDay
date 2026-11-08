// Галерея виджетов островка: что стоит на полоске и что можно добавить.
//
// Зачем отдельная страница, а не кнопки на самой полоске: на полоске места мало, и «+ Погода»
// рядом с дрожащими виджетами превращало режим правки в кашу.
import QtQuick
import QtQuick.Layouts

Item {
    id: wv
    readonly property var all: [
        { id: "assistant", name: "Ассистент", icon: "sparkles", hint: "Шар или существо: слушает ли он и занят ли" },
        { id: "cat", name: "Кошка", image: "icons/cat/run0.svg", hint: "Живёт на полоске, сидит на окнах" },
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
    // Включённые идут первыми и в том порядке, в каком стоят на полоске; выключенные — после.
    // Порядок меняют, таская строку за ручку (Р3-13): стрелки ↑↓ двигали на одну позицию за нажатие,
    // и перенести виджет с конца в начало было десятком щелчков.
    readonly property var ordered: {
        const every = all.concat(customs)
        const byId = {}
        every.forEach(w => byId[w.id] = w)
        const on = JD.peekLayout.filter(id => byId[id]).map(id => byId[id])
        return on.concat(every.filter(w => JD.peekLayout.indexOf(w.id) < 0))
    }
    readonly property int rowStep: 48 + 6   // высота строки и промежуток — шаг перетаскивания
    property string dragId: ""
    property real dragDy: 0
    function move(id, step) {
        const l = JD.peekLayout.slice()
        const i = l.indexOf(id), j = Math.max(0, Math.min(l.length - 1, i + step))
        if (i < 0 || j === i) return
        l.splice(j, 0, l.splice(i, 1)[0])
        JD.setConfig("island.peek", l)
    }
    function has(id) { return JD.peekLayout.indexOf(id) >= 0 }
    function toggle(id) {
        JD.setConfig("island.peek", has(id) ? JD.peekLayout.filter(k => k !== id) : JD.peekLayout.concat([id]))
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 8
        Label2 { Layout.fillWidth: true; color: JD.text2; text: JD.tr("Нажатие добавляет или убирает, ручка ⠿ меняет порядок.") }
        Flickable {
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentHeight: col.implicitHeight
            clip: true
            interactive: !wv.dragId   // иначе список уезжал вместе с перетаскиваемой строкой
            Column {
                id: col
                width: parent.width
                spacing: 6
                Repeater {
                    model: wv.ordered
                    delegate: Rectangle {
                        id: rowItem
                        required property var modelData
                        readonly property bool on: wv.has(modelData.id)
                        width: col.width; height: 48; radius: 14
                        z: wv.dragId === rowItem.modelData.id ? 10 : 1
                        transform: Translate { y: wv.dragId === rowItem.modelData.id ? wv.dragDy : 0 }
                        color: rowHover.hovered || wv.dragId === rowItem.modelData.id ? JD.fill2 : JD.fill1
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
                                visible: (!!modelData.icon || String(modelData.id).startsWith("custom:")) && !modelData.image
                                name: modelData.icon || "file-text"
                                implicitSize: 16
                            }
                            Image {
                                anchors.centerIn: parent
                                visible: !!modelData.image
                                source: modelData.image ? Qt.resolvedUrl(modelData.image) : ""
                                sourceSize.height: 40
                                height: 20; fillMode: Image.PreserveAspectFit
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
                            id: grip
                            visible: on
                            anchors.right: sw.left; anchors.rightMargin: 12
                            anchors.verticalCenter: parent.verticalCenter
                            width: 28; height: 28; radius: 14
                            color: gh.hovered || wv.dragId === rowItem.modelData.id ? JD.fill2 : "transparent"
                            Icon { anchors.centerIn: parent; name: "grip-vertical"; implicitSize: 16 }
                            HoverHandler { id: gh; cursorShape: wv.dragId ? Qt.ClosedHandCursor : Qt.OpenHandCursor }
                            DragHandler {
                                target: null
                                xAxis.enabled: false
                                onActiveChanged: {
                                    if (active) { wv.dragId = rowItem.modelData.id; wv.dragDy = 0; return }
                                    wv.move(wv.dragId, Math.round(wv.dragDy / wv.rowStep))
                                    wv.dragId = ""; wv.dragDy = 0
                                }
                                onTranslationChanged: if (active) wv.dragDy = translation.y
                            }
                        }
                        Rectangle {
                            id: sw
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
