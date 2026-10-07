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
    onVisibleChanged: {
        if (visible) { JD.chatRefresh(); input.forceActiveFocus() }
        else JD.chatOpen = false   // окно закрыли крестиком рамки
    }

    Connections {
        target: JD
        function onChatMessagesChanged() { Qt.callLater(() => list.positionViewAtEnd()) }
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
                            text: modelData.title; elide: Text.ElideRight
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
                        TextEdit {
                            id: body
                            anchors { left: parent.left; top: parent.top; margins: 12; topMargin: 8 }
                            width: parent.width - 24
                            readOnly: true; selectByMouse: true
                            textFormat: mine ? Text.PlainText : Text.MarkdownText
                            text: modelData.text
                            wrapMode: TextEdit.Wrap
                            color: mine ? "#ffffff" : JD.text1
                            font.family: JD.fontFamily; font.pixelSize: 14
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
            // Enter — отправить, Shift+Enter — перенос
            Rectangle {
                Layout.fillWidth: true; Layout.margins: 12
                implicitHeight: Math.min(160, Math.max(44, input.contentHeight + 24)); radius: 14; color: JD.fill1
                enabled: !!JD.chatCurrent
                TextEdit {
                    id: input
                    anchors { fill: parent; margins: 12 }
                    wrapMode: TextEdit.Wrap
                    color: JD.text1; font.family: JD.fontFamily; font.pixelSize: 14
                    Keys.onPressed: (e) => {
                        if ((e.key === Qt.Key_Return || e.key === Qt.Key_Enter) && !(e.modifiers & Qt.ShiftModifier)) {
                            JD.chatSend(text); text = ""; e.accepted = true
                        }
                    }
                    Text { visible: !input.text; text: JD.tr("Сообщение"); color: JD.text3; font: input.font }
                }
            }
        }
    }
}
