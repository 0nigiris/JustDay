// Панель инструментов островка: эмодзи, буфер обмена, звук, нагрузка машины.
//
// Программ здесь больше нет: у них своё меню (MenuView.qml) на всё окно, с разделами, значками и
// кнопкой питания. Две строки поиска по одному и тому же набору расходятся в тот же день, когда их
// становится две, — поэтому осталась одна, и она в меню.
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
import QtQuick.Controls

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
    readonly property bool searchable: page === "emoji" || page === "clip" || page === "history"

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
        //
        // fillHeight здесь обязателен явным false: у RowLayout внутри ColumnLayout он по умолчанию
        // true, и шапка забирала себе всю высоту окна — страница оставалась без места, а панель
        // открывалась пустой, с одними кнопками посреди черноты.
        RowLayout {
            Layout.fillWidth: true
            Layout.fillHeight: false
            spacing: 10

            Repeater {
                model: [
                    { id: "emoji", name: "Эмодзи", icon: "smile" },
                    { id: "clip", name: "Буфер", icon: "clipboard" },
                    { id: "mixer", name: "Звук", icon: "volume-2" },
                    { id: "plans", name: "Планы", icon: "clipboard" },
                    { id: "claude", name: "Клод", icon: "code" },
                    { id: "history", name: "История", icon: "message-circle" },
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
                            // Стрелки выбирают строку / клетку; Enter — скопировать и вставить в то окно, где курсор.
                            if (e.key === Qt.Key_Down || e.key === Qt.Key_Up
                                || e.key === Qt.Key_Left || e.key === Qt.Key_Right) {
                                let step = 0
                                if (tv.page === "emoji") {
                                    const cols = Math.max(1, Math.floor(grid.width / grid.cellWidth))
                                    if (e.key === Qt.Key_Down) step = cols
                                    else if (e.key === Qt.Key_Up) step = -cols
                                    else if (e.key === Qt.Key_Right) step = 1
                                    else if (e.key === Qt.Key_Left) {
                                        // Влево двигает каретку, пока есть куда; иначе — по сетке.
                                        if (field.cursorPosition > 0) return
                                        step = -1
                                    }
                                } else {
                                    if (e.key === Qt.Key_Down) step = 1
                                    else if (e.key === Qt.Key_Up) step = -1
                                    else return
                                }
                                JD.toolsPick = Math.max(0, Math.min(tv.items.length - 1, JD.toolsPick + step))
                                e.accepted = true
                                return
                            }
                            if (e.key !== Qt.Key_Return && e.key !== Qt.Key_Enter) return
                            e.accepted = true
                            // Enter берёт выбранное; ничего не выбирали — первое найденное.
                            const item = tv.items[JD.toolsPick] || tv.items[0]
                            if (!item) return
                            if (tv.page === "emoji") JD.useEmoji(item.c)
                            else JD.useClip(item.id)   // copy + paste (macOS-like)
                        }
                        Text {
                            anchors.fill: parent
                            verticalAlignment: Text.AlignVCenter
                            visible: !field.text
                            font: field.font
                            color: JD.text3
                            text: tv.page === "emoji" ? "кот, сердце, флаг…" : "искать в истории…"
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
            Layout.fillHeight: false
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
            currentIndex: JD.toolsPick
            onCurrentIndexChanged: positionViewAtIndex(currentIndex, GridView.Contain)
            Connections {
                target: JD
                function onToolsPickChanged() {
                    if (tv.page === "emoji")
                        grid.positionViewAtIndex(JD.toolsPick, GridView.Contain)
                }
            }
            delegate: Item {
                required property var modelData
                required property int index
                width: grid.cellWidth
                height: grid.cellHeight
                Rectangle {
                    anchors.centerIn: parent
                    width: 48
                    height: 48
                    radius: 12
                    color: index === JD.toolsPick ? JD.fill2 : (cellHover.hovered ? JD.fill1 : "transparent")
                    border.width: index === JD.toolsPick ? 1 : 0
                    border.color: JD.accentBlue
                    scale: cellTap.pressed ? 0.9 : 1
                    Behavior on scale { NumberAnimation { duration: 110 } }
                    Behavior on color { ColorAnimation { duration: 100 } }
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
                const item = tv.items[JD.toolsPick] || tv.items[0]
                return item ? item.c + "   " + item.n : ""
            }
        }

        // ───────────── программы, игры, окна ─────────────
        // ───────────── буфер обмена ─────────────
        ListView {
            id: clipList
            visible: tv.page === "clip"
            Layout.fillWidth: true
            Layout.fillHeight: true
            clip: true
            spacing: 6
            model: tv.page === "clip" ? tv.items : []
            currentIndex: JD.toolsPick
            onCurrentIndexChanged: positionViewAtIndex(currentIndex, ListView.Contain)
            Connections {
                target: JD
                function onToolsPickChanged() {
                    if (tv.page === "clip")
                        clipList.positionViewAtIndex(JD.toolsPick, ListView.Contain)
                }
            }
            delegate: Rectangle {
                id: row
                required property var modelData
                required property int index
                width: ListView.view.width
                readonly property bool isImage: modelData.kind === "image"
                readonly property bool isPinned: !!modelData.pinned
                readonly property bool editing: JD.clipEditing === modelData.id
                readonly property bool selected: !editing && index === JD.toolsPick
                implicitHeight: editing ? Math.max(120, editBox.implicitHeight + 58)
                                        : (isImage ? 72 : 46)
                radius: 10
                color: editing || selected || rowHover.hovered ? JD.fill1 : "transparent"
                border.width: selected ? 1 : 0
                border.color: JD.accentBlue
                Behavior on implicitHeight { NumberAnimation { duration: 140 } }
                Behavior on color { ColorAnimation { duration: 100 } }

                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 10
                    anchors.rightMargin: 8
                    anchors.topMargin: 6
                    anchors.bottomMargin: 6
                    spacing: 10

                    // Миниатюра снимка вместо подписи «screenshot copied» / «картинка, N КБ».
                    Rectangle {
                        visible: row.isImage && !row.editing
                        Layout.preferredWidth: 56
                        Layout.preferredHeight: 56
                        radius: 8
                        color: JD.fill2
                        clip: true
                        Image {
                            anchors.fill: parent
                            anchors.margins: 1
                            fillMode: Image.PreserveAspectCrop
                            asynchronous: true
                            source: row.modelData.file ? ("file://" + row.modelData.file) : ""
                        }
                    }
                    Icon {
                        visible: !row.isImage && !row.editing
                        name: "file-text"
                        implicitSize: 15
                        tint: JD.text3
                    }

                    ColumnLayout {
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        spacing: 2
                        visible: !row.editing

                        Label1 {
                            Layout.fillWidth: true
                            text: row.modelData.preview
                        }
                        Label2 {
                            color: JD.text3
                            text: (row.isPinned ? "📌 · " : "")
                                  + tv.ago(row.modelData.at)
                                  + (row.modelData.lines > 1 ? " · " + row.modelData.lines + " строк" : "")
                                  + (row.isImage ? "" : " · " + tv.fmtSize(row.modelData.size))
                        }
                    }

                    // Inline editor for copied text.
                    Rectangle {
                        id: editBox
                        visible: row.editing
                        Layout.fillWidth: true
                        Layout.fillHeight: true
                        implicitHeight: Math.min(220, Math.max(72, editInput.contentHeight + 20))
                        radius: 8
                        color: JD.fill2
                        border.width: 1
                        border.color: JD.accentBlue
                        Flickable {
                            id: editFlick
                            anchors.fill: parent
                            anchors.margins: 8
                            contentHeight: editInput.implicitHeight
                            clip: true
                            interactive: contentHeight > height
                            TextArea {
                                id: editInput
                                width: editFlick.width
                                wrapMode: TextArea.Wrap
                                selectByMouse: true
                                color: JD.text1
                                font.pixelSize: 14
                                text: JD.clipEditDraft
                                onTextChanged: if (row.editing) JD.clipEditDraft = text
                                background: null
                                Keys.onPressed: event => {
                                    if (event.key === Qt.Key_Escape) {
                                        JD.clipEditing = ""; JD.clipEditDraft = ""
                                        event.accepted = true
                                    } else if (event.key === Qt.Key_Return
                                               && (event.modifiers & Qt.ControlModifier)) {
                                        JD.editClip(row.modelData.id, JD.clipEditDraft)
                                        JD.clipEditing = ""; JD.clipEditDraft = ""
                                        event.accepted = true
                                    }
                                }
                            }
                        }
                        Component.onCompleted: if (row.editing) editInput.forceActiveFocus()
                    }

                    RowLayout {
                        spacing: 2
                        IconButton {
                            visible: row.editing
                            icon: "check"
                            size: 26
                            onClicked: {
                                JD.editClip(row.modelData.id, JD.clipEditDraft)
                                JD.clipEditing = ""; JD.clipEditDraft = ""
                            }
                        }
                        IconButton {
                            visible: row.editing
                            icon: "x"
                            size: 26
                            onClicked: { JD.clipEditing = ""; JD.clipEditDraft = "" }
                        }
                        IconButton {
                            visible: !row.editing
                            icon: "star"
                            size: 26
                            opacity: rowHover.hovered || row.isPinned ? 1 : 0
                            Behavior on opacity { NumberAnimation { duration: 120 } }
                            // Закреплённая звезда всегда видна; цвет задаёт сама кнопка через акцент.
                            onClicked: JD.pinClip(row.modelData.id, !row.isPinned)
                        }
                        IconButton {
                            visible: !row.editing && !row.isImage
                            icon: "pencil"
                            size: 26
                            opacity: rowHover.hovered ? 1 : 0
                            Behavior on opacity { NumberAnimation { duration: 120 } }
                            onClicked: {
                                JD.clipEditing = row.modelData.id
                                // Полный текст подгрузим запросом; пока — preview как черновик.
                                JD.clipEditDraft = row.modelData.preview || ""
                                JD.send({ cmd: "clip_text", which: String(row.modelData.id) })
                            }
                        }
                        IconButton {
                            visible: !row.editing
                            icon: "trash-2"
                            size: 26
                            opacity: rowHover.hovered ? 1 : 0
                            Behavior on opacity { NumberAnimation { duration: 120 } }
                            onClicked: JD.forgetClip(row.modelData.id)
                        }
                    }
                }
                HoverHandler { id: rowHover; cursorShape: row.editing ? Qt.IBeamCursor : Qt.PointingHandCursor }
                TapHandler {
                    enabled: !row.editing
                    gesturePolicy: TapHandler.ReleaseWithinBounds
                    onTapped: JD.useClip(row.modelData.id)
                }
            }
        }

        RowLayout {
            visible: tv.page === "clip"
            Layout.fillWidth: true
            Layout.fillHeight: false
            spacing: 10
            Label2 {
                Layout.fillWidth: true
                color: JD.text3
                text: JD.clipPaused ? "на паузе: новое не запоминается"
                     : JD.clipSkipped ? "пароли и ключи сюда не попадают — пропущено: " + JD.clipSkipped
                     : "пароли и ключи сюда не попадают · 📌 закрепляет · карандаш правит"
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

        // ───────────── живые сессии ─────────────
        SessionsView {
            visible: tv.page === "claude"
            Layout.fillWidth: true
            Layout.fillHeight: true
        }

        // ───────────── история разговоров ─────────────
        HistoryView {
            visible: tv.page === "history"
            Layout.fillWidth: true
            Layout.fillHeight: true
        }

        // ───────────── планы ─────────────
        PlansView {
            visible: tv.page === "plans"
            Layout.fillWidth: true
            Layout.fillHeight: true
        }

        // ───────────── микшер ─────────────
        MixerView {
            visible: tv.page === "mixer"
            Layout.fillWidth: true
            Layout.fillHeight: true
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
