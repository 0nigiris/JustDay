// Вынесено из shell.qml (Р-80).
import QtQuick
import QtQuick.Layouts

Pressable {
    id: chip
    property string icon: ""
    property string label: ""
    property color tint: JD.fill1
    implicitWidth: chipRow.implicitWidth + 24
    implicitHeight: 34
    radius: 17
    color: hovered ? Qt.lighter(tint === JD.fill1 ? "#262628" : tint, 1.2) : tint
    Behavior on color { enabled: JD.animOn; ColorAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
    RowLayout {
        id: chipRow
        anchors.centerIn: parent
        spacing: 7
        Icon { visible: !!chip.icon; name: chip.icon; implicitSize: 15 }
        Label1 { text: chip.label; font.pixelSize: 12; font.weight: Font.Medium }
    }
}

// one row of the sound card: icon (a tap mutes) · name · a track to drag or click · the level
