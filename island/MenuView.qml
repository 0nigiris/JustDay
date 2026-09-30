// Меню приложений — то, что в KDE открывается кнопкой Windows.
//
// Зачем своё. Кикофф KDE нарисован не тем набором значков, не теми цветами и не с теми углами, что
// островок, и подружить их нельзя: это чужая программа со своей темой. Меню же открывают по
// двадцать раз в день, и каждый раз оно объявляет, что здесь два разных интерфейса.
//
// Что отсюда следует для этого файла. Всё, что видно, берётся из тех же JD.text1 / JD.fill1 /
// island/icons, что и остров: одна тема на всё, а не «похожая». Значки самих программ — из темы
// системы (theme: true), потому что они принадлежат программам, а не нам.
//
// Вид только рисует. Разделы, раскладка программ по ним, поиск и кнопки питания приходят готовыми
// от демона: он же отвечает ассистенту, поэтому «открой дискорд» голосом и строка поиска находят
// одно и то же. Второй поиск на QML разошёлся бы с первым в тот же день.
import QtQuick
import QtQuick.Layouts

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

    // Высота — по содержимому, а не константой. Шесть закреплённых программ в окне на 716 точек
    // означают семьдесят процентов пустоты, и никакая раскраска этого не спасает: окно, которое не
    // знает, сколько в нём лежит, выглядит чужим при любом наборе значков.
    // Колонок столько, чтобы получился прямоугольник, а не строка с хвостом. Шесть программ в пять
    // колонок — это пять в ряд и одна под ними, и выглядит это как недогруженный список; те же
    // шесть в три колонки — ровный блок, который видно целиком одним взглядом.
    readonly property int columns: shown.length <= 4 ? Math.max(1, shown.length)
                                 : shown.length <= 9 ? 3
                                 : shown.length <= 16 ? 4 : 5
    readonly property real tile: 106
    readonly property real railRow: 32
    readonly property real railWants: JD.menuGroups.length * railRow + Math.max(0, JD.menuGroups.length - 1) * 2
    readonly property real gridWants: Math.ceil(Math.max(1, shown.length) / columns) * tile
    readonly property real bodyHeight: Math.max(220, Math.min(560, Math.max(railWants, gridWants)))

    implicitWidth: 880
    implicitHeight: 20 + 44 + 12 + 40 + 12 + bodyHeight + 12 + 30 + 18
    // Одна строка подсказки внизу вместо всплывающих плашек у курсора: плашка закрывает соседнюю
    // плитку ровно в тот момент, когда по ней целятся.
    property string hint: ""
    function hintFor(on, text) { if (on) hint = text; else if (hint === text) hint = "" }

    // Кнопка-кружок внизу полосы. Своя, а не IconButton: тот берёт островные 8% белого, которых на
    // этой карточке не видно, и подписи у него нет — а безымянный кружок не нажимают.
    component ToolDot: Rectangle {
        id: dot
        property string icon: ""
        property string note: ""
        signal picked()
        implicitWidth: 30
        implicitHeight: 30
        radius: 15
        color: dotHover.hovered ? mv.fill3 : "transparent"
        Behavior on color { ColorAnimation { duration: 120 } }
        scale: dotTap.pressed ? 0.92 : 1
        Behavior on scale { NumberAnimation { duration: 110 } }
        Icon { anchors.centerIn: parent; name: dot.icon; implicitSize: 16; tint: dotHover.hovered ? JD.text1 : JD.text3 }
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
        anchors.margins: 20
        anchors.bottomMargin: 18
        spacing: 12

        // ───────────── шапка: кто за машиной и кнопка питания ─────────────
        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: 44
            spacing: 12

            Rectangle {
                implicitWidth: 42
                implicitHeight: 42
                radius: 21
                color: mv.fill1
                clip: true
                Image {
                    anchors.fill: parent
                    visible: !!mv.user.avatar
                    source: mv.user.avatar ? "file://" + mv.user.avatar : ""
                    fillMode: Image.PreserveAspectCrop
                    sourceSize: Qt.size(80, 80)
                    smooth: true
                }
                Icon {
                    anchors.centerIn: parent
                    visible: !mv.user.avatar
                    name: "user-round"
                    implicitSize: 20
                    tint: JD.text2
                }
            }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 0
                Label1 { Layout.fillWidth: true; font.pixelSize: 15; text: mv.user.name || "" }
                Label2 { Layout.fillWidth: true; color: JD.text3; text: mv.user.host || "" }
            }

            // Опасное подтверждается второй раз той же кнопкой, а не окном поверх окна: она
            // краснеет и подписывается «точно?». Блокировка и сон не теряют ничего и спрашивать
            // не должны — иначе защита превращается в помеху.
            //
            // В покое кружков нет — только значки. Пять одинаковых серых кругов в углу тянут на
            // себя больше внимания, чем всё меню вместе, а нажимают из них дай бог один в неделю.
            Repeater {
                model: JD.sessionActions
                delegate: Rectangle {
                    required property var modelData
                    readonly property bool asking: JD.menuConfirm === modelData.id
                    implicitWidth: asking ? askRow.implicitWidth + 26 : 34
                    implicitHeight: 34
                    radius: 17
                    color: asking ? JD.accentRed : (powHover.hovered ? mv.fill3 : "transparent")
                    Behavior on implicitWidth { enabled: JD.animOn; NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
                    Behavior on color { ColorAnimation { duration: 140 } }
                    RowLayout {
                        id: askRow
                        anchors.centerIn: parent
                        spacing: 6
                        Icon { name: modelData.icon; implicitSize: 16; tint: parent.parent.asking ? JD.text1 : JD.text2 }
                        Label1 { visible: parent.parent.asking; text: "точно?" }
                    }
                    HoverHandler {
                        id: powHover
                        cursorShape: Qt.PointingHandCursor
                        onHoveredChanged: mv.hintFor(hovered, modelData.danger ? modelData.name + "  ·  нажать дважды"
                                                                               : modelData.name)
                    }
                    TapHandler {
                        gesturePolicy: TapHandler.ReleaseWithinBounds
                        onTapped: JD.sessionDo(modelData.id, modelData.danger)
                    }
                }
            }
        }

        // ───────────── поиск ─────────────
        //
        // Поле и так под курсором с первой секунды — обводить его толстым синим кольцом незачем.
        // Кольцо в два пикселя кричало на всё окно о том, что и без него очевидно.
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
                    font.pixelSize: 14
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
                        text: "программа, игра, окно — или просьба к " + JD.assistantName + "…"
                    }
                }
                // Поиск не на каждую букву: пока печатают быстро, спрашивать демона незачем.
                Timer { id: searchDelay; interval: 110; onTriggered: JD.searchMenu() }
            }
        }

        // ───────────── разделы и сетка ─────────────
        RowLayout {
            Layout.fillWidth: true
            Layout.preferredHeight: mv.bodyHeight
            spacing: 16

            // Пока ищут, разделы не при чём: поиск идёт по всему сразу, и подсвеченный раздел
            // только врал бы, что ищем в нём.
            ColumnLayout {
                // Внутри RowLayout вложенная раскладка по умолчанию тянется во всю ширину и съедает
                // preferredWidth вместе с сеткой. Здесь ширина задана нарочно — значит, не тянуть.
                Layout.fillWidth: false
                Layout.preferredWidth: 196
                Layout.fillHeight: true
                Layout.alignment: Qt.AlignTop
                spacing: 2
                opacity: JD.menuSearching ? 0.35 : 1
                Behavior on opacity { NumberAnimation { duration: 160 } }

                Repeater {
                    model: JD.menuGroups
                    delegate: Rectangle {
                        required property var modelData
                        readonly property bool on: !JD.menuSearching && JD.menuGroup === modelData.id
                        Layout.fillWidth: true
                        implicitHeight: mv.railRow
                        radius: 9
                        // Выбранный раздел — приглушённая заливка, а синим горит только значок.
                        // Сплошная синяя полоса во всю ширину была самым громким пятном на экране,
                        // хотя говорит она всего лишь «вы здесь».
                        color: on ? mv.fill3 : (railHover.hovered ? mv.fill1 : "transparent")
                        Behavior on color { ColorAnimation { duration: 130 } }
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 10
                            anchors.rightMargin: 10
                            spacing: 9
                            Icon { name: modelData.icon; implicitSize: 15; tint: on ? JD.accentBlue : JD.text2 }
                            Label1 {
                                Layout.fillWidth: true
                                font.pixelSize: 13
                                font.weight: on ? Font.DemiBold : Font.Medium
                                color: on ? JD.text1 : JD.text2
                                text: modelData.name
                            }
                            Label2 { font.pixelSize: 11; color: JD.text3; text: modelData.count || "" }
                        }
                        HoverHandler { id: railHover; cursorShape: Qt.PointingHandCursor }
                        TapHandler {
                            gesturePolicy: TapHandler.ReleaseWithinBounds
                            onTapped: { JD.menuQuery = ""; JD.menuGroup = modelData.id; JD.menuPick = 0 }
                        }
                    }
                }
                Item { Layout.fillHeight: true }
            }

            // Сетка. Плитка, а не строка: значок программы — это то, по чему её узнают, и в списке
            // из ста штук глаз ищет картинку, а не слово.
            // Обёртка нужна ради двух вещей, которых у самой сетки быть не может: полосы прокрутки
            // и растворения у нижнего края. Ряд, обрезанный ровной чертой, читается как поломка
            // вёрстки; тот же ряд, уходящий в прозрачность, читается как «дальше есть ещё».
            Item {
                id: gridBox
                visible: !mv.askInstead && mv.shown.length > 0
                Layout.fillWidth: true
                Layout.fillHeight: true

            GridView {
                id: grid
                // Программ меньше, чем помещается, — сетка стоит посередине, а не жмётся к верху и
                // левому краю, оставив вокруг себя дыру. Дыра поровну со всех сторон читается как
                // замысел; дыра с двух — как незаполненная форма.
                readonly property real cell: Math.min(Math.floor((parent.width - 6) / mv.columns), 142)
                width: cell * mv.columns
                height: Math.min(parent.height, contentHeight)
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.verticalCenter: parent.verticalCenter
                clip: true
                cellWidth: cell
                cellHeight: mv.tile
                model: mv.shown
                currentIndex: JD.menuPick
                highlightMoveDuration: 90
                onCurrentIndexChanged: positionViewAtIndex(currentIndex, GridView.Contain)
                boundsBehavior: Flickable.StopAtBounds

                delegate: Item {
                    required property var modelData
                    required property int index
                    width: grid.cellWidth
                    height: grid.cellHeight
                    Rectangle {
                        anchors.fill: parent
                        anchors.margins: 4
                        radius: 13
                        color: index === JD.menuPick ? mv.fill2 : (tileHover.hovered ? mv.fill1 : "transparent")
                        Behavior on color { ColorAnimation { duration: 120 } }
                        scale: tileTap.pressed ? 0.94 : 1
                        Behavior on scale { NumberAnimation { duration: 110 } }

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.topMargin: 13
                            anchors.bottomMargin: 9
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
                            visible: JD.isPinned(modelData) && !JD.menuSearching
                            name: "star"
                            implicitSize: 13
                            tint: JD.accentOrange
                        }
                        // Открытое окно — это переход к нему, а не второй запуск, и об этом надо сказать.
                        Label2 {
                            anchors { bottom: parent.bottom; horizontalCenter: parent.horizontalCenter; bottomMargin: -2 }
                            visible: modelData.kind === "window"
                            color: JD.accentCyan
                            font.pixelSize: 11
                            text: "открыто"
                        }
                        HoverHandler {
                            id: tileHover
                            cursorShape: Qt.PointingHandCursor
                            onHoveredChanged: mv.hintFor(hovered, (modelData.sub ? modelData.name + "  ·  " + modelData.sub : modelData.name)
                                + (modelData.kind === "window" ? "  ·  перейти к окну"
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
                visible: !grid.atYEnd
                gradient: Gradient {
                    GradientStop { position: 0; color: "transparent" }
                    GradientStop { position: 0.6; color: Qt.rgba(0.04, 0.04, 0.05, 0.7) }
                    GradientStop { position: 1; color: Qt.rgba(0.04, 0.04, 0.05, 1) }
                }
            }

            // Тонкая полоса прокрутки: без неё непонятно, что список длиннее окна.
            Rectangle {
                visible: grid.contentHeight > grid.height
                anchors { right: parent.right; rightMargin: 1 }
                width: 4
                radius: 2
                color: Qt.rgba(1, 1, 1, 0.3)
                height: Math.max(28, grid.height * grid.visibleArea.heightRatio)
                y: grid.y + grid.height * grid.visibleArea.yPosition
            }
            }

            // Раздел пуст — так и скажем. Пустая площадь без слов читается как «не загрузилось».
            Item {
                visible: !mv.askInstead && mv.shown.length === 0
                Layout.fillWidth: true
                Layout.fillHeight: true
                ColumnLayout {
                    anchors.centerIn: parent
                    spacing: 8
                    Icon { Layout.alignment: Qt.AlignHCenter; name: "star"; implicitSize: 22; tint: JD.text3 }
                    Label2 {
                        Layout.alignment: Qt.AlignHCenter
                        color: JD.text3
                        text: JD.menuGroup === "fav" ? "Здесь пусто. Правой кнопкой по программе — закрепить."
                                                     : "В этом разделе ничего нет"
                    }
                }
            }

            // Ничего не нашлось — спросим ассистента. Ради этого меню и своё: строка поиска здесь
            // не обязана быть именем программы.
            Item {
                visible: mv.askInstead
                Layout.fillWidth: true
                Layout.fillHeight: true
                ColumnLayout {
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
        }

        // ───────────── подвал ─────────────
        //
        // Кнопки стоят под всей карточкой, а не под колонкой разделов. В колонке они держали её
        // растянутой до самого низа независимо от того, сколько в меню программ, — и именно оттуда
        // бралась половина пустоты. Здесь же живёт строка подсказки: одна полка на всё мелкое.
        Item {
            Layout.fillWidth: true
            Layout.preferredHeight: 30

            Rectangle {
                anchors { left: parent.left; right: parent.right; top: parent.top }
                height: 1
                color: Qt.rgba(1, 1, 1, 0.08)
            }

            RowLayout {
                anchors.fill: parent
                anchors.topMargin: 6
                spacing: 6
                ToolDot { icon: "smile"; note: "Эмодзи"; onPicked: { JD.closeMenu(); JD.openTools("emoji") } }
                ToolDot { icon: "clipboard"; note: "Буфер обмена"; onPicked: { JD.closeMenu(); JD.openTools("clip") } }
                ToolDot { icon: "gauge"; note: "Нагрузка машины"; onPicked: { JD.closeMenu(); JD.openTools("load") } }

                // Что делает то, на что навели. Пусто — значит ни на чём.
                Label2 {
                    Layout.fillWidth: true
                    Layout.leftMargin: 8
                    color: JD.text3
                    font.pixelSize: 12
                    text: mv.hint
                    opacity: mv.hint ? 1 : 0
                    Behavior on opacity { NumberAnimation { duration: 120 } }
                }

                ToolDot { icon: "settings"; note: "Настройки"; onPicked: { JD.closeMenu(); JD.openSettings("general") } }
            }
        }
    }
}
