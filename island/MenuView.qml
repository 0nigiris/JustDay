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
    implicitWidth: 760
    implicitHeight: 560

    readonly property var shown: JD.menuShown
    readonly property var user: JD.menuUser
    // Ничего не нашлось, а что-то напечатано — это не тупик, а вопрос ассистенту.
    readonly property bool askInstead: JD.menuSearching && shown.length === 0
    readonly property int columns: 5
    // Одна строка подсказки внизу вместо всплывающих плашек у курсора: плашка закрывает соседнюю
    // плитку ровно в тот момент, когда по ней целятся.
    property string hint: ""
    function hintFor(on, text) { if (on) hint = text; else if (hint === text) hint = "" }

    function move(step) {
        if (!shown.length) return
        JD.menuPick = Math.max(0, Math.min(shown.length - 1, JD.menuPick + step))
    }
    function take() {
        if (askInstead) { JD.askFromMenu(JD.menuQuery); return }
        JD.runFromMenu(shown[JD.menuPick] || shown[0])
    }
    // Поле не теряет фокус никогда: меню открыли клавишей, значит можно печатать сразу.
    onVisibleChanged: if (visible) field.forceActiveFocus()
    Connections {
        target: JD
        function onMenuSerialChanged() { field.forceActiveFocus(); field.selectAll() }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 20
        spacing: 14

        // ───────────── шапка: кто за машиной и кнопка питания ─────────────
        RowLayout {
            Layout.fillWidth: true
            spacing: 12

            Rectangle {
                implicitWidth: 40
                implicitHeight: 40
                radius: 20
                color: JD.fill1
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
            Repeater {
                model: JD.sessionActions
                delegate: Rectangle {
                    required property var modelData
                    readonly property bool asking: JD.menuConfirm === modelData.id
                    implicitWidth: asking ? askRow.implicitWidth + 24 : 34
                    implicitHeight: 34
                    radius: 17
                    color: asking ? JD.accentRed : (powHover.hovered ? JD.fill2 : JD.fill1)
                    Behavior on implicitWidth { enabled: JD.animOn; NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
                    Behavior on color { ColorAnimation { duration: 140 } }
                    RowLayout {
                        id: askRow
                        anchors.centerIn: parent
                        spacing: 6
                        Icon { name: modelData.icon; implicitSize: 15 }
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
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 42
            radius: 21
            color: JD.fill1
            border.width: 1
            border.color: field.activeFocus ? JD.accentBlue : "transparent"
            Behavior on border.color { ColorAnimation { duration: 140 } }
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 15
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
            Layout.fillHeight: true
            spacing: 14

            // Пока ищут, разделы не при чём: поиск идёт по всему сразу, и подсвеченный раздел
            // только врал бы, что ищем в нём.
            ColumnLayout {
                // Внутри RowLayout вложенная раскладка по умолчанию тянется во всю ширину и съедает
                // preferredWidth вместе с сеткой. Здесь ширина задана нарочно — значит, не тянуть.
                Layout.fillWidth: false
                Layout.preferredWidth: 168
                Layout.fillHeight: true
                spacing: 2
                opacity: JD.menuSearching ? 0.35 : 1
                Behavior on opacity { NumberAnimation { duration: 160 } }

                Repeater {
                    model: JD.menuGroups
                    delegate: Rectangle {
                        required property var modelData
                        readonly property bool on: !JD.menuSearching && JD.menuGroup === modelData.id
                        Layout.fillWidth: true
                        implicitHeight: 34
                        radius: 10
                        color: on ? JD.accentBlue : (railHover.hovered ? JD.fill1 : "transparent")
                        Behavior on color { ColorAnimation { duration: 130 } }
                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 11
                            anchors.rightMargin: 11
                            spacing: 9
                            Icon { name: modelData.icon; implicitSize: 15; tint: JD.text1 }
                            Label1 { Layout.fillWidth: true; text: modelData.name }
                            Label2 { color: on ? JD.text2 : JD.text3; text: modelData.count || "" }
                        }
                        HoverHandler { id: railHover; cursorShape: Qt.PointingHandCursor }
                        TapHandler {
                            gesturePolicy: TapHandler.ReleaseWithinBounds
                            onTapped: { JD.menuQuery = ""; JD.menuGroup = modelData.id; JD.menuPick = 0 }
                        }
                    }
                }
                Item { Layout.fillHeight: true }
                // Дверь к остальному острову: панель инструментов и настройки — оттуда же, откуда
                // человек уже привык открывать программы.
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 6
                    IconButton { icon: "smile"; size: 30; onClicked: { JD.closeMenu(); JD.openTools("emoji") } }
                    IconButton { icon: "clipboard"; size: 30; onClicked: { JD.closeMenu(); JD.openTools("clip") } }
                    IconButton { icon: "gauge"; size: 30; onClicked: { JD.closeMenu(); JD.openTools("load") } }
                    Item { Layout.fillWidth: true }
                    IconButton { icon: "settings"; size: 30; onClicked: { JD.closeMenu(); JD.openSettings("general") } }
                }
            }

            // Сетка. Плитка, а не строка: значок программы — это то, по чему её узнают, и в списке
            // из ста штук глаз ищет картинку, а не слово.
            GridView {
                id: grid
                visible: !mv.askInstead && mv.shown.length > 0
                Layout.fillWidth: true
                Layout.fillHeight: true
                clip: true
                cellWidth: Math.floor(width / mv.columns)
                cellHeight: 96
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
                        anchors.margins: 3
                        radius: 12
                        color: index === JD.menuPick ? JD.fill2 : (tileHover.hovered ? JD.fill1 : "transparent")
                        Behavior on color { ColorAnimation { duration: 120 } }
                        scale: tileTap.pressed ? 0.94 : 1
                        Behavior on scale { NumberAnimation { duration: 110 } }

                        ColumnLayout {
                            anchors.fill: parent
                            anchors.topMargin: 12
                            anchors.bottomMargin: 8
                            anchors.leftMargin: 6
                            anchors.rightMargin: 6
                            spacing: 7
                            Icon {
                                Layout.alignment: Qt.AlignHCenter
                                name: modelData.icon
                                fallback: "application-x-executable"
                                implicitSize: 36
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
                            implicitSize: 12
                            tint: JD.accentOrange
                        }
                        // Открытое окно — это переход к нему, а не второй запуск, и об этом надо сказать.
                        Label2 {
                            anchors { bottom: parent.bottom; horizontalCenter: parent.horizontalCenter; bottomMargin: -2 }
                            visible: modelData.kind === "window"
                            color: JD.accentCyan
                            font.pixelSize: 10
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
                        HoverHandler {
                            onHoveredChanged: mv.hintFor(hovered, (modelData.sub ? modelData.name + "  ·  " + modelData.sub : modelData.name)
                                + (modelData.kind === "window" ? "  ·  перейти к окну"
                                   : JD.isPinned(modelData) ? "  ·  правой кнопкой — открепить"
                                   : "  ·  правой кнопкой — закрепить"))
                        }
                    }
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

        // Что делает то, на что навели. Пусто — значит ни на чём.
        Label2 {
            Layout.fillWidth: true
            Layout.preferredHeight: 14
            color: JD.text3
            font.pixelSize: 11
            text: mv.hint
            opacity: mv.hint ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: 120 } }
        }
    }
}
