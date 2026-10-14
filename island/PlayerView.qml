// Вынесено из shell.qml (Р-80).
import QtQuick
import QtQuick.Layouts

// the big player: cover, title, progress, shuffle · prev · play · next · repeat, the queue
View {
    id: pl
    readonly property var p: JD.player || ({})
    property color tint: JD.artTint(p.color)
    Behavior on tint { enabled: JD.animOn; ColorAnimation { duration: JD.durSlow; easing.type: JD.easeOut } }
    property real now: Date.now()
    property bool queueOpen: false
    property int volumeWas: 0      // where the mute button came from
    Timer { interval: 250; repeat: true; running: pl.visible && !pl.p.paused; onTriggered: pl.now = Date.now() }
    readonly property real pos: { pl.now; return JD.playerPos(Date.now()) }
    // повтор отрезка A–B. ponytail: проверяется раз в 250 мс и только пока карточка плеера открыта
    property real loopA: -1
    property real loopB: -1
    readonly property string trackKey: (p.title || "") + "|" + (p.index || 0)
    onTrackKeyChanged: { loopA = -1; loopB = -1 }
    // Ручку нельзя протащить за соседнюю: между A и B остаётся хотя бы секунда.
    function moveMark(which, sec) {
        const dur = p.duration || 0
        if (which === "A") loopA = Math.max(0, Math.min(sec, loopB - 1))
        else loopB = Math.min(dur, Math.max(sec, loopA + 1))
    }
    onPosChanged: if (loopA >= 0 && loopB > loopA && pos >= loopB && !p.paused) {
        JD.media("seek", loopA); optimistic({ pos: loopA })
    }
    readonly property var upcoming: (p.queue || []).filter(q => q.i >= (p.index || 0))
    implicitWidth: 540
    implicitHeight: plCol.implicitHeight + 36
    onShownChanged: if (!shown) queueOpen = false
    function optimistic(change) { JD.player = Object.assign({}, JD.player, change); JD.playerAt = Date.now() }
    // the cover's colour glows through from the top
    // Скругление то же, что у острова (30): подложка была прямоугольной, и её верхние углы торчали
    // из-под дуги карточки (Р-46). `clip` у острова обрезает по прямоугольнику, а не по дуге.
    Rectangle {
        anchors.fill: parent
        radius: 30
        gradient: Gradient {
            GradientStop { position: 0; color: Qt.rgba(pl.tint.r, pl.tint.g, pl.tint.b, 0.26) }
            GradientStop { position: 0.6; color: "transparent" }
        }
    }
    // колесо над плеером — громкость, как над любым плеером
    WheelHandler {
        onWheel: e => {
            const v = Math.max(0, Math.min(100, (pl.p.volume || 0) + (e.angleDelta.y > 0 ? 5 : -5)))
            JD.media("volume", v); pl.optimistic({ volume: v })
        }
    }
    ColumnLayout {
        id: plCol
        anchors { left: parent.left; right: parent.right; top: parent.top; margins: 18 }
        spacing: 10
        // Главное меню — вторая страница той же карточки: значок-сетка никто не находил (Р2-30).
        // «Сейчас играет» и «Медиатека» — два вида одного плеера, а «Островок» — выход из него. Третьим
        // сегментом он выглядел как ещё один вид, и нажатие «выкидывало» из выбора (13 окт, п.5).
        Row {
            Layout.alignment: Qt.AlignHCenter
            spacing: 8
            Rectangle {
                width: pageRow.implicitWidth + 4; height: 28
                radius: 14; color: Qt.rgba(1, 1, 1, 0.08)
                Row {
                    id: pageRow
                    anchors.centerIn: parent; spacing: 2
                    Repeater {
                        model: [{ l: JD.tr("Сейчас играет"), cur: JD.playerPage === "now", page: "now" },
                                { l: JD.tr("Медиатека"), cur: JD.playerPage === "library", page: "library" }]
                        Rectangle {
                            required property var modelData
                            width: pageText.implicitWidth + 24; height: 24; radius: 12
                            color: modelData.cur ? Qt.rgba(1, 1, 1, 0.18) : "transparent"
                            Text { id: pageText; anchors.centerIn: parent; text: modelData.l; font.pixelSize: 12
                                   color: modelData.cur ? "#ffffff" : Qt.rgba(1, 1, 1, 0.7) }
                            TapHandler { enabled: !modelData.cur; onTapped: {
                                JD.playerPage = modelData.page; if (modelData.page === "library") JD.libRefresh()
                            } }
                            HoverHandler { cursorShape: modelData.cur ? Qt.ArrowCursor : Qt.PointingHandCursor }
                        }
                    }
                }
            }
            Rectangle {
                width: islandText.implicitWidth + 24; height: 28; radius: 14
                color: islandHover.hovered ? Qt.rgba(1, 1, 1, 0.14) : Qt.rgba(1, 1, 1, 0.08)
                Text { id: islandText; anchors.centerIn: parent; text: JD.tr("Островок"); font.pixelSize: 12
                       color: Qt.rgba(1, 1, 1, 0.7) }
                TapHandler { onTapped: { JD.playerOpen = false; JD.expanded = true } }
                HoverHandler { id: islandHover; cursorShape: Qt.PointingHandCursor }
            }
        }
        MusicLibrary {
            visible: JD.playerPage === "library"
            Layout.fillWidth: true
            tint: pl.tint
        }
        ColumnLayout {
            id: nowPage
            visible: JD.playerPage !== "library"
            Layout.fillWidth: true
            spacing: 10
        // the cover, large: a tap on the small one opens it, a tap on it puts it back
        Item {
            Layout.fillWidth: true
            // plCol's width, not its own: a hidden item in a layout has none, and would never grow back
            Layout.preferredHeight: JD.artOpen ? plCol.width : 0
            visible: Layout.preferredHeight > 1
            clip: true
            Behavior on Layout.preferredHeight { enabled: JD.animOn; NumberAnimation { duration: JD.dur(JD.slideMs); easing.type: JD.easeOut } }
            Art {
                width: plCol.width; height: plCol.width
                size: plCol.width
                tint: pl.tint; src: pl.p.thumb || ""
                opacity: JD.artOpen ? 1 : 0
                scale: JD.artOpen ? 1 : 0.92
                Behavior on opacity { enabled: JD.animOn; NumberAnimation { duration: JD.dur(240); easing.type: JD.easeOut } }
                Behavior on scale { enabled: JD.animOn; NumberAnimation { duration: JD.dur(JD.slideMs); easing.type: JD.easeOut } }
            }
            HoverHandler { cursorShape: Qt.PointingHandCursor }
            TapHandler { onTapped: JD.artOpen = false }
        }
        RowLayout {
            spacing: 14
            Art {
                size: 84; tint: pl.tint; src: pl.p.thumb || ""
                visible: !JD.artOpen
                HoverHandler { cursorShape: Qt.PointingHandCursor }
                TapHandler { onTapped: JD.artOpen = true }
            }
            ColumnLayout {
                spacing: 2
                Layout.fillWidth: true
                Label2 {
                    visible: !!pl.p.source
                    text: (pl.p.source || "").toUpperCase()
                    color: pl.tint; font.pixelSize: 10; font.weight: Font.DemiBold; font.letterSpacing: 0.6
                    Layout.fillWidth: true
                }
                Label1 { text: pl.p.title || ""; TextSwap on text {} font.pixelSize: 18; wrapMode: Text.Wrap; maximumLineCount: 2; Layout.fillWidth: true }
                Label2 { text: pl.p.artist || ""; TextSwap on text {} font.pixelSize: 13; Layout.fillWidth: true }
            }
            IconButton { icon: "go-up"; size: 26; Layout.alignment: Qt.AlignTop; Layout.rightMargin: -5; onClicked: JD.playerOpen = false }
        }
        JSlider {
            Layout.fillWidth: true
            Layout.topMargin: 4
            tint: pl.tint
            value: pl.p.duration > 0 ? pl.pos / pl.p.duration : 0
            markA: pl.loopB > pl.loopA && pl.p.duration > 0 ? pl.loopA / pl.p.duration : -1
            markB: pl.loopB > pl.loopA && pl.p.duration > 0 ? pl.loopB / pl.p.duration : -1
            onMarkMoved: (which, frac) => pl.moveMark(which, frac * (pl.p.duration || 0))
            onMarkCleared: { pl.loopA = -1; pl.loopB = -1 }
            onMoved: frac => { const to = frac * (pl.p.duration || 0); JD.media("seek", to); pl.optimistic({ pos: to }) }
        }
        RowLayout {
            Layout.topMargin: -8
            Label2 { text: JD.fmtTime(pl.pos); color: JD.text3; font.pixelSize: 11; font.features: { "tnum": 1 } }
            Item { Layout.fillWidth: true }
            Label2 { text: "−" + JD.fmtTime((pl.p.duration || 0) - pl.pos); color: JD.text3; font.pixelSize: 11; font.features: { "tnum": 1 } }
        }
        RowLayout {
            spacing: 10
            Item { Layout.fillWidth: true }
            ModeButton {
                icon: "media-playlist-shuffle"; on: !!pl.p.shuffle; tint: pl.tint
                onClicked: { JD.media("shuffle", pl.p.shuffle ? "off" : "on"); pl.optimistic({ shuffle: !pl.p.shuffle }) }
            }
            Item { implicitWidth: 6 }
            IconButton { icon: "media-skip-backward"; size: 40; onClicked: JD.media("prev") }
            Pressable {
                implicitWidth: 56; implicitHeight: 56; radius: 28
                color: hovered ? Qt.lighter(pl.tint, 1.15) : pl.tint
                PlayGlyph { anchors.centerIn: parent; paused: !!pl.p.paused; size: 20; tint: "black" }
                onClicked: { JD.media("toggle"); pl.optimistic({ pos: pl.pos, paused: !pl.p.paused }) }
            }
            IconButton { icon: "media-skip-forward"; size: 40; onClicked: JD.media("next") }
            Item { implicitWidth: 6 }
            ModeButton {
                icon: pl.p.repeat === "one" ? "media-repeat-single" : "media-playlist-repeat"
                on: !!pl.p.repeat && pl.p.repeat !== "off"
                tint: pl.tint
                onClicked: {
                    const next = ({ off: "all", all: "one", one: "off" })[pl.p.repeat || "off"]
                    JD.media("repeat", next); pl.optimistic({ repeat: next })
                }
            }
            // повтор отрезка: включил — на ползунке появились ручки A и B, тяни их
            ModeButton {
                icon: "brackets"; on: pl.loopB > pl.loopA; tint: pl.tint
                onClicked: {
                    if (pl.loopB > pl.loopA) { pl.loopA = -1; pl.loopB = -1; return }
                    const dur = pl.p.duration || 0
                    if (dur < 3) return
                    pl.loopA = Math.min(pl.pos, dur - 2); pl.loopB = Math.min(dur, pl.loopA + Math.max(5, dur * 0.1))
                }
            }
            Item { Layout.fillWidth: true }
        }
        // how loud the music is — mpv's own volume, not the system's
        RowLayout {
            Layout.topMargin: 2
            Layout.leftMargin: 4
            Layout.rightMargin: 4
            spacing: 10
            Icon {
                name: (pl.p.volume || 0) === 0 ? "audio-volume-muted" : "audio-volume-high"
                implicitSize: 15; tint: JD.text3
                TapHandler { onTapped: { const was = pl.p.volume || 0
                                         JD.media("volume", was > 0 ? 0 : (pl.volumeWas || 70))
                                         pl.optimistic({ volume: was > 0 ? 0 : (pl.volumeWas || 70) }); pl.volumeWas = was } }
                HoverHandler { cursorShape: Qt.PointingHandCursor }
            }
            JSlider {
                Layout.fillWidth: true
                live: true
                thickness: 3
                tint: Qt.rgba(pl.tint.r, pl.tint.g, pl.tint.b, 0.75)
                value: (pl.p.volume || 0) / 100
                onMoved: frac => { const v = Math.round(frac * 100); JD.media("volume", v); pl.optimistic({ volume: v }) }
            }
            Label2 {
                text: Math.round(pl.p.volume || 0) + "%"
                color: JD.text3; font.pixelSize: 11; font.features: { "tnum": 1 }
                Layout.minimumWidth: 34; horizontalAlignment: Text.AlignRight
            }
        }
        // queue · folder · stop
        RowLayout {
            spacing: 8
            Rectangle {
                implicitWidth: qRow.implicitWidth + 22; implicitHeight: 30; radius: 15
                color: pl.queueOpen ? JD.fill2 : (qHover.hovered ? JD.fill2 : JD.fill1)
                RowLayout {
                    id: qRow
                    anchors.centerIn: parent
                    spacing: 6
                    Icon { name: "view-media-playlist"; implicitSize: 15 }
                    Label2 {
                        text: pl.upcoming.length > 1 ? JD.tr("Далее: ") + pl.upcoming[1].title + (pl.p.count - pl.p.index - 1 > 1 ? "  +" + (pl.p.count - pl.p.index - 2) : "")
                                                     : JD.tr("Очередь пуста")
                        color: JD.text2; Layout.maximumWidth: 300
                    }
                    Icon { name: pl.queueOpen ? "go-up" : "go-down"; implicitSize: 12; visible: (pl.p.count || 0) > 1 }
                }
                HoverHandler { id: qHover; cursorShape: Qt.PointingHandCursor }
                TapHandler { onTapped: if ((pl.p.count || 0) > 1) pl.queueOpen = !pl.queueOpen }
            }
            Item { Layout.fillWidth: true }
            IconButton { icon: "media-playback-stop"; size: 30; onClicked: { JD.media("stop"); JD.playerOpen = false } }
        }
        // the queue: tap a song to play it
        ListView {
            id: qList
            visible: pl.queueOpen
            Layout.fillWidth: true
            implicitHeight: Math.min(6, count) * 44
            clip: true
            spacing: 2
            model: pl.queueOpen ? (pl.p.queue || []) : []
            boundsBehavior: Flickable.StopAtBounds
            onVisibleChanged: if (visible) positionViewAtIndex(Math.max(0, (pl.p.queue || []).findIndex(q => q.i === pl.p.index)), ListView.Beginning)
            delegate: Rectangle {
                required property var modelData
                readonly property bool current: modelData.i === pl.p.index
                width: qList.width
                height: 42
                radius: 10
                color: current ? Qt.rgba(pl.tint.r, pl.tint.g, pl.tint.b, 0.16) : (rowHover.hovered ? JD.fill1 : "transparent")
                opacity: modelData.i < pl.p.index ? 0.45 : 1
                RowLayout {
                    anchors { fill: parent; leftMargin: 8; rightMargin: 12 }
                    spacing: 10
                    Art { size: 30; tint: pl.tint; src: modelData.thumb || "" }
                    ColumnLayout {
                        spacing: 0
                        Layout.fillWidth: true
                        Label1 { text: modelData.title; font.weight: current ? Font.DemiBold : Font.Normal; color: current ? pl.tint : JD.text1; Layout.fillWidth: true }
                        Label2 { text: modelData.artist || ""; visible: !!modelData.artist; font.pixelSize: 11; Layout.fillWidth: true }
                    }
                    EqBars { visible: current; tint: pl.tint; playing: !pl.p.paused }
                }
                HoverHandler { id: rowHover; cursorShape: Qt.PointingHandCursor }
                TapHandler { onTapped: JD.media("jump", modelData.i) }
            }
        }
        }
    }
}

// свёрнутый кадр: ролик играет дальше, а экран свободен — как пилюля музыки
