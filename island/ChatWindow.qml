import QtQuick
import QtQuick.Layouts
import Quickshell

// Отдельный чат с ассистентом (Р2-42). Обычное окно: у него фокус клавиатуры, Alt+Tab и сворачивание.
// Ответы сюда приходят из демона и никогда не озвучиваются; голосовой Джарвис — отдельная вещь.
FloatingWindow {
    id: win
    visible: JD.chatOpen
    title: "JustDay — чат"
    implicitWidth: 880
    implicitHeight: 620
    color: "#1c1c1e"
    // MarkdownText сам скачивает картинки `![](адрес)`, и `![x][ссылка]` тоже. Сайт, прочитанный
    // мозгом, может внушить ему такую картинку с чем-нибудь личным в адресе, и окно отправит это
    // наружу, едва ответ покажется: никто ничего не нажимал. Проверено опытом — запрос уходил.
    // Без `!` картинка становится обычной ссылкой, а ссылку открывает только человек. HTML <img>
    // и фоны в стилях MarkdownText не грузит — проверено тем же опытом.
    function noRemoteImages(t) { return String(t || "").replace(/!\[/g, "[") }
    onVisibleChanged: {
        if (visible) { JD.chatRefresh(); input.forceActiveFocus() }
        else JD.chatOpen = false   // окно закрыли крестиком рамки
    }

    Connections {
        target: JD
        function onChatMessagesChanged() { Qt.callLater(() => list.positionViewAtEnd()) }
        // Надиктованное ложится туда, где стоит курсор, и не уходит само: Whisper мог расслышать криво.
        function onChatInsert(text) {
            const gap = input.cursorPosition > 0 && !/\s$/.test(input.getText(0, input.cursorPosition)) ? " " : ""
            input.insert(input.cursorPosition, gap + text)
            input.forceActiveFocus()
        }
    }

    RowLayout {
        anchors.fill: parent
        spacing: 0

        // ── слева: чаты ──
        Rectangle {
            Layout.fillHeight: true; Layout.preferredWidth: 240
            color: "#2c2c2e"
            ColumnLayout {
                anchors { fill: parent; margins: 10 }
                spacing: 8
                Rectangle {
                    Layout.fillWidth: true; implicitHeight: 34; radius: 8; color: JD.accentBlue
                    Text { anchors.centerIn: parent; text: JD.tr("Новый чат"); color: "#ffffff"; font.family: JD.fontFamily; font.pixelSize: 13; font.weight: Font.DemiBold }
                    MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: JD.chatNew() }
                }
                Rectangle {
                    Layout.fillWidth: true; implicitHeight: 32; radius: 8; color: JD.fill1
                    TextInput {
                        id: search
                        anchors { fill: parent; leftMargin: 10; rightMargin: 10 }
                        verticalAlignment: TextInput.AlignVCenter
                        font.family: JD.fontFamily; font.pixelSize: 13; color: JD.text1; clip: true
                        onTextChanged: JD.send({ cmd: "chat_list", query: text })
                        Text { visible: !search.text; anchors.verticalCenter: parent.verticalCenter; text: JD.tr("Поиск"); color: JD.text3; font: search.font }
                    }
                }
                ListView {
                    Layout.fillWidth: true; Layout.fillHeight: true
                    model: JD.chatList; clip: true; spacing: 2
                    delegate: Rectangle {
                        required property var modelData
                        width: ListView.view.width; height: 34; radius: 8
                        color: modelData.id === JD.chatCurrent ? JD.fill2 : (hover.hovered ? JD.fill1 : "transparent")
                        HoverHandler { id: hover }
                        Text {
                            anchors { left: parent.left; right: del.left; verticalCenter: parent.verticalCenter; leftMargin: 10; rightMargin: 4 }
                            text: modelData.title; textFormat: Text.PlainText; elide: Text.ElideRight
                            color: JD.text1; font.family: JD.fontFamily; font.pixelSize: 13
                        }
                        Text {
                            id: del
                            visible: hover.hovered
                            anchors { right: parent.right; rightMargin: 10; verticalCenter: parent.verticalCenter }
                            text: "✕"; color: JD.text3; font.pixelSize: 12
                            MouseArea { anchors.fill: parent; anchors.margins: -6; cursorShape: Qt.PointingHandCursor; onClicked: JD.chatDelete(modelData.id) }
                        }
                        MouseArea { anchors.fill: parent; z: -1; onClicked: JD.chatOpenOne(modelData.id) }
                    }
                }
            }
        }

        // ── справа: переписка ──
        ColumnLayout {
            Layout.fillWidth: true; Layout.fillHeight: true
            spacing: 0
            ListView {
                id: list
                Layout.fillWidth: true; Layout.fillHeight: true
                model: JD.chatMessages; clip: true; spacing: 10
                topMargin: 16; bottomMargin: 8
                delegate: Item {
                    required property var modelData
                    readonly property bool mine: modelData.role === "user"
                    width: ListView.view.width
                    height: bubble.height
                    Rectangle {
                        id: bubble
                        x: mine ? parent.width - width - 20 : 20
                        width: Math.min(parent.width - 80, body.implicitWidth + 24)
                        height: body.implicitHeight + 16
                        radius: 14
                        color: mine ? JD.accentBlue : "#2c2c2e"
                        HoverHandler { id: bubbleHover }
                        // копирует сообщение целиком: с кодом внутри это чаще всего и нужно
                        Rectangle {
                            visible: bubbleHover.hovered && !mine
                            anchors { right: parent.right; top: parent.top; margins: 6 }
                            width: cp.implicitWidth + 14; height: 22; radius: 11; color: JD.fill2
                            Text { id: cp; anchors.centerIn: parent; text: copied.running ? JD.tr("Скопировано") : JD.tr("Копировать")
                                   color: JD.text1; font.pixelSize: 11 }
                            Timer { id: copied; interval: 1200 }
                            TapHandler { onTapped: { Quickshell.execDetached(["wl-copy", modelData.text]); copied.restart() } }
                        }
                        TextEdit {
                            id: body
                            anchors { left: parent.left; top: parent.top; margins: 12; topMargin: 8 }
                            width: parent.width - 24
                            readOnly: true; selectByMouse: true
                            textFormat: mine ? Text.PlainText : Text.MarkdownText
                            text: mine ? modelData.text : win.noRemoteImages(modelData.text)
                            wrapMode: TextEdit.Wrap
                            color: mine ? "#ffffff" : JD.text1
                            font.family: JD.fontFamily; font.pixelSize: 14
                            // Ссылки (источники из поиска) раньше не нажимались вовсе. Открываем только
                            // http(s): `file:` или `data:` из текста модели открыли бы у него что угодно.
                            onLinkActivated: link => { if (/^https?:\/\//i.test(link)) Qt.openUrlExternally(link) }
                            HoverHandler { cursorShape: body.hoveredLink ? Qt.PointingHandCursor : Qt.IBeamCursor }
                            // ширину задаёт самая длинная строка, но не шире окна
                            Component.onCompleted: width = Math.min(implicitWidth, win.width - 120)
                        }
                    }
                }
                Text {
                    visible: !JD.chatCurrent
                    anchors.centerIn: parent
                    text: JD.tr("Выбери чат слева или начни новый")
                    color: JD.text3; font.family: JD.fontFamily; font.pixelSize: 14
                }
            }
            Text {
                visible: JD.chatBusy
                Layout.leftMargin: 20
                text: JD.tr("Печатает…"); color: JD.text3; font.family: JD.fontFamily; font.pixelSize: 12
            }
            // Модель этого чата: подписка одна на всё, поэтому по умолчанию — как у голоса, сильнее — по выбору
            Row {
                visible: !!JD.chatCurrent
                Layout.leftMargin: 14; spacing: 6
                Repeater {
                    model: [["", JD.tr("Как у голоса")], ["haiku", "Haiku"], ["sonnet", "Sonnet"], ["opus", "Opus"]]
                    delegate: Rectangle {
                        required property var modelData
                        readonly property bool on: JD.chatModel === modelData[0]
                        height: 24; width: chipLbl.implicitWidth + 18; radius: 12
                        color: on ? JD.accentBlue : JD.fill1
                        Text { id: chipLbl; anchors.centerIn: parent; text: parent.modelData[1]; font.family: JD.fontFamily; font.pixelSize: 12
                               color: parent.on ? "#ffffff" : JD.text2 }
                        TapHandler { onTapped: JD.chatSetModel(parent.modelData[0]) }
                    }
                }
            }
            // Enter — отправить, Shift+Enter — перенос
            Rectangle {
                Layout.fillWidth: true; Layout.margins: 12
                implicitHeight: Math.min(160, Math.max(44, input.contentHeight + 24)); radius: 14; color: JD.fill1
                enabled: !!JD.chatCurrent
                TextEdit {
                    id: input
                    anchors { left: parent.left; right: mic.left; top: parent.top; bottom: parent.bottom; margins: 12 }
                    wrapMode: TextEdit.Wrap
                    color: JD.text1; font.family: JD.fontFamily; font.pixelSize: 14
                    Keys.onPressed: (e) => {
                        // картинку из буфера QML не видит; демон сохранит её в файл и вернёт путь.
                        // Нажатие не забираем: если в буфере ещё и текст, он вставится как обычно
                        if (e.matches(StandardKey.Paste)) JD.send({ cmd: "chat_image" })
                        if ((e.key === Qt.Key_Return || e.key === Qt.Key_Enter) && !(e.modifiers & Qt.ShiftModifier)) {
                            JD.chatSend(text); text = ""; e.accepted = true
                        }
                    }
                    Text { visible: !input.text; text: JD.tr("Сообщение"); color: JD.text3; font: input.font }
                }
                // файл, брошенный на поле, становится путём в сообщении: мозг сам откроет его через Read
                DropArea {
                    anchors.fill: parent
                    onDropped: (drop) => {
                        for (const u of drop.urls || []) {
                            const path = decodeURIComponent(String(u).replace(/^file:\/\//, ""))
                            JD.chatInsert(/\.(png|jpe?g|webp|gif)$/i.test(path) ? "[картинка: " + path + "]" : path)
                        }
                        drop.accept()
                    }
                }
                // Диктовка в поле, без озвучки ответа. Второе нажатие — «я договорил».
                Rectangle {
                    id: mic
                    anchors { right: parent.right; rightMargin: 8; bottom: parent.bottom; bottomMargin: 8 }
                    width: 28; height: 28; radius: 14
                    color: JD.chatDictating ? JD.accentRed : (micHover.hovered ? JD.fill2 : "transparent")
                    Accessible.role: Accessible.Button
                    Accessible.name: JD.chatDictating ? JD.tr("Остановить диктовку") : JD.tr("Надиктовать")
                    Icon { anchors.centerIn: parent; name: "mic"; implicitSize: 16; tint: JD.chatDictating ? "#ffffff" : JD.text2 }
                    HoverHandler { id: micHover; cursorShape: Qt.PointingHandCursor }
                    TapHandler { onTapped: JD.chatDictate() }
                }
            }
        }
    }
}
