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

    // Меню — рабочая поверхность, а не украшение: на ней читают и целятся, поэтому карточка почти
    // непрозрачная, а заливки кнопок плотнее островных. На чёрном острове 8% белого видно; на
    // карточке поверх размытых обоев — нет, и кнопки пропадали.
    readonly property color fill1: Qt.rgba(1, 1, 1, 0.10)
    readonly property color fill2: Qt.rgba(1, 1, 1, 0.18)
    readonly property color fill3: Qt.rgba(1, 1, 1, 0.26)

    readonly property var shown: JD.menuShown
    readonly property var user: JD.menuUser
    // Ничего не нашлось, а что-то напечатано — это не тупик, а вопрос ассистенту.
    readonly property bool askInstead: JD.menuSearching && shown.length === 0

    // Колонок столько, чтобы получился прямоугольник, а не строка с хвостом. Шесть программ в пять
    // колонок — это пять в ряд и одна под ними, и выглядит это как недогруженный список; те же
    // шесть в три колонки — ровный блок, который видно целиком одним взглядом.
    readonly property bool spotlight: JD.menuSearchMode
    // Spotlight — одна колонка-список; полное меню — сетка плиток.
    readonly property int columns: spotlight ? 1
                                 : shown.length <= 4 ? Math.max(1, shown.length)
                                 : shown.length <= 9 ? 3
                                 : shown.length <= 16 ? 4 : 5
    readonly property real tile: spotlight ? 52 : 104

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
    implicitHeight: 620

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

    // Кнопка-кружок нижней полки. Своя, а не IconButton: тот берёт островные 8% белого, которых на
    // этой карточке не видно, и подписи у него нет — а безымянный кружок не нажимают.
    component ToolDot: Rectangle {
        id: dot
        property string icon: ""
        property string note: ""
        property color accent: JD.text3
        signal picked()
        implicitWidth: 30
        implicitHeight: 30
        radius: 15
        color: dotHover.hovered ? mv.fill3 : "transparent"
        Behavior on color { ColorAnimation { duration: 120 } }
        scale: dotTap.pressed ? 0.9 : 1
        Behavior on scale { NumberAnimation { duration: 110 } }
        Icon { anchors.centerIn: parent; name: dot.icon; implicitSize: 16; tint: dotHover.hovered ? JD.text1 : dot.accent }
        HoverHandler { id: dotHover; cursorShape: Qt.PointingHandCursor; onHoveredChanged: mv.hintFor(hovered, dot.note) }
        TapHandler { id: dotTap; gesturePolicy: TapHandler.ReleaseWithinBounds; onTapped: dot.picked() }
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
    onVisibleChanged: if (visible) grab.restart()
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
        anchors.bottomMargin: spotlight ? 14 : 18
        spacing: spotlight ? 10 : 12

        // ───────────── поиск ─────────────
        //
        // Первым, как в спотлайте: меню открывают клавишей, и первое, что человек делает, — печатает.
        // Поле и так под курсором с первой секунды, поэтому обводить его толстым синим кольцом
        // незачем — кольцо в два пикселя кричало на всё окно о том, что и без него очевидно.
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 40
            radius: 20
            color: field.activeFocus ? mv.fill2 : mv.fill1
            border.width: 1
            border.color: field.activeFocus ? Qt.rgba(1, 1, 1, 0.22) : "transparent"
            Behavior on color { ColorAnimation { duration: 140 } }
            Behavior on border.color { ColorAnimation { duration: 140 } }
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
                            : ("Программа, файл, окно — или просьба к " + JD.assistantName)
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
            Behavior on opacity { NumberAnimation { duration: 160 } }

            Repeater {
                model: JD.menuGroups
                delegate: Rectangle {
                    required property var modelData
                    readonly property bool on: !JD.menuSearching && JD.menuGroup === modelData.id
                    implicitWidth: on ? 34 + chipName.implicitWidth + 12 : 34
                    implicitHeight: 34
                    radius: 17
                    color: on ? mv.fill3 : (chipHover.hovered ? mv.fill1 : "transparent")
                    Behavior on implicitWidth { enabled: JD.animOn
                                               NumberAnimation { duration: 170; easing.type: Easing.OutCubic } }
                    Behavior on color { ColorAnimation { duration: 130 } }
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
                readonly property real cell: mv.spotlight
                    ? parent.width
                    : Math.min(Math.floor((parent.width - 6) / mv.columns), 140)
                width: mv.spotlight ? parent.width : cell * mv.columns
                height: Math.min(parent.height, contentHeight)
                anchors.horizontalCenter: parent.horizontalCenter
                // Spotlight: список сверху; полное меню: сетка по центру.
                y: mv.spotlight ? 0 : Math.max(0, (parent.height - height) / 2)
                clip: true
                cellWidth: cell
                cellHeight: mv.tile
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
                    Rectangle {
                        anchors.fill: parent
                        anchors.margins: mv.spotlight ? 2 : 4
                        radius: mv.spotlight ? 10 : 12
                        color: index === JD.menuPick ? mv.fill2 : (tileHover.hovered ? mv.fill1 : "transparent")
                        Behavior on color { ColorAnimation { duration: 120 } }
                        scale: tileTap.pressed ? 0.94 : 1
                        Behavior on scale { NumberAnimation { duration: 110 } }

                        // Spotlight: строка значок+имя; полное меню: плитка.
                        RowLayout {
                            visible: mv.spotlight
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
                            visible: !mv.spotlight
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
                                implicitSize: 40
                                renderSize: 96
                                theme: true
                            }
                            Text {
                                Layout.fillWidth: true
                                font.family: JD.fontFamily
                                font.pixelSize: 12
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
                            visible: !mv.spotlight && modelData.kind !== "file" && modelData.kind !== "window" && JD.isPinned(modelData) && !JD.menuSearching
                            name: "star"
                            implicitSize: 13
                            tint: JD.accentOrange
                        }
                        // Открытое окно — это переход к нему, а не второй запуск, и об этом надо сказать.
                        Label2 {
                            anchors { bottom: parent.bottom; horizontalCenter: parent.horizontalCenter; bottomMargin: -2 }
                            visible: !mv.spotlight && (modelData.kind === "window" || modelData.kind === "file")
                            color: modelData.kind === "file" ? JD.text3 : JD.accentCyan
                            font.pixelSize: 11
                            text: modelData.kind === "file" ? "файл" : "открыто"
                        }
                        HoverHandler {
                            id: tileHover
                            cursorShape: Qt.PointingHandCursor
                            onHoveredChanged: mv.hintFor(hovered, (modelData.sub ? modelData.name + "  ·  " + modelData.sub : modelData.name)
                                + (modelData.kind === "window" ? "  ·  перейти к окну"
                                   : modelData.kind === "file" ? "  ·  открыть"
                                   : JD.isPinned(modelData) ? "  ·  правой кнопкой — открепить"
                                   : "  ·  правой кнопкой — закрепить"))
                        }
                        TapHandler {
                            id: tileTap
                            gesturePolicy: TapHandler.ReleaseWithinBounds
                            onTapped: JD.runFromMenu(modelData)
                        }
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
            Layout.preferredHeight: visible ? 30 : 0

            Rectangle {
                anchors { left: parent.left; right: parent.right; top: parent.top }
                height: 1
                color: Qt.rgba(1, 1, 1, 0.08)
            }

            RowLayout {
                anchors.fill: parent
                anchors.topMargin: 6
                spacing: 4
                ToolDot { icon: "smile"; note: "Эмодзи"; onPicked: { JD.closeMenu(); JD.openTools("emoji") } }
                ToolDot { icon: "clipboard"; note: "Буфер обмена"; onPicked: { JD.closeMenu(); JD.openTools("clip") } }
                ToolDot { icon: "gauge"; note: "Нагрузка машины"; onPicked: { JD.closeMenu(); JD.openTools("load") } }

                Label2 {
                    Layout.fillWidth: true
                    Layout.leftMargin: 8
                    font.pixelSize: 12
                    elide: Text.ElideRight
                    // Пока опасное ждёт второго щелчка, полка говорит об этом словами и красным.
                    // Раньше про «точно?» писала сама кнопка — и, раздуваясь, уводила соседние
                    // кнопки из-под курсора: человек целился в «выключить», а попадал в «сон».
                    color: mv.askingName ? JD.accentRed : JD.text3
                    text: mv.askingName ? mv.askingName + "  ·  нажмите ещё раз"
                                        : (mv.hint || (mv.user.name ? mv.user.name + (mv.user.host ? "  ·  " + mv.user.host : "") : ""))
                    opacity: (mv.askingName || mv.hint) ? 1 : 0.55
                    Behavior on opacity { NumberAnimation { duration: 120 } }
                }

                // Проверить обновление быстро, не уходя в настройки: кнопка там была, но на самом
                // дне страницы «О программе», и человек её попросту не находил.
                ToolDot {
                    icon: "refresh-cw"
                    note: "Проверить обновление"
                    onPicked: { JD.closeMenu(); JD.checkUpdate() }
                }
                ToolDot { icon: "settings"; note: "Настройки"; onPicked: { JD.closeMenu(); JD.openSettings("general") } }
                // Настройки самой плазмы: оболочка заменила панель и меню, но плазма под ней
                // осталась, и за обоями, экранами и клавишами человек идёт туда. Искать их через
                // поиск программ, когда меню уже открыто, — лишний круг.
                ToolDot {
                    icon: "sliders-horizontal"
                    note: "Настройки системы (KDE)"
                    onPicked: { JD.closeMenu(); Quickshell.execDetached(["systemsettings"]) }
                }

                // Опасное подтверждается второй раз той же кнопкой, а не окном поверх окна: она
                // краснеет, а словами про второй щелчок говорит подпись полки. Кнопка при этом
                // остаётся того же размера: раздувать её значит сдвигать соседние, и второй щелчок
                // человека уходит не туда, куда он целился. Блокировка и сон не теряют ничего и
                // спрашивать не должны — иначе защита превращается в помеху.
                Repeater {
                    model: JD.sessionActions
                    delegate: Rectangle {
                        id: pow
                        required property var modelData
                        readonly property bool asking: JD.menuConfirm === modelData.id
                        implicitWidth: 30
                        implicitHeight: 30
                        radius: 15
                        color: asking ? JD.accentRed : (powHover.hovered ? mv.fill3 : "transparent")
                        Behavior on color { ColorAnimation { duration: 140 } }
                        scale: powTap.pressed ? 0.9 : 1
                        Behavior on scale { NumberAnimation { duration: 110 } }
                        Icon {
                            anchors.centerIn: parent
                            name: pow.modelData.icon
                            implicitSize: 15
                            tint: pow.asking || powHover.hovered ? JD.text1 : JD.text3
                        }
                        HoverHandler {
                            id: powHover
                            cursorShape: Qt.PointingHandCursor
                            onHoveredChanged: mv.hintFor(hovered, pow.modelData.danger ? pow.modelData.name + "  ·  нажать дважды"
                                                                                       : pow.modelData.name)
                        }
                        TapHandler {
                            id: powTap
                            gesturePolicy: TapHandler.ReleaseWithinBounds
                            onTapped: JD.sessionDo(pow.modelData.id, pow.modelData.danger)
                        }
                    }
                }
            }
        }
    }
}
