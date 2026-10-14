// Вынесено из shell.qml (Р-80).
import QtQuick
import QtQuick.Layouts

RowLayout {
    property string icon: ""
    property string title: ""
    property string subtitle: ""
    property color tint: JD.accentBlue
    spacing: 12
    Rectangle {
        implicitWidth: 34; implicitHeight: 34; radius: 10
        color: Qt.rgba(tint.r, tint.g, tint.b, 0.18)
        Icon { anchors.centerIn: parent; name: icon; implicitSize: 20 }
    }
    ColumnLayout {
        spacing: 1
        Layout.fillWidth: true
        Label1 { text: title; TextSwap on text {} font.pixelSize: 14; Layout.fillWidth: true }
        Label2 { text: subtitle; TextSwap on text {} visible: !!subtitle; Layout.fillWidth: true }
    }
}
