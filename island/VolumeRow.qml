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
    // Стоймя: ползунок снизу вверх, сверху проценты, внизу значок. Он просил, чтобы громкость в
    // пульте можно было поставить и вертикально, и горизонтально.
    property bool vertical: false
    signal moved(real v)
    signal muteToggled()
    readonly property real shown: vertical ? vTrack.shown : vrTrack.shown
    Layout.fillWidth: true
    Layout.fillHeight: vertical
    implicitHeight: vertical ? 110 : 30   // стоймя ровно в два ряда плиток: выше — и соседние плитки вытягивались
    implicitWidth: vertical ? 44 : 200
    ColumnLayout {
        visible: vr.vertical
        anchors.fill: parent
        spacing: 6
        Label2 {
            text: Math.round(vr.shown * 100) + "%"
            color: JD.text2; font.pixelSize: 11; font.features: { "tnum": 1 }
            Layout.alignment: Qt.AlignHCenter
        }
        Item {
            id: vBox
            Layout.fillHeight: true
            Layout.fillWidth: true
            JSlider {
                id: vTrack
                anchors.centerIn: parent
                width: vBox.height
                implicitHeight: 30
                rotation: -90      // мышь и клавиши поворачиваются вместе с ним: вверх — громче
                knob: true; live: true; thickness: 6
                tint: JD.text1
                value: vr.value
                onMoved: v => vr.moved(v)
            }
        }
        Rectangle {
            implicitWidth: 30; implicitHeight: 30; radius: 15
            Layout.alignment: Qt.AlignHCenter
            color: vMute.containsMouse ? JD.fill2 : "transparent"
            Icon { anchors.centerIn: parent; name: vr.shown === 0 ? "audio-volume-muted" : vr.icon; implicitSize: 16; tint: vr.tint }
            MouseArea { id: vMute; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: vr.muteToggled() }
        }
    }
    RowLayout {
        visible: !vr.vertical
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
            // Р3-6: три ползунка трёх цветов спорили друг с другом. Как в Пункте управления macOS —
            // дорожка цвета текста, свой цвет несёт только значок слева.
            tint: JD.text1
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
