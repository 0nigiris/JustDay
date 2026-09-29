// Панель инструментов островка: эмодзи, буфер обмена, нагрузка машины.
//
// Зачем это здесь, а не тремя программами. В оболочках для Hyprland и Niri каждая из этих вещей —
// отдельная программа со своим окном, своими цветами и своей клавишей. Здесь они в островке: одно
// окно, одни клавиши, один вид. Искать умеет демон — он же отвечает и ассистенту, поэтому «вставь
// эмодзи с котиком» и сетка на экране находят одно и то же.
//
// Вид только рисует. Ни поиска, ни разбора истории, ни чтения /proc тут нет: всё это приходит
// готовым в JD.toolsItems и JD.load. Правило то же, что у телефонной половины, и по той же причине:
// два поиска по одному набору расходятся в тот же день, когда их становится два.
import QtQuick
import QtQuick.Layouts

// Корень — Item, а не View: показом и растворением заведует держатель в shell.qml, а у View своя
// прозрачность, завязанная на его собственный `shown`. Вложенный View остался бы невидимым.
Item {
    id: tv
    implicitWidth: 860
    implicitHeight: 560

    readonly property string page: JD.toolsPage
    readonly property var items: JD.toolsItems || []
    readonly property var load: JD.load

    // Поле поиска нужно двум страницам из трёх: у нагрузки искать нечего.
    readonly property bool searchable: page === "apps" || page === "emoji" || page === "clip"
    // Ничего не нашлось, а что-то напечатано — предложим спросить ассистента. Ради этого лаунчер
    // и живёт в островке: поле не обязано быть командой.
    readonly property bool askInstead: page === "apps" && JD.toolsQuery.trim() !== "" && items.length === 0

    // Байты — байтами: скопированная строка в 25 знаков не «1 КБ».
    function fmtSize(bytes) {
        if (bytes < 1024) return bytes + " Б"
        if (bytes < 1024 * 1024) return Math.round(bytes / 1024) + " КБ"
        return (bytes / 1024 / 1024).toFixed(1) + " МБ"
    }
    function ago(at) {
        const s = Math.max(0, JD.tick - at)
        if (s < 60) return Math.round(s) + " с"
        if (s < 3600) return Math.round(s / 60) + " мин"
        if (s < 86400) return Math.round(s / 3600) + " ч"
        return Math.round(s / 86400) + " дн"
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 18
        spacing: 12

        // ───────────── заголовок: вкладки, поиск, закрыть ─────────────
        RowLayout {
            Layout.fillWidth: true
            spacing: 10

            Repeater {
                model: [
                    { id: "apps", name: "Программы", icon: "layout-grid" },
                    { id: "emoji", name: "Эмодзи", icon: "smile" },
                    { id: "clip", name: "Буфер", icon: "clipboard" },
                    { id: "load", name: "Машина", icon: "activity" },
                ]
                delegate: Rectangle {
                    required property var modelData
                    readonly property bool on: tv.page === modelData.id
                    implicitWidth: tab.implicitWidth + 30
                    implicitHeight: 34
                    radius: 17
                    color: on ? JD.accentBlue : (tabHover.hovered ? JD.fill2 : JD.fill1)
                    Behavior on color { ColorAnimation { duration: 140 } }
                    RowLayout {
                        id: tab
                        anchors.centerIn: parent
                        spacing: 7
                        Icon { name: modelData.icon; implicitSize: 15; tint: JD.text1 }
                        Label1 { text: modelData.name }
                    }
                    HoverHandler { id: tabHover; cursorShape: Qt.PointingHandCursor }
                    TapHandler {
                        gesturePolicy: TapHandler.ReleaseWithinBounds
                        onTapped: JD.setToolsPage(modelData.id)
                    }
                }
            }

            Item { Layout.fillWidth: true }

            // Поиск. Фокус берёт сразу: открыли панель — можно печатать, как в Spotlight.
            Rectangle {
                visible: tv.searchable
                Layout.preferredWidth: 260
                implicitHeight: 34
                radius: 17
                color: JD.fill1
                border.width: field.activeFocus ? 1 : 0
                border.color: JD.accentBlue
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 12
                    anchors.rightMargin: 10
                    spacing: 8
                    Icon { name: "search"; implicitSize: 14; tint: JD.text3 }
                    TextInput {
                        id: field
                        Layout.fillWidth: true
                        font.family: JD.fontFamily
                        font.pixelSize: 13
                        color: JD.text1
                        selectByMouse: true
                        selectionColor: JD.accentBlue
                        clip: true
                        text: JD.toolsQuery
                        onTextChanged: if (text !== JD.toolsQuery) { JD.toolsQuery = text; searchDelay.restart() }
                        Keys.onPressed: (e) => {
                            if (e.key === Qt.Key_Escape) { JD.closeTools(); e.accepted = true; return }
                            if (e.key === Qt.Key_Down || e.key === Qt.Key_Up) {
                                const step = e.key === Qt.Key_Down ? 1 : -1
                                JD.toolsPick = Math.max(0, Math.min(tv.items.length - 1, JD.toolsPick + step))
                                e.accepted = true
                                return
                            }
                            if (e.key !== Qt.Key_Return && e.key !== Qt.Key_Enter) return
                            e.accepted = true
                            // Enter берёт выбранное; ничего не выбирали — первое найденное.
                            if (tv.askInstead) { JD.askFromLauncher(JD.toolsQuery); return }
                            const item = tv.items[JD.toolsPick] || tv.items[0]
                            if (!item) return
                            if (tv.page === "apps") JD.runApp(item)
                            else if (tv.page === "emoji") JD.useEmoji(item.c)
                            else JD.useClip(item.id)
                        }
                        Text {
                            anchors.fill: parent
                            verticalAlignment: Text.AlignVCenter
                            visible: !field.text
                            font: field.font
                            color: JD.text3
                            text: tv.page === "apps" ? "программа, игра, окно — или просьба…"
                            : tv.page === "emoji" ? "кот, сердце, флаг…" : "искать в истории…"
                        }
                    }
                }
            }

            IconButton { icon: "x"; size: 30; onClicked: JD.closeTools() }
        }

        // Поиск не на каждую букву: демон читает историю с диска, и дёргать его на «к», «ко», «кот»
        // значит три чтения вместо одного.
        Timer { id: searchDelay; interval: 120; onTriggered: JD.refreshTools() }

        // ───────────── эмодзи ─────────────
        RowLayout {
            visible: tv.page === "emoji"
            Layout.fillWidth: true
            spacing: 7
            Repeater {
                model: [""].concat(JD.emojiGroups || [])
                delegate: Rectangle {
                    required property var modelData
                    readonly property bool on: JD.emojiGroup === modelData
                    implicitWidth: chip.implicitWidth + 20
                    implicitHeight: 26
                    radius: 13
                    color: on ? JD.fill2 : "transparent"
                    border.width: on ? 0 : 1
                    border.color: JD.fill1
                    Label2 {
                        id: chip
                        anchors.centerIn: parent
                        text: modelData || "Все"
                        color: on ? JD.text1 : JD.text2
                    }
                    HoverHandler { cursorShape: Qt.PointingHandCursor }
                    TapHandler {
                        gesturePolicy: TapHandler.ReleaseWithinBounds
                        onTapped: { JD.emojiGroup = on ? "" : modelData; JD.refreshTools() }
                    }
                }
            }
            Item { Layout.fillWidth: true }
            Label2 {
                text: JD.toolsQuery || JD.emojiGroup ? tv.items.length + " шт." : "недавние — первыми"
                color: JD.text3
            }
        }

        GridView {
            id: grid
            visible: tv.page === "emoji"
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            cellWidth: 56
            cellHeight: 56
            model: tv.page === "emoji" ? tv.items : []
            delegate: Item {
                required property var modelData
                width: grid.cellWidth
                height: grid.cellHeight
                Rectangle {
                    anchors.centerIn: parent
                    width: 48
                    height: 48
                    radius: 12
                    color: cellHover.hovered ? JD.fill2 : "transparent"
                    scale: cellTap.pressed ? 0.9 : 1
                    Behavior on scale { NumberAnimation { duration: 110 } }
                    Text {
                        anchors.centerIn: parent
                        // Эмодзи рисует шрифт эмодзи, а не Inter: у Inter их нет, и вместо кота
                        // получался бы пустой прямоугольник.
                        font.family: "Noto Color Emoji"
                        font.pixelSize: 27
                        text: modelData.c
                    }
                    HoverHandler { id: cellHover; cursorShape: Qt.PointingHandCursor }
                    TapHandler {
                        id: cellTap
                        gesturePolicy: TapHandler.ReleaseWithinBounds
                        onTapped: JD.useEmoji(modelData.c)
                    }
                }
            }
        }

        // Название того, на что смотрит курсор: подписывать все 1900 клеток незачем, а знать, что
        // это за символ, иногда нужно.
        Label2 {
            visible: tv.page === "emoji"
            Layout.fillWidth: true
            horizontalAlignment: Text.AlignHCenter
            color: JD.text3
            text: {
                const item = tv.items[grid.currentIndex] || tv.items[0]
                return item ? item.c + "   " + item.n : ""
            }
        }

        // ───────────── программы, игры, окна ─────────────
        ListView {
            id: appList
            visible: tv.page === "apps" && !tv.askInstead
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: 2
            model: tv.page === "apps" ? tv.items : []
            currentIndex: JD.toolsPick
            highlightMoveDuration: 90
            // Выбранное стрелками не должно уезжать за край списка.
            onCurrentIndexChanged: positionViewAtIndex(currentIndex, ListView.Contain)
            delegate: Rectangle {
                required property var modelData
                required property int index
                width: ListView.view.width
                implicitHeight: 44
                radius: 10
                color: index === JD.toolsPick ? JD.fill2 : (appHover.hovered ? JD.fill1 : "transparent")
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 12
                    anchors.rightMargin: 12
                    spacing: 11
                    Icon { name: modelData.icon; fallback: "application-x-executable"; implicitSize: 22 }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 0
                        Label1 { Layout.fillWidth: true; text: modelData.name }
                        Label2 { visible: !!modelData.sub; color: JD.text3; text: modelData.sub }
                    }
                    Label2 {
                        color: JD.text3
                        text: ({ app: "", game: "игра", window: "открыто" })[modelData.kind] || ""
                    }
                }
                HoverHandler { id: appHover; cursorShape: Qt.PointingHandCursor }
                TapHandler {
                    gesturePolicy: TapHandler.ReleaseWithinBounds
                    onTapped: JD.runApp(modelData)
                }
            }
        }

        // Ничего не нашлось — не тупик, а вопрос ассистенту.
        Item {
            visible: tv.askInstead
            Layout.fillWidth: true
            Layout.fillHeight: true
            ColumnLayout {
                anchors.centerIn: parent
                width: Math.min(parent.width - 40, 520)
                spacing: 12
                Icon {
                    Layout.alignment: Qt.AlignHCenter
                    name: "sparkles"
                    implicitSize: 26
                    tint: JD.accentBlue
                }
                Label1 {
                    Layout.fillWidth: true
                    horizontalAlignment: Text.AlignHCenter
                    wrapMode: Text.Wrap
                    elide: Text.ElideNone
                    text: "Такой программы нет. Спросить " + JD.assistantName + "?"
                }
                Label2 {
                    Layout.fillWidth: true
                    horizontalAlignment: Text.AlignHCenter
                    color: JD.text3
                    wrapMode: Text.Wrap
                    elide: Text.ElideNone
                    text: "«" + JD.toolsQuery + "»"
                }
                PillButton {
                    Layout.alignment: Qt.AlignHCenter
                    label: "Спросить  ⏎"
                    tint: JD.accentBlue
                    onClicked: JD.askFromLauncher(JD.toolsQuery)
                }
            }
        }

        // ───────────── буфер обмена ─────────────
        ListView {
            visible: tv.page === "clip"
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: 4
            model: tv.page === "clip" ? tv.items : []
            delegate: Rectangle {
                required property var modelData
                width: ListView.view.width
                implicitHeight: 46
                radius: 10
                color: rowHover.hovered ? JD.fill1 : "transparent"
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 12
                    anchors.rightMargin: 8
                    spacing: 10
                    Icon {
                        name: modelData.kind === "image" ? "image" : "file-text"
                        implicitSize: 15
                        tint: JD.text3
                    }
                    ColumnLayout {
                        Layout.fillWidth: true
                        spacing: 1
                        Label1 { Layout.fillWidth: true; text: modelData.preview }
                        Label2 {
                            color: JD.text3
                            text: tv.ago(modelData.at)
                                  + (modelData.lines > 1 ? " · " + modelData.lines + " строк" : "")
                                  + (modelData.kind === "image" ? "" : " · " + tv.fmtSize(modelData.size))
                        }
                    }
                    IconButton {
                        icon: "trash-2"
                        size: 26
                        opacity: rowHover.hovered ? 1 : 0
                        Behavior on opacity { NumberAnimation { duration: 120 } }
                        onClicked: JD.forgetClip(modelData.id)
                    }
                }
                HoverHandler { id: rowHover; cursorShape: Qt.PointingHandCursor }
                TapHandler {
                    gesturePolicy: TapHandler.ReleaseWithinBounds
                    onTapped: JD.useClip(modelData.id)
                }
            }
        }

        RowLayout {
            visible: tv.page === "clip"
            Layout.fillWidth: true
            spacing: 10
            Label2 {
                Layout.fillWidth: true
                color: JD.text3
                // Главное про эту историю: пароли в неё не попадают. Говорим это прямо в панели, а
                // не только в руководстве — иначе первый вопрос к ней будет именно этот.
                text: JD.clipPaused ? "на паузе: новое не запоминается"
                     : JD.clipSkipped ? "пароли и ключи сюда не попадают — пропущено: " + JD.clipSkipped
                     : "пароли и ключи сюда не попадают"
            }
            PillButton {
                label: JD.clipPaused ? "Продолжить" : "Пауза"
                onClicked: { JD.pauseClip(!JD.clipPaused); JD.refreshTools() }
            }
            PillButton {
                label: "Забыть всё"
                tint: JD.fill1
                labelColor: JD.accentRed
                onClicked: { JD.send({ cmd: "clip_wipe" }); JD.refreshTools() }
            }
        }

        // ───────────── нагрузка машины ─────────────
        Flickable {
            visible: tv.page === "load"
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            contentHeight: loadCol.implicitHeight
            interactive: contentHeight > height
            boundsBehavior: Flickable.StopAtBounds

            ColumnLayout {
                id: loadCol
                width: parent.width
                spacing: 10

                // Три главных числа с графиком за минуту: процессор, память, видеокарта.
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 10
                    Repeater {
                        model: [
                            { key: "cpu", name: "Процессор", icon: "cpu", tint: JD.accentBlue },
                            { key: "mem", name: "Память", icon: "memory-stick", tint: JD.accentGreen },
                            { key: "gpu", name: "Видеокарта", icon: "monitor", tint: JD.accentPurple },
                        ]
                        delegate: Rectangle {
                            required property var modelData
                            readonly property var history: (JD.loadHistory || ({}))[modelData.key] || []
                            readonly property real now: history.length ? history[history.length - 1] : 0
                            readonly property bool known: modelData.key !== "gpu" || !!(tv.load && tv.load.gpu)
                            Layout.fillWidth: true
                            implicitHeight: 104
                            radius: 14
                            color: JD.fill1
                            opacity: known ? 1 : 0.45

                            ColumnLayout {
                                anchors.fill: parent
                                anchors.margins: 12
                                spacing: 2
                                RowLayout {
                                    spacing: 7
                                    Icon { name: modelData.icon; implicitSize: 14; tint: modelData.tint }
                                    Label2 { text: modelData.name }
                                    Item { Layout.fillWidth: true }
                                    Label1 {
                                        text: known ? Math.round(now) + "%" : "нет"
                                        color: modelData.tint
                                        font.pixelSize: 15
                                    }
                                }
                                Label2 {
                                    Layout.fillWidth: true
                                    color: JD.text3
                                    font.pixelSize: 11
                                    text: {
                                        if (!tv.load) return ""
                                        if (modelData.key === "cpu")
                                            return (tv.load.cpu.count || 0) + " ядер · средняя "
                                                   + (tv.load.load || [0])[0].toFixed(2)
                                        if (modelData.key === "mem")
                                            return (tv.load.memory.used / 1024).toFixed(1) + " из "
                                                   + (tv.load.memory.total / 1024).toFixed(0) + " ГБ"
                                        return tv.load.gpu ? tv.load.gpu.name : "не NVIDIA или нет nvidia-smi"
                                    }
                                }
                                // График за минуту. Рисуем сами: график — это ломаная по 60 числам,
                                // и тянуть ради неё Charts значит тянуть половину QtQuick.
                                Canvas {
                                    id: spark
                                    Layout.fillWidth: true
                                    Layout.fillHeight: true
                                    readonly property var data: history
                                    onDataChanged: requestPaint()
                                    onPaint: {
                                        const ctx = getContext("2d")
                                        ctx.reset()
                                        if (data.length < 2) return
                                        const stepX = width / Math.max(1, data.length - 1)
                                        const y = (v) => height - Math.max(0, Math.min(100, v)) / 100 * height
                                        ctx.beginPath()
                                        ctx.moveTo(0, y(data[0]))
                                        for (let i = 1; i < data.length; i++) ctx.lineTo(i * stepX, y(data[i]))
                                        ctx.strokeStyle = modelData.tint
                                        ctx.lineWidth = 1.6
                                        ctx.stroke()
                                        // Заливка под ломаной: она и делает из линии «сколько занято».
                                        ctx.lineTo(width, height)
                                        ctx.lineTo(0, height)
                                        ctx.closePath()
                                        ctx.fillStyle = Qt.rgba(modelData.tint.r, modelData.tint.g,
                                                                modelData.tint.b, 0.16)
                                        ctx.fill()
                                    }
                                }
                            }
                        }
                    }
                }

                // Строка мелочей: температура, сеть, диск, время работы.
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    Repeater {
                        model: {
                            if (!tv.load) return []
                            const out = []
                            if (tv.load.hot)
                                out.push({ icon: "thermometer", text: Math.round(tv.load.hot.c) + "°",
                                           sub: tv.load.hot.label })
                            out.push({ icon: "network",
                                       text: "↓" + Math.round(tv.load.net.rx_kb) + " ↑" + Math.round(tv.load.net.tx_kb),
                                       sub: "КБ/с" })
                            out.push({ icon: "hard-drive",
                                       text: "↓" + tv.load.io.read_mb.toFixed(1) + " ↑" + tv.load.io.write_mb.toFixed(1),
                                       sub: "МБ/с" })
                            const hours = Math.floor(tv.load.uptime / 3600)
                            out.push({ icon: "timer",
                                       text: hours >= 24 ? Math.floor(hours / 24) + " дн" : hours + " ч",
                                       sub: "работает" })
                            for (const d of (tv.load.disks || []).slice(0, 2))
                                out.push({ icon: "hard-drive", text: Math.round(d.percent) + "%",
                                           sub: d.where + " · " + Math.round(d.free_gb) + " ГБ своб." })
                            return out
                        }
                        delegate: Rectangle {
                            required property var modelData
                            Layout.fillWidth: true
                            implicitHeight: 46
                            radius: 12
                            color: JD.fill1
                            ColumnLayout {
                                anchors.centerIn: parent
                                spacing: 0
                                RowLayout {
                                    Layout.alignment: Qt.AlignHCenter
                                    spacing: 5
                                    Icon { name: modelData.icon; implicitSize: 12; tint: JD.text3 }
                                    Label1 { text: modelData.text; font.pixelSize: 12 }
                                }
                                Label2 {
                                    Layout.alignment: Qt.AlignHCenter
                                    color: JD.text3
                                    font.pixelSize: 10
                                    text: modelData.sub
                                }
                            }
                        }
                    }
                }

                // Что съедает машину. Нажатие спрашивает ассистента — закрыть программу это
                // действие, которое трудно отменить, и решать должен человек.
                Label2 { text: "Тяжелее всех"; color: JD.text3 }
                Repeater {
                    model: tv.load && tv.load.top ? tv.load.top : []
                    delegate: Rectangle {
                        required property var modelData
                        Layout.fillWidth: true
                        implicitHeight: 34
                        radius: 9
                        color: procHover.hovered ? JD.fill1 : "transparent"
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 10
                            anchors.rightMargin: 10
                            spacing: 10
                            Label1 { Layout.fillWidth: true; text: modelData.name }
                            Label2 { text: modelData.mem_mb + " МБ"; color: JD.text3 }
                            Label1 {
                                text: modelData.cpu.toFixed(1) + "%"
                                color: modelData.cpu > 50 ? JD.accentOrange : JD.text2
                                horizontalAlignment: Text.AlignRight
                                Layout.preferredWidth: 52
                            }
                        }
                        HoverHandler { id: procHover; cursorShape: Qt.PointingHandCursor }
                        TapHandler {
                            gesturePolicy: TapHandler.ReleaseWithinBounds
                            onTapped: {
                                JD.closeTools()
                                JD.send({ cmd: "type", text: "закрой " + modelData.name })
                            }
                        }
                    }
                }
            }
        }
    }

    // Открыли панель — поле поиска сразу под пальцами. toolsSerial растёт на каждое открытие,
    // поэтому второе нажатие клавиши тоже возвращает фокус, а не оставляет его где было.
    Connections {
        target: JD
        function onToolsSerialChanged() { if (tv.searchable) field.forceActiveFocus() }
        function onToolsPageChanged() { if (tv.searchable) field.forceActiveFocus() }
    }
}
