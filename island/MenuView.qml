// Меню приложений — то, что в KDE открывается кнопкой Windows.
//
// Зачем своё. Кикофф KDE нарисован не тем набором значков, не теми цветами и не с теми углами, что
// островок, и подружить их нельзя: это чужая программа со своей темой. Меню же открывают по
// двадцать раз в день, и каждый раз оно объявляет, что здесь два разных интерфейса.
//
// Форма. Сначала здесь была колонка разделов слева и сетка справа — то есть «Пуск» из Windows,
// перекрашенный в другие цвета. Колонка из одиннадцати пунктов держала окно растянутым при любом
// числе программ, шапка с аватаром и пятью кнопками питания тянула взгляд на себя, а сетка жалась
// в угол. Теперь порядок другой и он же порядок мысли: сначала строка поиска, потом разделы одной
// лентой значков, потом сами программы. Всё мелкое — на одной полке внизу.
//
// Вид только рисует. Разделы, раскладка программ по ним, поиск и кнопки питания приходят готовыми
// от демона: он же отвечает ассистенту, поэтому «открой дискорд» голосом и строка поиска находят
// одно и то же. Второй поиск на QML разошёлся бы с первым в тот же день.
import QtQuick
import QtQuick.Layouts
import Quickshell

Item {
    id: mv

    readonly property var shown: JD.menuShown
    readonly property var user: JD.menuUser
    // Ничего не нашлось, а что-то напечатано — это не тупик, а вопрос ассистенту.
    readonly property bool askInstead: JD.menuSearching && shown.length === 0

    // Колонок столько, чтобы получился прямоугольник, а не строка с хвостом. Шесть программ в пять
    // колонок — это пять в ряд и одна под ними, и выглядит это как недогруженный список; те же
    // шесть в три колонки — ровный блок, который видно целиком одним взглядом.
    readonly property bool spotlight: JD.menuSearchMode
    // Список вместо сетки (island.menu_layout = "list"): строка со значком и именем, как в
    // Spotlight, но с полкой и разделами полного меню. Он просил выбор: сетка или список (16 нояб.).
    readonly property bool asList: spotlight || (!pad && JD.island.menu_layout === "list")
    // Launchpad: карточка во весь экран, значки крупнее, справа колонка плиток управления. Список,
    // поиск и разделы те же — меняется только то, сколько места им дали.
    readonly property bool pad: JD.menuLaunchpad
    readonly property real controlsW: 280
    // Spotlight — одна колонка-список; полное меню — сетка плиток.
    readonly property int columns: asList ? 1
                                 : pad ? Math.max(3, Math.floor((width - controlsW - 80) / padTile))
                                 // При поиске сетка постоянная и прижата к верху слева: найденное
                                 // встаёт прямо под строкой, куда смотрит глаз и тянется рука. Раньше
                                 // одна находка («bottle») садилась посреди пустого окна (16 нояб.).
                                 : JD.menuSearching ? 5
                                 : shown.length <= 4 ? Math.max(1, shown.length)
                                 : shown.length <= 9 ? 3
                                 : shown.length <= 16 ? 4 : 5
    readonly property real padTile: 150
    // Плитка выше, значок крупнее (8 нояб.): при значке 40 на карточке 760×620 меню выглядело
    // большим и пустым — «не в стиле Apple». Теперь значок 52, а карточка ниже (menu_height 500).
    // Нижняя граница высоты ряда. Настоящая высота растягивается так, чтобы в окно вошло целое
    // число рядов (grid.rowH): при постоянных 116 третий ряд резался пополам, и меню звало крутить
    // ради четырёх значков (9 нояб.).
    readonly property real tile: asList ? 52 : pad ? padTile : 96

    // Размер меню больше не считается по содержимому — и это починка, а не упрощение. Раньше
    // высота карточки равнялась высоте сетки: шесть закреплённых программ и сто пятьдесят семь
    // всех давали два разных окна, и лента разделов после каждого нажатия оказывалась в новом
    // месте. Нажал «Избранные» — лента уехала вверх, нажал «Все» — уехала вниз, и до следующего
    // раздела приходилось вести курсор через пол-экрана. Меню, в котором кнопки убегают от руки,
    // — плохое меню, каким бы точным ни был его размер.
    //
    // Теперь размер задаёт человек, углом карточки, и он же запоминается. Сетка прокручивается
    // внутри, а лента разделов и поиск стоят на месте всегда.
    implicitWidth: 760
    implicitHeight: 500

    // Одна строка подсказки внизу вместо всплывающих плашек у курсора: плашка закрывает соседнюю
    // плитку ровно в тот момент, когда по ней целятся.
    property string hint: ""
    function hintFor(on, text) { if (on) hint = text; else if (hint === text) hint = "" }

    // Имя действия, которое ждёт второго щелчка, — его показывает подпись полки.
    readonly property string askingName: {
        if (!JD.menuConfirm)
            return ""
        const rows = JD.sessionActions
        for (let i = 0; i < rows.length; ++i)
            if (rows[i].id === JD.menuConfirm)
                return rows[i].name
        return ""
    }

    // ───────────── полка: что на ней и в каком порядке ─────────────
    // Полка собирается из списка `island.menu_tools`: «|» — место подписи (имя и машина), слева от
    // неё — левые кнопки, справа — правые. Спрятанные лежат в `island.menu_tools_off`. Правка —
    // правой кнопкой по любому кружку: он хотел убирать лишние значки и переставлять их (16 нояб.).
    readonly property var toolDefs: ({
        mixer: { icon: "volume-2", note: "Звук", act: () => { JD.closeMenu(); JD.openTools("mixer") } },
        emoji: { icon: "smile", note: "Эмодзи", act: () => { JD.closeMenu(); JD.openTools("emoji") } },
        clip: { icon: "clipboard", note: "Буфер обмена", act: () => { JD.closeMenu(); JD.openTools("clip") } },
        load: { icon: "cpu", note: "Нагрузка машины", act: () => { JD.closeMenu(); JD.openTools("load") } },
        // Режим сервера прямо из меню: «включил и лёг спать» не должно начинаться с терминала.
        // Не луна: луна — это «сон» рядом, две одинаковые кнопки путали.
        server: { icon: JD.serverMode ? "sun" : "hard-drive", note: JD.serverMode ? "Вернуть машину" : "Режим сервера",
                  act: () => { JD.closeMenu(); JD.toggleServerMode() } },
        // Не круговые стрелки: так нарисована перезагрузка в той же полке.
        update: { icon: "download", note: "Проверить обновление", act: () => { JD.closeMenu(); JD.checkUpdate() } },
        settings: { icon: "settings", note: "Настройки", act: () => { JD.closeMenu(); JD.openSettings("general") } },
        // Плазма под оболочкой осталась: за обоями, экранами и клавишами человек идёт туда.
        kde: { icon: "sliders-horizontal", note: "Настройки системы (KDE)", act: () => { JD.closeMenu(); JD.systemSettings("") } }
    })
    readonly property var toolDefault: ["mixer", "emoji", "clip", "load", "|", "server", "update", "settings", "kde"]
        .concat(JD.sessionActions.map(a => "s:" + a.id))
    function toolKnown(id) { return id === "|" || !!toolDefs[id] || JD.sessionActions.some(a => "s:" + a.id === id) }
    property var toolsForced: null
    readonly property var toolOrder: {
        if (toolsForced) return toolsForced
        const saved = (Array.isArray(JD.island.menu_tools) ? JD.island.menu_tools : []).filter((x, i, a) => toolKnown(x) && a.indexOf(x) === i)
        if (!saved.length) return toolDefault
        if (!saved.includes("|")) saved.push("|")
        return saved.concat(toolDefault.filter(x => !saved.includes(x)))
    }
    readonly property var toolsOff: Array.isArray(JD.island.menu_tools_off) ? JD.island.menu_tools_off : []
    property bool toolsEdit: false
    Connections { target: JD; function onIslandChanged() { mv.toolsForced = null } }
    function toolShown(id) { return toolsEdit || !toolsOff.includes(id) }
    readonly property var toolsLeft: toolOrder.slice(0, toolOrder.indexOf("|")).filter(x => toolShown(x))
    readonly property var toolsRight: toolOrder.slice(toolOrder.indexOf("|") + 1).filter(x => toolShown(x))
    function toolToggle(id) {
        JD.setConfig("island.menu_tools_off", toolsOff.includes(id) ? toolsOff.filter(x => x !== id) : toolsOff.concat([id]))
    }
    // Брошенный кружок встаёт перед тем, над чьей серединой его отпустили; за подпись («|»)
    // перебрасывается на другую сторону полки.
    function toolDrop(id, sceneX) {
        let target = "", best = 1e9
        for (const d of toolDots) {
            if (!d || d.tid === id || !d.visible) continue
            const p = d.mapToItem(null, d.width / 2, 0), dist = Math.abs(p.x - sceneX)
            if (dist < best) { best = dist; target = d.tid; var after = sceneX > p.x }
        }
        if (!target) return
        const next = toolOrder.filter(x => x !== id)
        next.splice(next.indexOf(target) + (after ? 1 : 0), 0, id)
        toolsForced = next
        JD.setConfig("island.menu_tools", next)
    }
    property var toolDots: []
    Shortcut { sequence: "Escape"; enabled: mv.toolsEdit; onActivated: mv.toolsEdit = false }

    Component {
        id: toolDelegate
        Item {
            id: td
            required property string modelData
            readonly property string tid: modelData
            readonly property bool sess: tid.startsWith("s:")
            readonly property var sa: sess ? JD.sessionActions.find(a => "s:" + a.id === tid) : null
            readonly property var def: sess ? null : mv.toolDefs[tid]
            readonly property bool off: mv.toolsOff.includes(tid)
            readonly property bool asking: !!sa && JD.menuConfirm === sa.id
            implicitWidth: 30
            implicitHeight: 30
            opacity: off ? 0.35 : 1
            Component.onCompleted: mv.toolDots = mv.toolDots.concat([td])
            Component.onDestruction: mv.toolDots = mv.toolDots.filter(x => x !== td)
            transform: Translate { id: tdMove }
            Pressable {
                id: dot
                anchors.fill: parent
                radius: 15
                // Опасное подтверждается второй раз той же кнопкой, а не окном поверх окна: она
                // краснеет, а про второй щелчок говорит подпись полки. Размер не меняется — иначе
                // соседние кнопки уезжают из-под курсора.
                color: td.asking ? JD.accentRed : (hovered || mv.toolsEdit ? JD.menuFill3 : "transparent")
                Behavior on color { enabled: JD.animOn; ColorAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
                onHoveredChanged: if (!mv.toolsEdit) mv.hintFor(hovered, td.sa ? (td.sa.danger ? td.sa.name + "  ·  нажать дважды" : td.sa.name) : td.def.note)
                onClicked: {
                    if (mv.toolsEdit) mv.toolToggle(td.tid)
                    else if (td.sa) JD.sessionDo(td.sa.id, td.sa.danger)
                    else td.def.act()
                }
                Icon { anchors.centerIn: parent; name: td.sa ? td.sa.icon : td.def.icon; implicitSize: td.sa ? 15 : 16
                       tint: td.asking || dot.hovered ? JD.text1 : JD.text3 }
                TapHandler { acceptedButtons: Qt.RightButton; onTapped: mv.toolsEdit = !mv.toolsEdit }
                DragHandler {
                    enabled: mv.toolsEdit
                    target: null
                    yAxis.enabled: false
                    onTranslationChanged: tdMove.x = translation.x
                    onActiveChanged: if (!active) { const sx = td.mapToItem(null, td.width / 2, 0).x; tdMove.x = 0; mv.toolDrop(td.tid, sx) }
                }
            }
            Rectangle {
                visible: mv.toolsEdit
                width: 12; height: 12; radius: 6
                anchors { top: parent.top; right: parent.right; margins: -2 }
                color: td.off ? JD.accentGreen : JD.accentRed
                Rectangle { anchors.centerIn: parent; width: 6; height: 2; color: "white" }
                Rectangle { visible: td.off; anchors.centerIn: parent; width: 2; height: 6; color: "white" }
            }
        }
    }

    function move(step) {
        if (!shown.length) return
        JD.menuPick = Math.max(0, Math.min(shown.length - 1, JD.menuPick + step))
    }
    function take() {
        if (askInstead) { JD.askFromMenu(JD.menuQuery); return }
        JD.runFromMenu(shown[JD.menuPick] || shown[0])
    }
    // Меню открыли клавишей — значит, можно печатать сразу, не целясь мышью в строку.
    //
    // Три случая, и каждый нужен. Первое открытие: вида ещё нет, когда номер открытия растёт, —
    // ловим при создании. Повторное, пока вид жив: ловим по номеру. И третий, из-за которого это
    // вообще написано, — окно уже показано, а фокус слою выдали мгновением позже.
    Component.onCompleted: grab.restart()
    onVisibleChanged: { if (visible) grab.restart(); else toolsEdit = false }
    Connections {
        target: JD
        function onMenuSerialChanged() { grab.restart() }
    }
    Timer {
        id: grab
        interval: 1
        repeat: true
        triggeredOnStart: true
        property int tries: 0
        onRunningChanged: if (running) tries = 0
        onTriggered: {
            field.forceActiveFocus()
            field.selectAll()
            if (field.activeFocus || ++tries > 30) { stop(); interval = 1 } else interval = 30
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: spotlight ? 14 : 20
        // Полке снизу столько же воздуха, сколько слева: при 18 значки лежали на скруглении рамки (10 нояб.).
        anchors.bottomMargin: spotlight ? 14 : 20
        anchors.rightMargin: pad ? controlsW + 40 : (spotlight ? 14 : 20)
        spacing: spotlight ? 10 : 12

        // ───────────── поиск ─────────────
        //
        // Первым, как в спотлайте: меню открывают клавишей, и первое, что человек делает, — печатает.
        // Поле и так под курсором с первой секунды, поэтому обводить его толстым синим кольцом
        // незачем — кольцо в два пикселя кричало на всё окно о том, что и без него очевидно.
        Rectangle {
            Layout.fillWidth: true
            Layout.maximumWidth: mv.pad ? 560 : 100000
            Layout.alignment: Qt.AlignHCenter
            Layout.preferredHeight: 40
            radius: 20
            color: field.activeFocus ? JD.menuFill2 : JD.menuFill1
            border.width: 1
            border.color: field.activeFocus ? Qt.rgba(1, 1, 1, 0.22) : "transparent"
            Behavior on color { enabled: JD.animOn; ColorAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
            Behavior on border.color { enabled: JD.animOn; ColorAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 14
                anchors.rightMargin: 12
                spacing: 9
                Icon { name: "search"; implicitSize: 16; tint: JD.text3 }
                TextInput {
                    id: field
                    Layout.fillWidth: true
                    font.family: JD.fontFamily
                    font.pixelSize: 15
                    color: JD.text1
                    selectByMouse: true
                    selectionColor: JD.accentBlue
                    clip: true
                    text: JD.menuQuery
                    onTextChanged: if (text !== JD.menuQuery) { JD.menuQuery = text; JD.menuPick = 0; searchDelay.restart() }
                    Keys.onPressed: (e) => {
                        switch (e.key) {
                        case Qt.Key_Escape: JD.closeMenu(); break
                        case Qt.Key_Down: mv.move(mv.columns); break
                        case Qt.Key_Up: mv.move(-mv.columns); break
                        // Стрелки вбок двигают по сетке, только когда каретке некуда ехать по строке:
                        // иначе ими нельзя было бы править набранное.
                        case Qt.Key_Right: if (field.cursorPosition === field.text.length) mv.move(1); else return; break
                        case Qt.Key_Left: if (field.cursorPosition === 0) mv.move(-1); else return; break
                        case Qt.Key_Return:
                        case Qt.Key_Enter: mv.take(); break
                        default: return
                        }
                        e.accepted = true
                    }
                    Text {
                        anchors.fill: parent
                        verticalAlignment: Text.AlignVCenter
                        visible: !field.text
                        font: field.font
                        color: JD.text3
                        text: mv.spotlight
                            ? ("Поиск или просьба к " + JD.assistantName)
                            // Сочетание поиска прямо в поле: он хочет привыкнуть открывать поиск с
                            // клавиатуры, и меню, открытое мышью, каждый раз напоминает, как быстрее.
                            : ("Программа, файл или просьба к " + JD.assistantName + " · " + (JD.hotkeys.apps || "Alt+Space"))
                    }
                }
                // Поиск не на каждую букву: пока печатают быстро, спрашивать демона незачем.
                Timer { id: searchDelay; interval: 110; onTriggered: JD.searchMenu() }
                Icon {
                    visible: !!field.text
                    name: "x"
                    implicitSize: 15
                    tint: JD.text3
                    TapHandler { gesturePolicy: TapHandler.ReleaseWithinBounds; onTapped: { JD.menuQuery = ""; JD.menuFound = [] } }
                    HoverHandler { cursorShape: Qt.PointingHandCursor }
                }
            }
        }

        // ───────────── разделы ─────────────
        //
        // Лентой значков, а не колонкой в полкарточки. Названия у разделов длинные, и одиннадцать
        // названий подряд занимали столько места, что программы — то, ради чего меню открывают, —
        // оставались на вторых ролях. Значка хватает, чтобы узнать раздел; имя показывает тот, что
        // выбран, и тот, на который навели.
        RowLayout {
            visible: !spotlight
            Layout.fillWidth: true
            Layout.preferredHeight: visible ? 34 : 0
            spacing: 6
            opacity: JD.menuSearching ? 0.3 : 1
            Behavior on opacity { enabled: JD.animOn; NumberAnimation { duration: JD.durFast; easing.type: JD.easeOut } }

            Repeater {
                model: JD.menuGroups
                delegate: Rectangle {
                    required property var modelData
                    readonly property bool on: !JD.menuSearching && JD.menuGroup === modelData.id
                    implicitWidth: on ? 34 + chipName.implicitWidth + 12 : 34
                    implicitHeight: 34
                    radius: 17
                    color: on ? JD.menuFill3 : (chipHover.hovered ? JD.menuFill1 : "transparent")
                    Behavior on implicitWidth { enabled: JD.animOn
                                               NumberAnimation { duration: JD.durBase; easing.type: Easing.OutCubic } }
                    Behavior on color { enabled: JD.animOn; ColorAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
                    Row {
                        anchors.verticalCenter: parent.verticalCenter
                        x: 9
                        spacing: 7
                        Icon {
                            anchors.verticalCenter: parent.verticalCenter
                            name: modelData.icon
                            implicitSize: 16
                            tint: parent.parent.on ? JD.accentBlue : JD.text2
                        }
                        Label1 {
                            id: chipName
                            anchors.verticalCenter: parent.verticalCenter
                            visible: parent.parent.on
                            font.pixelSize: 13
                            text: modelData.name
                        }
                    }
                    HoverHandler {
                        id: chipHover
                        cursorShape: Qt.PointingHandCursor
                        onHoveredChanged: mv.hintFor(hovered, modelData.name + "  ·  " + (modelData.count || 0))
                    }
                    TapHandler {
                        gesturePolicy: TapHandler.ReleaseWithinBounds
                        onTapped: { JD.menuQuery = ""; JD.menuGroup = modelData.id; JD.menuPick = 0 }
                    }
                }
            }
            Item { Layout.fillWidth: true }
        }

        // ───────────── программы ─────────────
        Item {
            id: gridBox
            Layout.fillWidth: true
            Layout.fillHeight: true

            // Плитка, а не строка: значок программы — это то, по чему её узнают, и в списке из ста
            // штук глаз ищет картинку, а не слово.
            GridView {
                id: grid
                visible: !mv.askInstead && mv.shown.length > 0
                // Программ меньше, чем помещается, — сетка стоит посередине, а не жмётся к левому
                // верхнему углу, оставив вокруг себя дыру. Дыра поровну со всех сторон читается как
                // замысел; дыра с двух — как незаполненная форма.
                readonly property real cell: mv.asList
                    ? parent.width
                    : Math.min(Math.floor((parent.width - 6) / mv.columns), mv.pad ? 180 : 150)
                width: mv.asList ? parent.width : cell * mv.columns
                // Только целые ряды: ряд, срезанный пополам, звал крутить, а крутить было почти нечего.
                readonly property real rowH: mv.asList ? mv.tile
                    : parent.height / Math.max(1, Math.floor(parent.height / mv.tile))
                height: Math.min(parent.height, contentHeight)
                anchors.horizontalCenter: parent.horizontalCenter
                // Spotlight: список сверху; полное меню: сетка по центру.
                y: mv.asList || JD.menuSearching ? 0 : Math.max(0, (parent.height - height) / 2)
                clip: true
                cellWidth: cell
                cellHeight: rowH
                model: mv.shown
                currentIndex: JD.menuPick
                highlightMoveDuration: 90
                onCurrentIndexChanged: positionViewAtIndex(currentIndex, GridView.Contain)
                boundsBehavior: Flickable.StopAtBounds
                flickDeceleration: 2600
                maximumFlickVelocity: 6000

                // Колесо крутят по-разному: один щелчок, чтобы посмотреть следующий ряд, и десять
                // подряд, чтобы долистать до конца. Шаг постоянной величины отвечает на оба
                // одинаково, и быстрое кручение превращается в долгое. Поэтому чем чаще приходят
                // щелчки, тем крупнее шаг — до четырёх раз, дальше уже промахиваешься мимо цели.
                WheelHandler {
                    property real rush: 1
                    property real lastAt: 0
                    acceptedDevices: PointerDevice.Mouse | PointerDevice.TouchPad
                    onWheel: event => {
                        const now = Date.now()
                        const since = now - lastAt
                        lastAt = now
                        rush = since < 90 ? Math.min(4, rush + 0.55) : since < 220 ? Math.max(1, rush * 0.8) : 1
                        const step = (event.angleDelta.y / 120) * mv.tile * 0.75 * rush
                        const max = Math.max(0, grid.contentHeight - grid.height)
                        grid.contentY = Math.max(0, Math.min(max, grid.contentY - step))
                        event.accepted = true
                    }
                }

                delegate: Item {
                    required property var modelData
                    required property int index
                    width: grid.cellWidth
                    height: grid.cellHeight
                    Pressable {
                        id: appTile
                        anchors.fill: parent
                        anchors.margins: mv.asList ? 2 : 4
                        radius: mv.asList ? 10 : 12
                        color: index === JD.menuPick ? JD.menuFill2 : (appTile.hovered ? JD.menuFill1 : "transparent")
                        Behavior on color { enabled: JD.animOn; ColorAnimation { duration: JD.durFast; easing.type: JD.easeOut } }

                        // Spotlight: строка значок+имя; полное меню: плитка.
                        RowLayout {
                            visible: mv.asList
                            anchors.fill: parent
                            anchors.leftMargin: 12
                            anchors.rightMargin: 12
                            spacing: 12
                            Icon {
                                name: modelData.icon
                                fallback: "application-x-executable"
                                implicitSize: 28
                                renderSize: 64
                                theme: true
                            }
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 1
                                Text {
                                    Layout.fillWidth: true
                                    font.family: JD.fontFamily
                                    font.pixelSize: 14
                                    color: JD.text1
                                    elide: Text.ElideRight
                                    text: modelData.name
                                }
                                Label2 {
                                    visible: !!(modelData.sub || modelData.kind === "window" || modelData.kind === "file")
                                    Layout.fillWidth: true
                                    color: modelData.kind === "window" ? JD.accentCyan : JD.text3
                                    font.pixelSize: 11
                                    elide: Text.ElideRight
                                    text: modelData.kind === "file" ? (modelData.sub || "файл")
                                          : modelData.kind === "window" ? (modelData.sub || "открыто")
                                          : (modelData.sub || "")
                                }
                            }
                            Icon {
                                visible: modelData.kind !== "file" && modelData.kind !== "window" && JD.isPinned(modelData)
                                name: "star"
                                implicitSize: 13
                                tint: JD.accentOrange
                            }
                        }
                        ColumnLayout {
                            visible: !mv.asList
                            anchors.fill: parent
                            anchors.topMargin: 12
                            anchors.bottomMargin: 8
                            anchors.leftMargin: 7
                            anchors.rightMargin: 7
                            spacing: 8
                            Icon {
                                Layout.alignment: Qt.AlignHCenter
                                name: modelData.icon
                                fallback: "application-x-executable"
                                implicitSize: mv.pad ? 56 : 52
                                renderSize: 128
                                theme: true
                            }
                            Text {
                                Layout.fillWidth: true
                                font.family: JD.fontFamily
                                font.pixelSize: mv.pad ? 13 : 12
                                color: JD.text1
                                horizontalAlignment: Text.AlignHCenter
                                maximumLineCount: 2
                                wrapMode: Text.Wrap
                                elide: Text.ElideRight
                                text: modelData.name
                            }
                        }
                        // Звёздочка в углу: закреплённое видно, не наводя мышь.
                        Icon {
                            anchors { top: parent.top; right: parent.right; topMargin: 6; rightMargin: 6 }
                            visible: !mv.asList && modelData.kind !== "file" && modelData.kind !== "window" && JD.isPinned(modelData) && !JD.menuSearching
                            name: "star"
                            implicitSize: 13
                            tint: JD.accentOrange
                        }
                        // Открытое окно — это переход к нему, а не второй запуск, и об этом надо сказать.
                        Label2 {
                            anchors { bottom: parent.bottom; horizontalCenter: parent.horizontalCenter; bottomMargin: -2 }
                            visible: !mv.asList && (modelData.kind === "window" || modelData.kind === "file")
                            color: modelData.kind === "file" ? JD.text3 : JD.accentCyan
                            font.pixelSize: 11
                            text: modelData.kind === "file" ? "файл" : "открыто"
                        }
                        onHoveredChanged: mv.hintFor(hovered, (modelData.sub ? modelData.name + "  ·  " + modelData.sub : modelData.name)
                            + (modelData.kind === "window" ? "  ·  перейти к окну"
                               : modelData.kind === "file" ? "  ·  открыть"
                               : JD.isPinned(modelData) ? "  ·  правой кнопкой — открепить"
                               : "  ·  правой кнопкой — закрепить"))
                        onClicked: JD.runFromMenu(modelData)
                        // Правой кнопкой — закрепить. Без меню на меню: одно действие, один щелчок.
                        TapHandler {
                            acceptedButtons: Qt.RightButton
                            gesturePolicy: TapHandler.ReleaseWithinBounds
                            onTapped: JD.pinFromMenu(modelData)
                        }
                    }
                }
            }

            // Нижний ряд уходит в прозрачность, а не режется чертой.
            Rectangle {
                anchors { left: grid.left; right: grid.right; bottom: grid.bottom }
                height: 20
                visible: grid.visible && !grid.atYEnd
                gradient: Gradient {
                    GradientStop { position: 0; color: "transparent" }
                    GradientStop { position: 0.6; color: Qt.rgba(0.04, 0.04, 0.05, 0.7) }
                    GradientStop { position: 1; color: Qt.rgba(0.04, 0.04, 0.05, 1) }
                }
            }

            // Тонкая полоса прокрутки: без неё непонятно, что список длиннее окна.
            Rectangle {
                visible: grid.visible && grid.contentHeight > grid.height
                anchors { right: parent.right; rightMargin: 1 }
                width: 4
                radius: 2
                color: Qt.rgba(1, 1, 1, 0.3)
                height: Math.max(28, grid.height * grid.visibleArea.heightRatio)
                y: grid.y + grid.height * grid.visibleArea.yPosition
            }

            // Раздел пуст — так и скажем. Пустая площадь без слов читается как «не загрузилось».
            ColumnLayout {
                visible: !mv.askInstead && mv.shown.length === 0
                anchors.centerIn: parent
                spacing: 8
                Icon { Layout.alignment: Qt.AlignHCenter; name: "star"; implicitSize: 22; tint: JD.text3 }
                Label2 {
                    Layout.alignment: Qt.AlignHCenter
                    color: JD.text3
                    text: mv.spotlight ? "Ничего недавнего — начните печатать"
                         : JD.menuGroup === "fav" ? "Здесь пусто. Правой кнопкой по программе — закрепить."
                                                 : "В этом разделе ничего нет"
                }
            }

            // Ничего не нашлось — спросим ассистента. Ради этого меню и своё: строка поиска здесь
            // не обязана быть именем программы.
            ColumnLayout {
                visible: mv.askInstead
                anchors.centerIn: parent
                width: Math.min(parent.width - 40, 460)
                spacing: 12
                Icon { Layout.alignment: Qt.AlignHCenter; name: "sparkles"; implicitSize: 26; tint: JD.accentBlue }
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
                    text: "«" + JD.menuQuery + "»"
                }
                PillButton {
                    Layout.alignment: Qt.AlignHCenter
                    label: "Спросить  ⏎"
                    tint: JD.accentBlue
                    onClicked: JD.askFromMenu(JD.menuQuery)
                }
            }
        }

        // ───────────── нижняя полка ─────────────
        //
        // Одна полка на всё мелкое: инструменты слева, подсказка посередине, выключение и настройки
        // справа. Раньше кнопки питания стояли в шапке пятью серыми кругами и тянули на себя больше
        // внимания, чем всё меню вместе, — а нажимают из них дай бог один раз в неделю.
        // В Spotlight полка скрыта: это только поиск, не пуск.
        Item {
            visible: !spotlight
            Layout.fillWidth: true
            Layout.preferredHeight: visible ? 46 : 0

            Rectangle {
                anchors { left: parent.left; right: parent.right; top: parent.top }
                height: 1
                color: Qt.rgba(1, 1, 1, 0.08)
            }

            RowLayout {
                anchors.fill: parent
                anchors.topMargin: 10
                spacing: 4
                Repeater { model: mv.toolsLeft; delegate: toolDelegate }

                Label2 {
                    Layout.fillWidth: true
                    Layout.leftMargin: 8
                    font.pixelSize: 12
                    elide: Text.ElideRight
                    // Пока опасное ждёт второго щелчка, полка говорит об этом словами и красным.
                    // Раньше про «точно?» писала сама кнопка — и, раздуваясь, уводила соседние
                    // кнопки из-под курсора: человек целился в «выключить», а попадал в «сон».
                    color: mv.askingName ? JD.accentRed : JD.text3
                    text: mv.toolsEdit ? "Правка полки: нажатие прячет и возвращает, перетаскивание двигает · Esc — готово"
                                        : mv.askingName ? mv.askingName + "  ·  нажмите ещё раз"
                                        : (mv.hint || (mv.user.name ? mv.user.name + (mv.user.host ? "  ·  " + mv.user.host : "") : ""))
                    opacity: (mv.askingName || mv.hint) ? 1 : 0.55
                    Behavior on opacity { enabled: JD.animOn; NumberAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
                }

                Repeater { model: mv.toolsRight; delegate: toolDelegate }
                // Вид программ меняется здесь же, в правке полки: отдельная страница настроек ради
                // одного переключателя — лишний круг.
                Pressable {
                    visible: mv.toolsEdit && !mv.pad
                    implicitWidth: 30; implicitHeight: 30; radius: 15
                    color: JD.accentBlue
                    onHoveredChanged: mv.hintFor(hovered, mv.asList ? "Показать сеткой" : "Показать списком")
                    onClicked: JD.setConfig("island.menu_layout", mv.asList ? "grid" : "list")
                    Icon { anchors.centerIn: parent; name: mv.asList ? "layout-grid" : "list"; implicitSize: 16; tint: "white" }
                }
            }
        }
    }

    // Плитки управления — только в Launchpad, в правом поле, которое сетке не отдано.
    ControlTiles {
        visible: mv.pad
        anchors { top: parent.top; bottom: parent.bottom; right: parent.right; margins: 20 }
        width: mv.controlsW
    }
}
