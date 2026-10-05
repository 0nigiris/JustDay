// Spotlight: поиск по всему сразу, клавишей и с клавиатуры.
//
// Это не уменьшенный «Пуск». Пуск открывают, чтобы посмотреть, что вообще есть, — там разделы,
// плитки и полка питания. Spotlight открывают, уже зная, что нужно: нажал, напечатал три буквы,
// Enter. Всё остальное на этой поверхности лишнее, и поэтому его здесь нет.
//
// Правила, которым подчинён этот вид:
//   — поле ввода стоит на месте и не шевелится, когда меняются находки: прыгающая строка под
//     пальцами — худшее, что может сделать поиск;
//   — карточка растёт вниз от своего верхнего края, а не из середины: верх прибит, низ едет;
//   — выбор — это логика, а не картинка: он меняется мгновенно, пружина только догоняет подсветку;
//   — находки сгруппированы по роду (программы, окна, файлы), потому что искать глазами в
//     перемешанном списке дольше, чем прочитать подпись.
import QtQuick
import QtQuick.Layouts

Item {
    id: sp

    readonly property var rows: JD.menuFound || []
    readonly property bool asking: JD.menuSearching && rows.length === 0

    // Плоский список: подписи групп и сами находки вперемешку, по порядку. Высота у строк разная,
    // поэтому ListView, а не сетка: сетке все ячейки нужны одного роста.
    readonly property var lines: {
        const out = []
        let was = ""
        for (let i = 0; i < rows.length; i++) {
            const kind = String(rows[i].kind || "")
            if (kind !== was) {
                out.push({ caption: sp.groupName(kind) })
                was = kind
            }
            out.push({ row: rows[i], at: i })
        }
        return out
    }

    function groupName(kind) {
        return kind === "app" ? JD.tr("Программы")
             : kind === "game" ? JD.tr("Игры")
             : kind === "window" ? JD.tr("Открытые окна")
             : kind === "file" ? JD.tr("Файлы")
             : JD.tr("Другое")
    }

    // Высота: строка поиска плюс находки, но не выше предела. Её читает карточка в shell.qml —
    // поверхность растёт вниз ровно настолько, насколько есть что показать.
    readonly property int barHeight: 76
    readonly property int maxHeight: 760
    implicitWidth: 720
    implicitHeight: Math.min(maxHeight, barHeight + (list.count ? Math.min(list.contentHeight + 12, maxHeight - barHeight) : (asking ? 92 : 0)))

    function move(step) {
        if (!rows.length) return
        JD.menuPick = Math.max(0, Math.min(rows.length - 1, JD.menuPick + step))
    }
    function take() {
        if (asking) { JD.askFromMenu(JD.menuQuery); return }
        JD.runFromMenu(rows[JD.menuPick] || rows[0])
    }

    // Открыли клавишей — значит печатать можно сразу, не целясь мышью в строку.
    Component.onCompleted: field.forceActiveFocus()
    Connections {
        target: JD
        function onMenuSerialChanged() { field.forceActiveFocus() }
    }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        // ───────────── строка поиска ─────────────
        //
        // Без своей подложки и без рамки: подложка внутри подложки — это две рамки на одном окне,
        // а здесь всё окно и есть поле ввода.
        Item {
            Layout.fillWidth: true
            Layout.preferredHeight: sp.barHeight

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 24
                anchors.rightMargin: 24
                spacing: 14

                Icon {
                    name: "search"
                    implicitSize: 26
                    tint: JD.text1
                    opacity: 0.58
                    scale: field.activeFocus ? 1.04 : 1
                    Behavior on scale { enabled: JD.animOn; NumberAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
                }

                TextInput {
                    id: field
                    Layout.fillWidth: true
                    font.family: JD.fontFamily
                    font.pixelSize: 28
                    color: JD.text1
                    selectByMouse: true
                    selectionColor: JD.accentBlue
                    clip: true
                    text: JD.menuQuery
                    onTextChanged: if (text !== JD.menuQuery) { JD.menuQuery = text; JD.menuPick = 0; later.restart() }
                    Keys.onPressed: (e) => {
                        switch (e.key) {
                        // Первый Escape стирает набранное, второй закрывает. Так ошибку в запросе
                        // можно исправить, не открывая поиск заново.
                        case Qt.Key_Escape:
                            if (field.text) { JD.menuQuery = ""; JD.menuFound = []; JD.menuPick = 0; JD.searchMenu() }
                            else JD.closeMenu()
                            break
                        case Qt.Key_Down: sp.move(1); break
                        case Qt.Key_Up: sp.move(-1); break
                        case Qt.Key_PageDown: sp.move(5); break
                        case Qt.Key_PageUp: sp.move(-5); break
                        case Qt.Key_Home: JD.menuPick = 0; break
                        case Qt.Key_End: JD.menuPick = Math.max(0, sp.rows.length - 1); break
                        case Qt.Key_Return:
                        case Qt.Key_Enter: sp.take(); break
                        default: return
                        }
                        e.accepted = true
                    }
                    // Поиск не на каждую букву: пока печатают быстро, спрашивать демона незачем.
                    Timer { id: later; interval: 40; onTriggered: JD.searchMenu() }
                    Text {
                        anchors.fill: parent
                        verticalAlignment: Text.AlignVCenter
                        visible: !field.text
                        font: field.font
                        color: JD.text1
                        opacity: 0.42
                        text: JD.tr("Поиск")
                    }
                }

                Label2 {
                    visible: !field.text
                    text: "Alt Space"
                    color: JD.text3
                    opacity: 0.6
                    font.pixelSize: 12
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredHeight: 1
            visible: list.count > 0 || sp.asking
            color: Qt.rgba(1, 1, 1, 0.07)
        }

        // ───────────── ничего не нашлось ─────────────
        //
        // Пустой поиск — не тупик: то, что мы не нашли, может знать ассистент.
        Item {
            Layout.fillWidth: true
            Layout.preferredHeight: sp.asking ? 90 : 0
            visible: sp.asking
            Column {
                anchors.centerIn: parent
                spacing: 6
                Label1 {
                    anchors.horizontalCenter: parent.horizontalCenter
                    text: JD.tr("Ничего не нашлось")
                }
                Label2 {
                    anchors.horizontalCenter: parent.horizontalCenter
                    color: JD.text3
                    text: JD.tr("Enter — спросить ") + JD.assistantName
                }
            }
        }

        ListView {
            id: list
            Layout.fillWidth: true
            Layout.fillHeight: true
            visible: !sp.asking
            clip: true
            model: sp.lines
            boundsBehavior: Flickable.StopAtBounds
            currentIndex: {
                for (let i = 0; i < sp.lines.length; i++)
                    if (sp.lines[i].row && sp.lines[i].at === JD.menuPick) return i
                return 0
            }
            onCurrentIndexChanged: positionViewAtIndex(currentIndex, ListView.Contain)
            topMargin: 6
            bottomMargin: 6

            delegate: Item {
                id: line
                required property var modelData
                readonly property bool caption: !!modelData.caption
                readonly property var row: modelData.row || ({})
                readonly property bool on: !caption && modelData.at === JD.menuPick
                width: ListView.view.width
                height: caption ? 28 : 68

                Label2 {
                    visible: line.caption
                    anchors { left: parent.left; leftMargin: 26; bottom: parent.bottom; bottomMargin: 4 }
                    text: line.modelData.caption || ""
                    color: JD.text3
                    font.pixelSize: 11
                    font.weight: Font.DemiBold
                    font.capitalization: Font.AllUppercase
                    font.letterSpacing: 0.6
                }

                Rectangle {
                    visible: !line.caption
                    anchors { fill: parent; leftMargin: 12; rightMargin: 12; topMargin: 2; bottomMargin: 2 }
                    radius: 14
                    color: line.on ? Qt.rgba(1, 1, 1, 0.10)
                         : hover.hovered ? Qt.rgba(1, 1, 1, 0.05) : "transparent"
                    Behavior on color { enabled: JD.animOn; ColorAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
                    scale: line.on ? 1.015 : 1
                    Behavior on scale { enabled: JD.animOn; NumberAnimation { duration: JD.durFast; easing.type: JD.easeOut } }

                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 14
                        anchors.rightMargin: 14
                        spacing: 14

                        Item {
                            implicitWidth: 44
                            implicitHeight: 44
                            Icon {
                                anchors.centerIn: parent
                                name: line.row.icon || "application-x-executable"
                                fallback: "application-x-executable"
                                implicitSize: 40
                                renderSize: 96
                                // Значок самой программы, как в Пуске. Без этого признака весь список
                                // выглядел одинаковыми пустыми окошками: наше запасное имя
                                // application-x-executable само есть в штриховом наборе и перебивало
                                // настоящий значок — Spotlight отделился от Пуска и потерял это.
                                theme: true
                            }
                            // Открытое окно отмечено точкой: запускать второй раз его не надо.
                            Rectangle {
                                visible: line.row.kind === "window"
                                anchors { right: parent.right; bottom: parent.bottom }
                                implicitWidth: 8; implicitHeight: 8; radius: 4
                                color: JD.accentBlue
                            }
                        }

                        ColumnLayout {
                            Layout.fillWidth: true
                            spacing: 1
                            Label1 {
                                Layout.fillWidth: true
                                text: line.row.name || ""
                                font.pixelSize: 17
                                font.weight: line.on ? Font.DemiBold : Font.Medium
                                elide: Text.ElideRight
                            }
                            Label2 {
                                Layout.fillWidth: true
                                visible: !!line.row.sub
                                text: line.row.sub || ""
                                font.pixelSize: 13
                                color: JD.text3
                                opacity: 0.8
                                elide: Text.ElideMiddle
                            }
                        }

                        Label2 {
                            visible: line.on
                            text: "Enter"
                            color: JD.text3
                            opacity: 0.55
                            font.pixelSize: 12
                        }
                    }

                    HoverHandler {
                        id: hover
                        cursorShape: Qt.PointingHandCursor
                        onHoveredChanged: if (hovered) JD.menuPick = line.modelData.at
                    }
                    TapHandler {
                        gesturePolicy: TapHandler.ReleaseWithinBounds
                        onTapped: { JD.menuPick = line.modelData.at; sp.take() }
                    }
                }
            }
        }
    }
}
