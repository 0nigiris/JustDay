// Вынесено из shell.qml (Р-80).
import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Widgets
import QtMultimedia

// a video inside the island (downloaded first; played by Qt right here)
View {
    id: vv
    readonly property var v: JD.video || ({})
    readonly property bool ready: !!v.file
    property bool ended: false
    readonly property bool busyLine: ["listening", "thinking", "speaking", "transcribing"].includes(JD.dstate) || JD.answerOpen
    readonly property bool hearing: JD.dstate === "listening"
    property real smallWidth: 640      // куда вернуться из «во весь экран»
    implicitWidth: JD.videoWidth
    implicitHeight: Math.round(implicitWidth * 9 / 16)
    function grow(w) { JD.setVideoWidth(w); JD.saveVideoWidth() }

    function close() {
        player.stop()
        JD.send({ cmd: "video_state", closed: true })
        JD.video = null
    }
    function popout(fullscreen) {
        const at = player.position / 1000
        player.stop()
        JD.send({ cmd: "video_popout", pos: at, fullscreen: fullscreen })
        JD.video = null
    }
    function seekBy(ms) {
        player.position = Math.max(0, Math.min(player.duration || 0, player.position + ms))
        vv.ended = false
    }
    function toggle() {
        if (vv.ended) { player.position = 0; vv.ended = false; player.play() }
        else if (player.playbackState === MediaPlayer.PlayingState) player.pause()
        else player.play()
    }

    MediaPlayer {
        id: player
        source: vv.ready ? "file://" + vv.v.file : ""
        videoOutput: screenOut
        playbackRate: JD.videoRate
        audioOutput: AudioOutput {
            // своя громкость кадра (колесо над видео), приглушённая, пока ассистент слушает или говорит
            volume: JD.videoVolume * (["listening", "speaking", "approval"].includes(JD.dstate) ? 0.25 : 1.0)
            muted: Quickshell.env("JUSTDAY_ISLAND_MUTE") === "1"  // the headless test stand stays silent
        }
        onSourceChanged: { vv.ended = false; JD.loopA = -1; JD.loopB = -1; if (source.toString() !== "") play() }
        // ролик, который вернули из окна или продолжили, начинается с той же секунды
        onMediaStatusChanged: {
            if (mediaStatus === MediaPlayer.LoadedMedia && (vv.v.start || 0) > 1 && position < 1000)
                position = vv.v.start * 1000
            if (mediaStatus === MediaPlayer.EndOfMedia) {
                if (JD.videoLoop) { position = 0; play() }
                else { vv.ended = true; endTimer.restart() }
            }
        }
        onPlaybackStateChanged: {
            JD.videoPlaying = playbackState === MediaPlayer.PlayingState
            JD.send({ cmd: "video_state", playing: playbackState === MediaPlayer.PlayingState, pos: position / 1000 })
        }
        onPositionChanged: {
            JD.videoPos = position / 1000; JD.videoDur = duration / 1000
            // отрезок A–B: дошли до B — назад к A (пока B не задан, отрезка нет)
            if (JD.loopA >= 0 && JD.loopB > JD.loopA && JD.videoPos >= JD.loopB) position = JD.loopA * 1000
        }
    }
    Timer { id: endTimer; interval: 12000; onTriggered: if (vv.ended) { if (JD.islandHovered) restart(); else vv.close() } }
    Connections {
        target: JD
        function onVideoCommand(action) {
            if (action === "pause") player.pause()
            else if (action === "resume") player.play()
            else if (action === "toggle") vv.toggle()
            else if (action === "restart") { player.position = 0; player.play() }
        }
    }
    HoverHandler { id: vHover }
    readonly property bool chrome: vHover.hovered || player.playbackState !== MediaPlayer.PlayingState

    ClippingRectangle {
        anchors.fill: parent
        radius: 29
        color: "black"

        // while it downloads: the thumbnail, dimmed, with progress
        Image {
            anchors.fill: parent
            visible: !vv.ready
            source: vv.v.thumb ? (vv.v.thumb.startsWith("http") ? vv.v.thumb : "file://" + vv.v.thumb) : ""
            fillMode: Image.PreserveAspectCrop
            asynchronous: true
            opacity: 0.4
        }
        ColumnLayout {
            visible: !vv.ready
            anchors.centerIn: parent
            width: parent.width * 0.6
            spacing: 12
            Ring { size: 34; spinning: true; tint: JD.accentPink; Layout.alignment: Qt.AlignHCenter }
            Rectangle {
                Layout.fillWidth: true
                implicitHeight: 5; radius: 2.5
                color: Qt.rgba(1, 1, 1, 0.18)
                Rectangle { width: parent.width * (vv.v.progress || 0); height: parent.height; radius: 2.5; color: JD.text1
                            Behavior on width { enabled: JD.animOn; NumberAnimation { duration: JD.durBase; easing.type: JD.easeOut } } }
            }
            Label2 { text: JD.tr("Загружаю видео…") + " " + Math.round((vv.v.progress || 0) * 100) + "%"; horizontalAlignment: Text.AlignHCenter; Layout.fillWidth: true }
        }

        VideoOutput { id: screenOut; anchors.fill: parent; visible: vv.ready; fillMode: VideoOutput.PreserveAspectFit }

        TapHandler { enabled: vv.ready; onTapped: vv.toggle(); onDoubleTapped: vv.popout(true) }

        // big play sign while paused / replay at the end
        Rectangle {
            visible: vv.ready && player.playbackState !== MediaPlayer.PlayingState
            anchors.centerIn: parent
            width: 64; height: 64; radius: 32
            color: Qt.rgba(0, 0, 0, 0.55)
            Icon { anchors.centerIn: parent; name: vv.ended ? "media-repeat-single" : "media-playback-start"; implicitSize: 28 }
        }

        // top: title and buttons
        Rectangle {
            anchors { left: parent.left; right: parent.right; top: parent.top }
            height: 84
            opacity: vv.chrome ? 1 : 0
            Behavior on opacity { enabled: JD.animOn; NumberAnimation { duration: JD.durBase; easing.type: JD.easeOut } }
            gradient: Gradient {
                GradientStop { position: 0; color: Qt.rgba(0, 0, 0, 0.82) }
                GradientStop { position: 0.55; color: Qt.rgba(0, 0, 0, 0.45) }
                GradientStop { position: 1; color: "transparent" }
            }
            RowLayout {
                anchors { left: parent.left; right: parent.right; top: parent.top; leftMargin: 24; rightMargin: 16; topMargin: 12 }
                spacing: 8
                ColumnLayout {
                    spacing: 0
                    Layout.fillWidth: true
                    Label1 { text: vv.v.title || ""; Layout.fillWidth: true }
                    Label2 { text: vv.v.channel || ""; visible: !!vv.v.channel; font.pixelSize: 11; Layout.fillWidth: true }
                }
                IconButton {
                    icon: JD.videoBig ? "view-restore" : "view-fullscreen"; size: 28
                    onClicked: { if (JD.videoBig) vv.grow(vv.smallWidth)
                                 else { vv.smallWidth = JD.videoWidth; vv.grow(JD.videoRoom) } }
                }
                IconButton { icon: "window-new"; size: 28; visible: vv.ready; onClicked: vv.popout(false) }
                IconButton { icon: "go-up"; size: 28; visible: vv.ready; onClicked: JD.videoMini = true }
                IconButton { icon: "internet-web-browser"; size: 28; visible: !!vv.v.url && vv.v.url.startsWith("http")
                             onClicked: { Quickshell.execDetached(["xdg-open", vv.v.url + (player.position > 3000 ? "&t=" + Math.floor(player.position / 1000) + "s" : "")]); vv.close() } }
                IconButton { icon: "window-close"; size: 28; onClicked: vv.close() }
            }
        }

        // низ: перемотка, время, прогресс, громкость, скорость, повтор — то, что ждёшь от плеера
        Rectangle {
            id: vctl
            visible: vv.ready
            anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
            height: 96
            opacity: vv.chrome && !vv.busyLine ? 1 : 0
            Behavior on opacity { enabled: JD.animOn; NumberAnimation { duration: JD.durBase; easing.type: JD.easeOut } }
            gradient: Gradient {
                GradientStop { position: 0; color: "transparent" }
                GradientStop { position: 0.35; color: Qt.rgba(0, 0, 0, 0.55) }
                GradientStop { position: 1; color: Qt.rgba(0, 0, 0, 0.92) }
            }
            readonly property bool roomy: vv.width > 560     // на узком кадре остаётся главное
            ColumnLayout {
                anchors { left: parent.left; right: parent.right; bottom: parent.bottom
                          leftMargin: 20; rightMargin: 24; bottomMargin: 10 }
                spacing: 2
                JSlider {
                    Layout.fillWidth: true
                    tint: JD.accentPink
                    value: player.duration > 0 ? player.position / player.duration : 0
                    markA: JD.loopB > JD.loopA && player.duration > 0 ? JD.loopA * 1000 / player.duration : -1
                    markB: JD.loopB > JD.loopA && player.duration > 0 ? JD.loopB * 1000 / player.duration : -1
                    onMarkMoved: (which, frac) => {
                        const sec = frac * player.duration / 1000
                        if (which === "A") JD.loopA = Math.max(0, Math.min(sec, JD.loopB - 1))
                        else JD.loopB = Math.min(player.duration / 1000, Math.max(sec, JD.loopA + 1))
                    }
                    onMarkCleared: { JD.loopA = -1; JD.loopB = -1 }
                    onMoved: frac => { player.position = frac * player.duration; vv.ended = false }
                }
                RowLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    IconButton { icon: "rotate-ccw"; size: 28; onClicked: vv.seekBy(-10000) }
                    IconButton { icon: player.playbackState === MediaPlayer.PlayingState ? "media-playback-pause" : "media-playback-start"
                                 size: 34; onClicked: vv.toggle() }
                    IconButton { icon: "refresh-cw"; size: 28; onClicked: vv.seekBy(10000) }
                    Label2 {
                        text: JD.fmtTime(player.position / 1000) + " / " + JD.fmtTime(player.duration / 1000)
                        color: JD.text1; font.pixelSize: 11; font.features: { "tnum": 1 }
                        Layout.leftMargin: 4
                    }
                    Item { Layout.fillWidth: true }
                    // громкость этого ролика: она запоминается и не трогает ни музыку, ни систему
                    Icon {
                        name: JD.videoVolume === 0 ? "audio-volume-muted" : "audio-volume-high"
                        implicitSize: 15; tint: JD.text2
                        HoverHandler { cursorShape: Qt.PointingHandCursor }
                        TapHandler { onTapped: { JD.setVideoVolume(JD.videoVolume > 0 ? 0 : 1); JD.saveVideoVolume() } }
                    }
                    JSlider {
                        visible: vctl.roomy
                        Layout.preferredWidth: 76
                        live: true
                        thickness: 3
                        tint: Qt.rgba(1, 1, 1, 0.8)
                        value: JD.videoVolume
                        onMoved: frac => JD.setVideoVolume(frac)
                    }
                    // скорость: 0.5 … 2, по кругу
                    Rectangle {
                        visible: vctl.roomy
                        implicitWidth: rateLabel.implicitWidth + 20; implicitHeight: 28; radius: 14
                        color: JD.videoRate === 1 ? (rateHover.hovered ? Qt.rgba(1, 1, 1, 0.22) : Qt.rgba(1, 1, 1, 0.14))
                                                  : Qt.rgba(JD.accentPink.r, JD.accentPink.g, JD.accentPink.b, 0.32)
                        Label1 {
                            id: rateLabel
                            anchors.centerIn: parent
                            font.pixelSize: 12
                            font.weight: Font.DemiBold
                            text: (JD.videoRate % 1 === 0 ? JD.videoRate.toFixed(0) : String(JD.videoRate)) + "×"
                            color: JD.videoRate === 1 ? JD.text1 : JD.accentPink
                        }
                        HoverHandler { id: rateHover; cursorShape: Qt.PointingHandCursor }
                        TapHandler {
                            gesturePolicy: TapHandler.ReleaseWithinBounds
                            onTapped: {
                                const steps = [0.5, 0.75, 1, 1.25, 1.5, 2]
                                JD.videoRate = steps[(steps.indexOf(JD.videoRate) + 1) % steps.length]
                            }
                        }
                    }
                    // повтор отрезка: на ползунке появляются ручки A и B
                    ModeButton {
                        icon: "brackets"; on: JD.loopB > JD.loopA; tint: JD.accentPink
                        implicitWidth: 30; implicitHeight: 30
                        onClicked: {
                            if (JD.loopB > JD.loopA) { JD.loopA = -1; JD.loopB = -1; return }
                            const dur = player.duration / 1000
                            if (dur < 3) return
                            JD.loopA = Math.min(JD.videoPos, dur - 2); JD.loopB = Math.min(dur, JD.loopA + Math.max(5, dur * 0.1))
                            JD.videoLoop = false
                        }
                    }
                    ModeButton {
                        icon: "media-repeat-single"; on: JD.videoLoop; tint: JD.accentPink
                        implicitWidth: 30; implicitHeight: 30
                        onClicked: JD.videoLoop = !JD.videoLoop
                    }
                }
            }
        }

        // колесо — громкость, Ctrl+колесо — размер кадра
        WheelHandler {
            acceptedModifiers: Qt.NoModifier
            onWheel: e => JD.setVideoVolume(JD.videoVolume + (e.angleDelta.y > 0 ? 0.05 : -0.05))
        }
        WheelHandler {
            acceptedModifiers: Qt.ControlModifier
            onWheel: e => { JD.setVideoWidth(JD.videoWidth + (e.angleDelta.y > 0 ? 80 : -80)); JD.saveVideoWidth() }
        }

        // сколько сейчас громкость / какой размер — пока его меняют
        Rectangle {
            anchors { horizontalCenter: parent.horizontalCenter; top: parent.top; topMargin: 96 }
            width: sizeLabel.implicitWidth + 24; height: 28; radius: 14
            color: Qt.rgba(0, 0, 0, 0.7)
            opacity: volumeHint.running || JD.videoResizing ? 1 : 0
            visible: opacity > 0.01
            Behavior on opacity { enabled: JD.animOn; NumberAnimation { duration: JD.durBase; easing.type: JD.easeOut } }
            Label2 {
                id: sizeLabel
                anchors.centerIn: parent
                color: JD.text1
                font.features: { "tnum": 1 }
                text: JD.videoResizing ? Math.round(JD.videoWidth) + " × " + Math.round(JD.videoWidth * 9 / 16)
                                       : JD.tr("Громкость") + " " + Math.round(JD.videoVolume * 100) + "%"
            }
        }
        Timer { id: volumeHint; interval: 1100 }
        Connections { target: JD; function onVideoVolumeChanged() { volumeHint.restart() } }

        // уголок: тянуть — менять размер кадра. Размер запоминается, когда его отпускают
        Item {
            anchors { right: parent.right; bottom: parent.bottom }
            width: 30; height: 30
            opacity: vv.chrome || JD.videoResizing ? 0.85 : 0
            visible: opacity > 0.01
            Behavior on opacity { enabled: JD.animOn; NumberAnimation { duration: JD.durBase; easing.type: JD.easeOut } }
            Repeater {   // три косые чёрточки у самого угла, как у любого окна, которое можно тянуть
                model: 3
                Rectangle {
                    required property int index
                    readonly property real away: 6 + index * 5      // как далеко от угла
                    width: 7 + index * 6; height: 2; radius: 1
                    color: JD.text1
                    rotation: -45
                    x: 30 - away - width / 2
                    y: 30 - away - height / 2
                }
            }
            MouseArea {
                anchors.fill: parent
                cursorShape: Qt.SizeFDiagCursor
                property real fromX: 0
                property real fromWidth: 0
                onPressed: m => {
                    // от точки экрана, а не от своей: уголок уезжает вместе с краем кадра
                    fromX = mapToGlobal(m.x, m.y).x
                    fromWidth = JD.videoWidth
                    JD.videoResizing = true
                }
                // остров растёт в обе стороны от центра: край уходит на половину прибавки
                onPositionChanged: m => { if (pressed) JD.setVideoWidth(fromWidth + 2 * (mapToGlobal(m.x, m.y).x - fromX)) }
                onReleased: { JD.videoResizing = false; JD.saveVideoWidth() }
                onCanceled: { JD.videoResizing = false; JD.saveVideoWidth() }
            }
        }

        // the assistant keeps working over the video: its words run as a caption
        Rectangle {
            anchors { horizontalCenter: parent.horizontalCenter; bottom: parent.bottom; bottomMargin: 16 }
            width: Math.min(parent.width - 48, capRow.implicitWidth + 28)
            height: capRow.implicitHeight + 14
            radius: 14
            color: Qt.rgba(0, 0, 0, 0.72)
            opacity: vv.busyLine ? 1 : 0
            visible: opacity > 0.01
            Behavior on opacity { enabled: JD.animOn; NumberAnimation { duration: JD.durBase; easing.type: JD.easeOut } }
            RowLayout {
                id: capRow
                anchors.centerIn: parent
                width: Math.min(implicitWidth, vv.width - 76)
                spacing: 10
                Ring { visible: !vv.hearing; size: 16; tint: JD.accentOrange }
                Waveform { visible: vv.hearing; Layout.preferredWidth: 42; Layout.preferredHeight: 20 }
                Label1 {
                    text: JD.answerOpen ? JD.answer
                        : vv.hearing ? (JD.activity || JD.tr("Слушаю…"))
                        : (JD.activity || JD.tr("Думаю…"))
                    font.weight: Font.Medium
                    wrapMode: Text.Wrap
                    maximumLineCount: 2
                    Layout.fillWidth: true
                    Layout.maximumWidth: vv.width - 110
                }
            }
        }
    }
}

