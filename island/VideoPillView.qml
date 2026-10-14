// Вынесено из shell.qml (Р-80).
import QtQuick
import QtQuick.Layouts

// свёрнутый кадр: ролик играет дальше, а экран свободен — как пилюля музыки
View {
    id: vp2
    // закрыть ролик умеет только сам VideoView (он гасит mpv и окно), а не пилюля
    signal closeRequested()
    readonly property var v: JD.video || ({})
    implicitWidth: vpRow.implicitWidth + 26
    implicitHeight: 40
    RowLayout {
        id: vpRow
        anchors { left: parent.left; verticalCenter: parent.verticalCenter; leftMargin: 10 }
        spacing: 10
        Rectangle {
            implicitWidth: 26; implicitHeight: 26; radius: 7
            color: Qt.rgba(JD.accentPink.r, JD.accentPink.g, JD.accentPink.b, 0.22)
            Icon { anchors.centerIn: parent; name: "video-x-generic"; implicitSize: 15 }
        }
        Label1 { text: vp2.v.title || JD.tr("Видео"); Layout.maximumWidth: 220 }
        Label2 {
            text: JD.fmtTime(JD.videoPos) + " / " + JD.fmtTime(JD.videoDur)
            font.features: { "tnum": 1 }
            visible: JD.videoDur > 0
        }
        IconButton { icon: JD.videoPlaying ? "media-playback-pause" : "media-playback-start"; size: 26
                     onClicked: JD.videoCommand("toggle") }
        IconButton { icon: "view-fullscreen"; size: 26; onClicked: JD.videoMini = false }
        IconButton { icon: "window-close"; size: 26; onClicked: vp2.closeRequested() }
    }
}
