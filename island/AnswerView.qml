// Вынесено из shell.qml (Р-80).
import QtQuick
import QtQuick.Layouts

View {
    implicitWidth: 600
    implicitHeight: Math.min(430, answerText.implicitHeight + 116)
    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 18
        spacing: 12
        RowLayout {
            spacing: 10
            Ring { size: 18 }
            Label1 { text: JD.assistantName; Layout.fillWidth: true }
            Label2 {
                text: JD.dstate === "speaking" ? JD.tr("говорит")
                    : JD.dstate === "listening" ? JD.tr("слушает продолжение") : ""
            }
            Waveform {
                visible: JD.dstate === "listening"
                Layout.preferredWidth: 40; Layout.preferredHeight: 20
            }
            // Выделено что-то — кнопка забирает выделенное и остаётся на месте: человек
            // продолжает читать. Не выделено — забирает весь ответ и уходит, как раньше.
            IconButton {
                icon: "edit-copy"; size: 26
                onClicked: {
                    answerText.take()
                    if (!answerText.picked) JD.answerOpen = false
                }
            }
        }
        Flickable {
            id: answerScroll
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentHeight: answerText.implicitHeight
            clip: true
            // Тянуть мышью здесь значит выделять, а не листать: иначе Flickable перехватывает
            // движение на полпути, и выделение обрывается ровно там, где человек разогнался.
            // Листать остаётся колесо — им тут и листают.
            interactive: false
            WheelHandler {
                onWheel: event => {
                    const room = Math.max(0, answerScroll.contentHeight - answerScroll.height)
                    answerScroll.contentY = Math.max(0, Math.min(room,
                        answerScroll.contentY - event.angleDelta.y))
                    event.accepted = true
                }
            }
            SelectableText {
                id: answerText
                width: parent.width
                text: JD.answer
                TextSwap on text {}
            }

            // Кнопка у самого выделения, а не только в заголовке. Выделяют в середине длинного
            // ответа, и путь «выдели — доведи курсор до угла карточки — нажми» длиннее самого
            // выделения. Так это сделано везде, где текст выделяют мышью, и по той же причине.
            Rectangle {
                id: pickCopy
                parent: answerScroll
                visible: answerText.picked
                width: pickRow.implicitWidth + 20
                height: 28
                radius: 14
                z: 3
                color: Qt.rgba(0, 0, 0, 0.92)
                border.width: 1
                border.color: Qt.rgba(1, 1, 1, 0.16)
                x: Math.max(0, Math.min(answerScroll.width - width, answerText.pickRect.x - 10))
                y: Math.max(0, answerText.pickRect.y - answerScroll.contentY - height - 6)
                Row {
                    id: pickRow
                    anchors.centerIn: parent
                    spacing: 7
                    Icon { anchors.verticalCenter: parent.verticalCenter; name: "edit-copy"; implicitSize: 14 }
                    Label1 { anchors.verticalCenter: parent.verticalCenter; text: JD.tr("Скопировать"); font.pixelSize: 12 }
                }
                HoverHandler { cursorShape: Qt.PointingHandCursor }
                TapHandler {
                    gesturePolicy: TapHandler.ReleaseWithinBounds
                    onTapped: answerText.take()
                }
            }
        }
        // reply: opens the text field (or press the shortcut)
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: 34
            radius: 17
            color: replyHover.hovered ? JD.fill2 : JD.fill1
            Behavior on color { enabled: JD.animOn; ColorAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
            RowLayout {
                anchors { fill: parent; leftMargin: 14; rightMargin: 12 }
                Label2 { text: JD.tr("Ответить…"); color: JD.text3; Layout.fillWidth: true }
                Label2 { text: JD.hotkeys.type || ""; color: JD.text3; font.pixelSize: 11 }
            }
            HoverHandler { id: replyHover; cursorShape: Qt.IBeamCursor }
            TapHandler { onTapped: JD.openCompose() }
        }
    }
}
