// Вынесено из shell.qml (Р-80).
import QtQuick
import QtQuick.Layouts

// a desktop notification: ⌄ unfolds the whole text, ✕ lets it go, a tap anywhere else opens the app
View {
    id: nv
    readonly property var n: JD.notification || ({})
    readonly property bool open: JD.notifExpanded
    implicitWidth: open ? 600 : Math.min(580, Math.max(380, nRow.implicitWidth + 36))
    implicitHeight: nCol.implicitHeight + 26
    HoverHandler { id: nvHover; onHoveredChanged: JD.notifHovered = hovered }
    MouseArea {
        anchors.fill: parent
        z: 0
        cursorShape: Qt.PointingHandCursor
        acceptedButtons: Qt.LeftButton
        onClicked: JD.openNotification(JD.notification)
    }
    ColumnLayout {
        id: nCol
        anchors { left: parent.left; right: parent.right; top: parent.top; topMargin: 13; leftMargin: 16; rightMargin: 12 }
        spacing: 10
        RowLayout {
            id: nRow
            spacing: 12
            Rectangle {
                implicitWidth: 38; implicitHeight: 38; radius: 11
                color: JD.fill1
                Layout.alignment: Qt.AlignTop
                Icon { anchors.centerIn: parent; name: nv.n.icon || (nv.n.app || "").toLowerCase(); fallback: "preferences-desktop-notification-bell"; implicitSize: 26 }
            }
            ColumnLayout {
                spacing: 1
                Layout.fillWidth: true
                RowLayout {
                    spacing: 6
                    Label2 { text: nv.n.app || ""; color: JD.text3; font.pixelSize: 11 }
                    Label2 { text: JD.tr("· сейчас"); color: JD.text3; font.pixelSize: 11 }
                    Label2 { visible: JD.notifMore > 0; text: JD.tr("· ещё ") + JD.notifMore; color: JD.accentBlue; font.pixelSize: 11 }
                }
                Label1 { text: nv.n.summary || ""; TextSwap on text {} Layout.fillWidth: true; Layout.maximumWidth: 440 }
                Label2 {
                    visible: !!nv.n.body && !nv.open
                    text: (nv.n.body || "").replace(/\s+/g, " ")
                    TextSwap on text {}
                    wrapMode: Text.Wrap; maximumLineCount: 2
                    Layout.fillWidth: true; Layout.maximumWidth: 440
                }
            }
            // ⌄ и ✕ проявляются при наведении: пока не навёл, на карточке только текст (Р2-38).
            // Прозрачностью, а не visible: иначе ширина карточки прыгала бы под курсором.
            RoundKey {
                visible: !!nv.n.body
                opacity: nvHover.hovered || nv.open ? 1 : 0
                Behavior on opacity { enabled: JD.animOn; NumberAnimation { duration: JD.durFast } }
                Layout.alignment: Qt.AlignTop
                icon: nv.open ? "go-up" : "go-down"
                onClicked: JD.notifExpanded = !JD.notifExpanded
            }
            RoundKey {
                opacity: nvHover.hovered || nv.open ? 1 : 0
                Behavior on opacity { enabled: JD.animOn; NumberAnimation { duration: JD.durFast } }
                Layout.alignment: Qt.AlignTop; icon: "window-close"; onClicked: JD.dismissNotification()
            }
        }
        Row {
            visible: JD.notifButtons.length > 0 && (nvHover.hovered || nv.open)
            spacing: 8
            Layout.alignment: Qt.AlignHCenter
            Repeater {
                model: JD.notifButtons
                delegate: PillButton {
                    required property var modelData
                    label: modelData.text
                    onClicked: JD.runNotificationAction(modelData.id)
                }
            }
        }
        Label2 {
            visible: !nv.open
            text: JD.tr("Нажмите, чтобы открыть ") + (nv.n.app || JD.tr("приложение"))
            color: JD.text3; font.pixelSize: 11
            Layout.alignment: Qt.AlignHCenter
        }
        // unfolded: the whole message, like a long-press preview on a phone
        Rectangle {
            visible: nv.open
            Layout.fillWidth: true
            Layout.rightMargin: 4
            implicitHeight: Math.min(320, fullBody.implicitHeight + 24)
            radius: 14
            color: JD.fill1
            Flickable {
                anchors { fill: parent; margins: 12 }
                contentHeight: fullBody.implicitHeight
                clip: true
                boundsBehavior: Flickable.StopAtBounds
                MouseArea {  // the Flickable keeps clicks on the text for itself: pass them on
                    width: parent.width
                    height: fullBody.implicitHeight
                    cursorShape: Qt.PointingHandCursor
                    onClicked: JD.openNotification(JD.notification)
                }
                Text {
                    id: fullBody
                    width: parent.width
                    text: nv.n.body || ""
                    wrapMode: Text.Wrap
                    color: JD.text1
                    font.family: JD.fontFamily
                    font.pixelSize: 14
                    lineHeight: 1.18
                    textFormat: Text.PlainText
                }
            }
        }
        Label2 {
            visible: nv.open
            text: JD.tr("Нажмите, чтобы открыть ") + (nv.n.app || JD.tr("приложение"))
            color: JD.text3; font.pixelSize: 11
            Layout.alignment: Qt.AlignHCenter
        }
    }
}

// A timer or an alarm going off. One thing to read (what and when), one thing to press (Выключить):
// Live Activities › Offering interactivity — "prefer limiting it to a single element".
