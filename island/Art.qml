// Вынесено из shell.qml (Р-80).
import QtQuick
import Quickshell.Widgets

// album cover (a file or a YouTube thumbnail link), cropped to a rounded square
ClippingRectangle {
    id: art
    property string src: ""
    property color tint: JD.text1     // the track's colour, for the placeholder
    property real size: 26
    implicitWidth: size
    implicitHeight: size
    radius: Math.min(Math.round(size * 0.24), 16)
    color: JD.fill2
    // no cover yet (a local file, a station): a record-sleeve gradient, not a grey file icon
    Rectangle {
        anchors.fill: parent
        visible: artImg.status !== Image.Ready
        gradient: Gradient {
            GradientStop { position: 0; color: Qt.rgba(art.tint.r, art.tint.g, art.tint.b, 0.30) }
            GradientStop { position: 1; color: Qt.rgba(art.tint.r, art.tint.g, art.tint.b, 0.10) }
        }
        Icon { anchors.centerIn: parent; name: "music"; implicitSize: art.size * 0.46; opacity: 0.75 }
    }
    Image {
        id: artImg
        anchors.fill: parent
        // MPRIS отдаёт обложку готовым адресом «file:///…». Здесь ему приклеивали второй
        // file://, картинка не грузилась, и у чужого плеера вместо обложки всегда была нота.
        source: !art.src ? "" : /^(https?|file|data|image):/.test(art.src) ? art.src : "file://" + art.src
        sourceSize.height: art.size * 2
        fillMode: Image.PreserveAspectCrop
        asynchronous: true
        opacity: status === Image.Ready ? 1 : 0
        Behavior on opacity { enabled: JD.animOn; NumberAnimation { duration: JD.dur(260); easing.type: JD.easeOut } }
    }
}

// equaliser bars in the cover's colour; they settle down when the music pauses
