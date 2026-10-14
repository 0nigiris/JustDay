// Вынесено из shell.qml (Р-80).
import QtQuick
import QtQuick.Layouts

// one row of the sound card: icon (a tap mutes) · name · a track to drag or click · the level
Item {
    id: vr
    property real value: 0          // 0…1
    property string icon: "audio-volume-high"
    property string label: ""
    property color tint: JD.accentBlue
    signal moved(real v)
    signal muteToggled()
    readonly property real shown: vrTrack.shown
    Layout.fillWidth: true
    implicitHeight: 30
    RowLayout {
        anchors.fill: parent
        spacing: 10
        Rectangle {
            implicitWidth: 30; implicitHeight: 30; radius: 15
            color: vrMute.containsMouse ? JD.fill2 : "transparent"
            Icon { anchors.centerIn: parent; name: vr.shown === 0 ? "audio-volume-muted" : vr.icon; implicitSize: 16; tint: vr.tint }
            MouseArea { id: vrMute; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: vr.muteToggled() }
        }
        Label1 { text: vr.label; font.pixelSize: 13; font.weight: Font.Medium; Layout.preferredWidth: 86 }
        JSlider {
            id: vrTrack
            Layout.fillWidth: true
            implicitHeight: 30
            knob: true
            live: true
            thickness: 6
            tint: vr.tint
            value: vr.value
            onMoved: v => vr.moved(v)
        }
        Label2 {
            text: Math.round(vr.shown * 100) + "%"
            color: JD.text2; font.pixelSize: 12; font.features: { "tnum": 1 }
            horizontalAlignment: Text.AlignRight; Layout.preferredWidth: 38
        }
    }
}
