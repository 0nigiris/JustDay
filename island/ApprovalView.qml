// Вынесено из shell.qml (Р-80).
import QtQuick
import QtQuick.Layouts

View {
    implicitWidth: 580
    implicitHeight: approvalCol.implicitHeight + 36
    ColumnLayout {
        id: approvalCol
        anchors { left: parent.left; right: parent.right; top: parent.top; margins: 18 }
        spacing: 14
        CardHeader { icon: "dialog-warning"; title: JD.tr("Нужно подтверждение"); subtitle: JD.approvalReason; tint: JD.accentOrange; Layout.fillWidth: true }
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: cmd.implicitHeight + 20
            radius: 12
            color: JD.fill1
            Text {
                id: cmd
                anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: 12 }
                text: JD.approvalText
                wrapMode: Text.WrapAnywhere
                maximumLineCount: 6
                elide: Text.ElideRight
                color: JD.text1
                font.family: "monospace"
                font.pixelSize: 12
                textFormat: Text.PlainText
            }
        }
        RowLayout {
            Layout.alignment: Qt.AlignRight
            spacing: 10
            PillButton { label: JD.tr("Отклонить"); onClicked: JD.send({ cmd: "deny" }) }
            PillButton { label: JD.tr("Разрешить"); tint: JD.accentOrange; labelColor: "black"; onClicked: JD.send({ cmd: "approve" }) }
        }
    }
}
