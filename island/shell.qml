// JustDay Dynamic Island — Quickshell (Qt Quick) layer-shell overlay.
// Talks to the daemon over $XDG_RUNTIME_DIR/justday.sock: `subscribe` for live status, one-shot commands back.
// Run: qs -p <repo>/island        (service: justday-island.service)
import QtQuick
import QtQuick.Layouts
import QtQuick.Shapes
import QtQuick.Effects
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import Quickshell.Widgets
import Quickshell.Services.Mpris
import QtMultimedia

ShellRoot {
    id: root

    // `qs -p <repo>/island ipc call island expand|collapse|toggle|peek` — e.g. bind a key to open the control center
    IpcHandler {
        target: "island"
        function expand(): void { JD.expanded = true }
        function collapse(): void { JD.closeAll() }
        function toggle(): void { JD.expanded = !JD.expanded }
        function settings(): void { JD.openSettings("general") }
        function settingsPage(page: string): void { JD.openSettings(page) }
        function peek(): void { JD.peeking = true; JD.islandHovered = false }
        function status(): string {
            return JSON.stringify({ screen: win.screen ? win.screen.name : null, screens: Quickshell.screens.map(s => s.name + "@" + s.x + "," + s.y),
                                    connected: JD.connected, dstate: JD.dstate, mode: JD.mode, visible: win.visible,
                                    island: [island.x, island.y, island.width, island.height, island.opacity] })
        }
        function snapshot(path: string): void { island.grabToImage(r => r.saveToFile(path)) }
    }

    // test backdrop (JUSTDAY_ISLAND_WALLPAPER=1 or a picture path): a "wallpaper" so the black island is visible in headless sessions
    Loader {
        active: !!Quickshell.env("JUSTDAY_ISLAND_WALLPAPER")
        sourceComponent: PanelWindow {
            anchors { top: true; bottom: true; left: true; right: true }
            exclusionMode: ExclusionMode.Ignore
            WlrLayershell.layer: WlrLayer.Background
            color: "#1d2b53"
            Rectangle {
                anchors.fill: parent
                gradient: Gradient {
                    orientation: Gradient.Horizontal
                    GradientStop { position: 0; color: "#355c7d" }
                    GradientStop { position: 0.5; color: "#c06c84" }
                    GradientStop { position: 1; color: "#f8b195" }
                }
            }
            Image {
                anchors.fill: parent
                visible: Quickshell.env("JUSTDAY_ISLAND_WALLPAPER") !== "1"
                source: visible ? "file://" + Quickshell.env("JUSTDAY_ISLAND_WALLPAPER") : ""
                fillMode: Image.PreserveAspectCrop
            }
        }
    }

    // ───────────── window ─────────────
    PanelWindow {
        id: win
        screen: Quickshell.screens.find(s => s.name === (JD.island.screen || Quickshell.env("JUSTDAY_ISLAND_SCREEN")))
                || Quickshell.screens.find(s => s.x === 0 && s.y === 0) || Quickshell.screens[0]
        anchors.top: true
        exclusionMode: ExclusionMode.Ignore
        WlrLayershell.layer: WlrLayer.Overlay
        WlrLayershell.namespace: "justday-island"
        readonly property bool big: ["expanded", "settings", "compose", "player"].includes(island.mode)
        // the text field takes the keyboard at once (it was opened by a shortcut); menus only on click
        WlrLayershell.keyboardFocus: island.mode === "compose" ? WlrKeyboardFocus.Exclusive
                                   : big ? WlrKeyboardFocus.OnDemand : WlrKeyboardFocus.None
        implicitWidth: 1000
        implicitHeight: 720
        color: "transparent"

        // clicks pass through everywhere except the island (and the whole area while expanded, to close on outside click)
        mask: Region {
            item: win.big ? backdrop : island
            Region { item: hotZone }
        }

        MouseArea {
            id: backdrop
            anchors.fill: parent
            enabled: win.big
            onClicked: JD.closeAll()
        }

        // thin invisible strip at the very top: hover it to reveal the island
        Item {
            id: hotZone
            width: 420
            height: island.mode === "hidden" && JD.island.hover_reveal !== false ? 3 : 0
            anchors.horizontalCenter: parent.horizontalCenter
            HoverHandler { onHoveredChanged: if (hovered) JD.peeking = true }
        }

        Shortcut { sequence: "Escape"; enabled: win.big; onActivated: JD.closeAll() }

        // ───────────── the island ─────────────
        Rectangle {
            id: island
            readonly property string mode: JD.mode
            readonly property Item content: ({
                expanded: expandedView, settings: settingsHolder, compose: composeView, approval: approvalView, card: cardView, listening: listeningView,
                notification: notificationView, flash: flashView, answer: answerView, transcribing: thinkingView, thinking: thinkingView,
                peek: peekView, hidden: peekView, music: musicView, player: playerView, video: videoView })[mode]
            readonly property bool compact: ["listening", "flash", "transcribing", "thinking", "peek", "hidden", "music"].includes(mode) && !JD.detailOpen

            width: mode === "hidden" ? 140 : Math.max(120, content.implicitWidth)
            height: mode === "hidden" ? 8 : content.implicitHeight
            // corners follow the *animated* height every frame (a pill stays a pill while it grows);
            // only the pill ↔ card transition itself is eased
            property real pill: compact ? 1 : 0
            Behavior on pill { enabled: JD.animOn; NumberAnimation { duration: 280; easing.type: Easing.OutCubic } }
            radius: Math.min(height / 2, pill * height / 2 + (1 - pill) * (mode === "settings" ? 34 : 30))
            anchors.horizontalCenter: parent.horizontalCenter
            y: mode === "hidden" ? -14 : 8
            opacity: mode === "hidden" ? 0 : 1
            scale: mode === "hidden" ? 0.7 : 1
            color: JD.ink
            clip: true
            border.width: 1
            border.color: Qt.rgba(1, 1, 1, win.big ? 0.10 : 0.06)

            Behavior on width { enabled: JD.animOn; SpringAnimation { spring: JD.springK; damping: JD.springDamping; epsilon: 0.3 } }
            Behavior on height { enabled: JD.animOn; SpringAnimation { spring: JD.springK; damping: JD.springDamping; epsilon: 0.3 } }
            Behavior on y { enabled: JD.animOn; SpringAnimation { spring: JD.springK - 0.2; damping: Math.max(0.4, JD.springDamping); epsilon: 0.2 } }
            Behavior on opacity { enabled: JD.animOn; NumberAnimation { duration: 220; easing.type: Easing.OutCubic } }
            Behavior on scale { enabled: JD.animOn; SpringAnimation { spring: JD.springK - 0.2; damping: Math.max(0.42, JD.springDamping); epsilon: 0.005 } }

            HoverHandler { onHoveredChanged: JD.islandHovered = hovered }

            TapHandler {
                enabled: !["expanded", "settings", "approval", "card", "compose", "player", "video"].includes(island.mode)
                onTapped: {
                    if (island.mode === "music") { JD.playerOpen = true; return }
                    if (island.mode === "answer") { JD.answerOpen = false; return }
                    if (island.mode === "notification") { JD.notification = null; return }
                    JD.expanded = true
                }
            }

            // Every view is laid out at its own natural size; the island springs to it and the view follows.
            // The stage is masked to the island's *rounded* shape, so nothing pokes out of the corners while it grows.
            Item {
                id: islandMask
                anchors.fill: parent
                visible: false
                layer.enabled: true
                Rectangle { anchors.fill: parent; radius: island.radius; antialiasing: true }
            }
            Item {
                id: stage
                anchors.fill: parent
                layer.enabled: JD.animOn
                layer.smooth: true
                layer.effect: MultiEffect { maskEnabled: true; maskSource: islandMask; maskThresholdMin: 0.5; maskSpreadAtMin: 1.0 }
                PeekView { id: peekView; shown: island.mode === "peek" }
                MusicView { id: musicView; shown: island.mode === "music" }
                PlayerView { id: playerView; shown: island.mode === "player" }
                VideoView { id: videoView; shown: island.mode === "video" }
                ListeningView { id: listeningView; shown: island.mode === "listening" }
                ThinkingView { id: thinkingView; shown: island.mode === "thinking" || island.mode === "transcribing" }
                FlashView { id: flashView; shown: island.mode === "flash" }
                NotificationView { id: notificationView; shown: island.mode === "notification" }
                AnswerView { id: answerView; shown: island.mode === "answer" }
                ApprovalView { id: approvalView; shown: island.mode === "approval" }
                CardView { id: cardView; shown: island.mode === "card" }
                ExpandedView { id: expandedView; shown: island.mode === "expanded" }
                ComposeView { id: composeView; shown: island.mode === "compose" }
                View {
                    id: settingsHolder
                    shown: island.mode === "settings"
                    implicitWidth: 940
                    implicitHeight: 640
                    Loader {
                        anchors.fill: parent
                        active: settingsHolder.shown || settingsHolder.opacity > 0.01
                        sourceComponent: SettingsView {}
                    }
                }
            }
        }

        // soft shadow under the island. Its source is a plain copy of the shape: with the island itself as the
        // source, the effect draws the island again (border included) and that copy shows as a ring while it grows
        Rectangle {
            id: shadowShape
            width: island.width
            height: island.height
            radius: island.radius
            color: JD.ink
            visible: false
            layer.enabled: true
        }
        MultiEffect {
            source: shadowShape
            anchors.fill: island
            scale: island.scale
            z: -1
            shadowEnabled: true
            shadowColor: Qt.rgba(0, 0, 0, 0.55)
            shadowBlur: 0.9
            shadowVerticalOffset: 6
            opacity: island.opacity
            visible: island.mode !== "hidden"
        }
    }

    // ═════════════════════ building blocks ═════════════════════
    component View: Item {
        id: view
        property bool shown: false
        // how far the island has grown towards this view's size (the island springs, the content rides along):
        // the content fades in over the last part of the growth and settles from 94 % to full size with it
        readonly property real fit: Math.min(1, parent.width / Math.max(1, implicitWidth), parent.height / Math.max(1, implicitHeight))
        readonly property real reveal: JD.animOn ? Math.max(0, Math.min(1, (fit - 0.55) / 0.4)) : 1
        property real fade: shown ? 1 : 0
        Behavior on fade { enabled: JD.animOn; NumberAnimation { duration: view.shown ? 180 : 110; easing.type: Easing.OutCubic } }
        anchors.top: parent.top
        anchors.horizontalCenter: parent.horizontalCenter
        width: implicitWidth
        height: implicitHeight
        transformOrigin: Item.Top
        opacity: shown ? fade * reveal : fade
        scale: 0.94 + 0.06 * (shown ? reveal : fade)
        visible: opacity > 0.01
    }

    // put `TextSwap on text {}` on a Text: a new text fades out the old one and fades itself in
    component TextSwap: Behavior {
        id: sw
        enabled: JD.animOn
        SequentialAnimation {
            NumberAnimation { target: sw.targetProperty.object; property: "opacity"; to: 0; duration: 70; easing.type: Easing.InQuad }
            PropertyAction {}
            NumberAnimation { target: sw.targetProperty.object; property: "opacity"; to: 1; duration: 170; easing.type: Easing.OutCubic }
        }
    }

    component Label1: Text {
        font.family: JD.fontFamily
        color: JD.text1
        font.pixelSize: 13
        font.weight: Font.DemiBold
        elide: Text.ElideRight
        textFormat: Text.PlainText
    }
    component Label2: Text {
        font.family: JD.fontFamily
        color: JD.text2
        font.pixelSize: 12
        elide: Text.ElideRight
        textFormat: Text.PlainText
    }

    // Arc-reactor ring: pulses with the voice, spins while thinking
    component Ring: Item {
        id: ring
        property color tint: JD.accentFor(JD.dstate)
        property real size: 22
        property bool spinning: JD.dstate === "thinking" || JD.dstate === "transcribing"
        implicitWidth: size
        implicitHeight: size
        Rectangle {
            anchors.centerIn: parent
            width: ring.size * (0.42 + 0.3 * Math.min(1, JD.level * (JD.dstate === "listening" ? 1 : 0)))
            height: width
            radius: width / 2
            color: ring.tint
            opacity: 0.9
            Behavior on width { NumberAnimation { duration: 90 } }
            SequentialAnimation on opacity {
                running: JD.dstate === "speaking"
                loops: Animation.Infinite
                NumberAnimation { to: 0.45; duration: 420; easing.type: Easing.InOutSine }
                NumberAnimation { to: 0.95; duration: 420; easing.type: Easing.InOutSine }
            }
        }
        Shape {
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer
            ShapePath {
                strokeColor: ring.tint
                strokeWidth: 2
                fillColor: "transparent"
                capStyle: ShapePath.RoundCap
                PathAngleArc {
                    centerX: ring.size / 2; centerY: ring.size / 2
                    radiusX: ring.size / 2 - 1.5; radiusY: radiusX
                    startAngle: 0
                    sweepAngle: ring.spinning ? 250 : 360
                    Behavior on sweepAngle { NumberAnimation { duration: 300 } }
                }
            }
            RotationAnimation on rotation { running: ring.spinning; loops: Animation.Infinite; from: 0; to: 360; duration: 900 }
        }
    }

    component Icon: IconImage {
        property string name: ""
        property string fallback: "system-run"
        implicitSize: 18
        source: Quickshell.iconPath(name || fallback, fallback)

    }

    component PillButton: Rectangle {
        id: pb
        property string label: ""
        property color tint: JD.fill2
        property color labelColor: JD.text1
        signal clicked()
        implicitWidth: Math.max(88, lbl.implicitWidth + 28)
        implicitHeight: 32
        radius: 16
        color: pbHover.hovered ? Qt.lighter(tint, 1.25) : tint
        scale: pbTap.pressed ? 0.95 : 1
        Behavior on scale { NumberAnimation { duration: 120 } }
        Behavior on color { ColorAnimation { duration: 120 } }
        Text { font.family: JD.fontFamily; id: lbl; anchors.centerIn: parent; text: pb.label; color: pb.labelColor; font.pixelSize: 13; font.weight: Font.DemiBold }
        HoverHandler { id: pbHover; cursorShape: Qt.PointingHandCursor }
        TapHandler { id: pbTap; onTapped: pb.clicked() }
    }

    component IconButton: Rectangle {
        id: ib
        property string icon: ""
        property real size: 30
        signal clicked()
        implicitWidth: size
        implicitHeight: size
        radius: size / 2
        color: ibHover.hovered ? JD.fill2 : JD.fill1
        scale: ibTap.pressed ? 0.9 : 1
        Behavior on scale { NumberAnimation { duration: 120 } }
        Icon { anchors.centerIn: parent; name: ib.icon; implicitSize: ib.size * 0.55 }
        HoverHandler { id: ibHover; cursorShape: Qt.PointingHandCursor }
        TapHandler { id: ibTap; onTapped: ib.clicked() }
    }

    // ───────────── compact views ─────────────
    component PeekView: View {
        id: pv
        readonly property string event: JD.workers > 0 ? JD.tr("Клод работает") + (JD.workers > 1 ? " ×" + JD.workers : "")
                                        : JD.dstate === "offline" ? JD.assistantName + JD.tr(" не запущен")
                                        : JD.nextEvent ? Qt.formatTime(new Date(JD.nextEvent.start), "HH:mm") + " · " + JD.nextEvent.title
                                        : JD.update ? JD.tr("Доступно обновление")
                                        : (JD.island.show_events !== false && JD.history.length && JD.history[0].a) ? JD.history[0].a : ""
        implicitWidth: peekRow.implicitWidth + 32
        implicitHeight: 44
        SystemClock { id: clock; precision: SystemClock.Minutes }
        RowLayout {
            id: peekRow
            anchors.centerIn: parent
            spacing: 12
            Ring { size: 18; tint: JD.workers > 0 ? JD.accentPurple : JD.dstate === "offline" ? JD.accentRed : JD.accentCyan; spinning: JD.workers > 0 }
            Text { text: Qt.formatTime(clock.date, "HH:mm"); color: JD.text1; font.family: JD.fontFamily; font.pixelSize: 16; font.weight: Font.Bold; font.features: { "tnum": 1 } }
            Label2 { text: clock.date.toLocaleDateString(Qt.locale(JD.lang === "ru" ? "ru_RU" : "en_US"), "ddd, d MMM") }
            Rectangle { visible: !!pv.event; implicitWidth: 1; implicitHeight: 18; color: JD.fill2 }
            Label2 { visible: !!pv.event; text: pv.event.replace(/\s+/g, " "); maximumLineCount: 1; wrapMode: Text.NoWrap; Layout.maximumWidth: 260; color: JD.workers > 0 ? JD.accentPurple : JD.text2 }
            Rectangle { visible: !!JD.weather && JD.island.show_weather !== false; implicitWidth: 1; implicitHeight: 18; color: JD.fill2 }
            RowLayout {
                visible: !!JD.weather && JD.island.show_weather !== false
                spacing: 6
                Image { source: JD.weather ? Quickshell.shellDir + "/icons/" + JD.weather.icon + ".svg" : ""; sourceSize: Qt.size(36, 36); Layout.preferredWidth: 18; Layout.preferredHeight: 18 }
                Text { text: JD.weather ? (JD.weather.temp > 0 ? "+" : "") + JD.weather.temp + "°" : ""; color: JD.text1; font.family: JD.fontFamily; font.pixelSize: 14; font.weight: Font.DemiBold }
            }
        }
    }

    component ListeningView: View {
        implicitWidth: 236
        implicitHeight: 40
        RowLayout {
            anchors.fill: parent
            anchors.leftMargin: 12
            anchors.rightMargin: 16
            spacing: 10
            Ring { size: 20 }
            Label1 { text: JD.tr("Слушаю"); Layout.fillWidth: true }
            Waveform { Layout.preferredWidth: 46; Layout.preferredHeight: 22 }
        }
    }

    component Waveform: Item {
        id: wave
        property real t: 0
        FrameAnimation { running: wave.visible; onTriggered: { wave.t += frameTime; JD.level *= Math.pow(0.9, frameTime * 60) } }
        Row {
            anchors.centerIn: parent
            spacing: 3
            Repeater {
                model: 7
                Rectangle {
                    required property int index
                    width: 3.5
                    radius: 2
                    color: JD.accentCyan
                    anchors.verticalCenter: parent.verticalCenter
                    // a slow ripple keeps the bars alive in silence; the voice level drives the rest
                    height: 4 + 3 * (0.5 + 0.5 * Math.sin(wave.t * 4 - index * 0.9))
                            + 15 * Math.min(1, JD.level * (0.55 + 0.45 * Math.abs(Math.sin(wave.t * 9 + index * 1.3))))
                }
            }
        }
    }

    component ThinkingView: View {
        id: tv
        readonly property string line: JD.dstate === "transcribing" ? JD.tr("Распознаю…") : (JD.activity || JD.tr("Думаю…"))
        property int elapsed: 0
        Timer { interval: 1000; repeat: true; running: tv.shown; onTriggered: tv.elapsed = Math.round((Date.now() - JD.busySince) / 1000) }
        TextMetrics { font.family: JD.fontFamily; id: tm; text: tv.line; font.pixelSize: 13; font.weight: Font.DemiBold }
        readonly property bool longText: tm.width > 470
        implicitWidth: Math.min(640, Math.max(240, tm.width + 118))
        implicitHeight: JD.detailOpen ? Math.min(260, full.implicitHeight + 58) : 40

        RowLayout {
            id: head
            anchors { left: parent.left; right: parent.right; top: parent.top; leftMargin: 12; rightMargin: 12 }
            height: 40
            spacing: 10
            Item {
                implicitWidth: 20; implicitHeight: 20
                Ring { anchors.fill: parent; size: 20; visible: !JD.activityIcon }
                Icon { anchors.centerIn: parent; name: JD.activityIcon; implicitSize: 18; visible: !!JD.activityIcon }
            }
            Label1 {
                id: oneLine
                text: tv.line
                TextSwap on text {}
                Layout.fillWidth: true
                visible: !JD.detailOpen
            }
            Label2 { text: tv.elapsed >= 3 ? tv.elapsed + JD.tr(" с") : ""; font.features: { "tnum": 1 } }
            IconButton {
                visible: oneLine.truncated || JD.detailOpen
                size: 24
                icon: JD.detailOpen ? "go-up" : "go-down"
                onClicked: JD.detailOpen = !JD.detailOpen
            }
        }
        Flickable {
            anchors { left: parent.left; right: parent.right; top: head.bottom; bottom: parent.bottom; leftMargin: 18; rightMargin: 18; bottomMargin: 14 }
            contentHeight: full.implicitHeight
            clip: true
            visible: JD.detailOpen
            Text {
                font.family: JD.fontFamily
                id: full
                width: parent.width
                text: tv.line
                wrapMode: Text.Wrap
                color: JD.text1
                font.pixelSize: 13
                textFormat: Text.PlainText
            }
        }
    }

    component FlashView: View {
        implicitWidth: flashRow.implicitWidth + 32
        implicitHeight: 40
        RowLayout {
            id: flashRow
            anchors.centerIn: parent
            spacing: 10
            Rectangle {
                implicitWidth: 22; implicitHeight: 22; radius: 11
                color: Qt.rgba(JD.flashColor.r, JD.flashColor.g, JD.flashColor.b, 0.2)
                Icon { anchors.centerIn: parent; name: JD.flashIcon; fallback: "dialog-ok"; implicitSize: 16 }
            }
            Label1 { text: JD.flashText; TextSwap on text {} Layout.maximumWidth: 520 }
            Text { font.family: JD.fontFamily; text: JD.flashColor === JD.accentRed ? "" : "✓"; color: JD.accentGreen; font.pixelSize: 15; font.weight: Font.Bold }
        }
    }

    component NotificationView: View {
        readonly property var n: JD.notification || ({})
        implicitWidth: Math.min(560, Math.max(320, nRow.implicitWidth + 36))
        implicitHeight: nRow.implicitHeight + 26
        RowLayout {
            id: nRow
            anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; leftMargin: 16; rightMargin: 18 }
            spacing: 12
            Rectangle {
                implicitWidth: 36; implicitHeight: 36; radius: 10
                color: JD.fill1
                Icon { anchors.centerIn: parent; name: n.icon || (n.app || "").toLowerCase(); fallback: "preferences-desktop-notification-bell"; implicitSize: 24 }
            }
            ColumnLayout {
                spacing: 1
                Layout.fillWidth: true
                Label2 { text: n.app || ""; color: JD.text3; font.pixelSize: 11; Layout.fillWidth: true }
                Label1 { text: n.summary || ""; TextSwap on text {} Layout.fillWidth: true; Layout.maximumWidth: 460 }
                Label2 { visible: !!n.body; text: (n.body || "").replace(/\s+/g, " "); TextSwap on text {} wrapMode: Text.Wrap; maximumLineCount: 2; Layout.fillWidth: true; Layout.maximumWidth: 460 }
            }
        }
    }

    // ───────────── music & video ─────────────
    // album cover (a file or a YouTube thumbnail link), cropped to a rounded square
    component Art: ClippingRectangle {
        id: art
        property string src: ""
        property real size: 26
        implicitWidth: size
        implicitHeight: size
        radius: Math.round(size * 0.24)
        color: JD.fill2
        Icon { anchors.centerIn: parent; name: "audio-x-generic"; implicitSize: art.size * 0.55; visible: artImg.status !== Image.Ready }
        Image {
            id: artImg
            anchors.fill: parent
            source: art.src ? (art.src.startsWith("http") ? art.src : "file://" + art.src) : ""
            sourceSize.height: art.size * 2
            fillMode: Image.PreserveAspectCrop
            asynchronous: true
            opacity: status === Image.Ready ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: JD.dur(260) } }
        }
    }

    // equaliser bars in the cover's colour; they settle down when the music pauses
    component EqBars: Item {
        id: eq
        property color tint: JD.accentPink
        property bool playing: true
        property real t: 0
        implicitWidth: 22
        implicitHeight: 18
        FrameAnimation { running: eq.visible && eq.playing && JD.animOn; onTriggered: eq.t += frameTime }
        Row {
            anchors.centerIn: parent
            spacing: 2.5
            Repeater {
                model: 4
                Rectangle {
                    required property int index
                    width: 3
                    radius: 1.5
                    color: eq.tint
                    anchors.verticalCenter: parent.verticalCenter
                    height: eq.playing ? 4 + 13 * Math.abs(Math.sin(eq.t * (3.1 + index * 1.7) + index * 1.9) * Math.sin(eq.t * (1.3 + index * 0.6) + index))
                                       : 3 + (index % 2)
                    Behavior on height { enabled: !eq.playing && JD.animOn; NumberAnimation { duration: 260; easing.type: Easing.OutCubic } }
                }
            }
        }
    }

    // ▶ / ❚❚ drawn in any colour (theme icons are light-only)
    component PlayGlyph: Item {
        id: pg
        property bool paused: true
        property real size: 20
        property color tint: "black"
        implicitWidth: size
        implicitHeight: size
        Row {
            visible: !pg.paused
            anchors.centerIn: parent
            spacing: pg.size * 0.22
            Rectangle { width: pg.size * 0.26; height: pg.size * 0.8; radius: width * 0.3; color: pg.tint }
            Rectangle { width: pg.size * 0.26; height: pg.size * 0.8; radius: width * 0.3; color: pg.tint }
        }
        Shape {
            visible: pg.paused
            anchors.fill: parent
            preferredRendererType: Shape.CurveRenderer
            ShapePath {
                fillColor: pg.tint
                strokeColor: pg.tint
                strokeWidth: pg.size * 0.08
                joinStyle: ShapePath.RoundJoin
                startX: pg.size * 0.26; startY: pg.size * 0.12
                PathLine { x: pg.size * 0.9; y: pg.size * 0.5 }
                PathLine { x: pg.size * 0.26; y: pg.size * 0.88 }
                PathLine { x: pg.size * 0.26; y: pg.size * 0.12 }
            }
        }
    }

    // a thin progress line: click or drag to jump
    component SeekBar: Item {
        id: sb
        property real value: 0          // 0…1
        property color tint: JD.text1
        property real dragValue: -1
        signal seek(real frac)
        implicitHeight: 16
        Rectangle {
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width
            height: sbHover.hovered || sb.dragValue >= 0 ? 7 : 5
            radius: height / 2
            color: Qt.rgba(1, 1, 1, 0.16)
            Behavior on height { NumberAnimation { duration: 120 } }
            Rectangle {
                width: parent.width * Math.max(0, Math.min(1, sb.dragValue >= 0 ? sb.dragValue : sb.value))
                height: parent.height
                radius: parent.radius
                color: sb.tint
            }
        }
        HoverHandler { id: sbHover; cursorShape: Qt.PointingHandCursor }
        MouseArea {
            anchors.fill: parent
            function at(x) { return Math.max(0, Math.min(1, x / width)) }
            onPressed: m => sb.dragValue = at(m.x)
            onPositionChanged: m => { if (pressed) sb.dragValue = at(m.x) }
            onReleased: { sb.seek(sb.dragValue); sb.dragValue = -1 }
        }
    }

    // the live activity: cover · title · bars (a click opens the player)
    component MusicView: View {
        id: mv
        readonly property var p: JD.player || ({})
        readonly property bool loading: !!p.loading
        readonly property string label: loading ? JD.tr("Загружаю") + " «" + (p.loading.title || "") + "»" : (p.title || "")
        implicitWidth: mrow.implicitWidth + 24
        implicitHeight: 40
        RowLayout {
            id: mrow
            anchors { left: parent.left; verticalCenter: parent.verticalCenter; leftMargin: 8 }
            spacing: 10
            Item {
                implicitWidth: 26; implicitHeight: 26
                Art { anchors.fill: parent; size: 26; src: mv.loading ? "" : (mv.p.thumb || ""); visible: !mv.loading }
                Ring { anchors.centerIn: parent; size: 20; visible: mv.loading; spinning: true; tint: JD.accentPink }
            }
            Label1 { text: mv.label; TextSwap on text {} Layout.maximumWidth: 230 }
            Label2 {
                visible: mv.loading && (mv.p.loading.progress || 0) > 0
                text: Math.round((mv.p.loading ? mv.p.loading.progress : 0) * 100) + "%"
                font.features: { "tnum": 1 }
            }
            EqBars { visible: !mv.loading; tint: JD.artTint(mv.p.color); playing: !mv.p.paused }
        }
    }

    // the big player: cover, title, progress, buttons
    component PlayerView: View {
        id: pl
        readonly property var p: JD.player || ({})
        readonly property color tint: JD.artTint(p.color)
        property real now: Date.now()
        Timer { interval: 250; repeat: true; running: pl.visible && !pl.p.paused; onTriggered: pl.now = Date.now() }
        readonly property real pos: { pl.now; return JD.playerPos(Date.now()) }
        implicitWidth: 520
        implicitHeight: plCol.implicitHeight + 36
        // the cover's colour glows through from the top
        Rectangle {
            anchors.fill: parent
            gradient: Gradient {
                GradientStop { position: 0; color: Qt.rgba(pl.tint.r, pl.tint.g, pl.tint.b, 0.24) }
                GradientStop { position: 0.75; color: "transparent" }
            }
        }
        ColumnLayout {
            id: plCol
            anchors { left: parent.left; right: parent.right; top: parent.top; margins: 18 }
            spacing: 10
            RowLayout {
                spacing: 14
                Art { size: 78; src: pl.p.thumb || "" }
                ColumnLayout {
                    spacing: 2
                    Layout.fillWidth: true
                    Label1 { text: pl.p.title || ""; TextSwap on text {} font.pixelSize: 17; wrapMode: Text.Wrap; maximumLineCount: 2; Layout.fillWidth: true }
                    Label2 { text: pl.p.artist || ""; TextSwap on text {} font.pixelSize: 13; Layout.fillWidth: true }
                    Label2 {
                        visible: !!pl.p.next
                        text: JD.tr("Далее: ") + (pl.p.next || "") + (pl.p.count > 2 ? "  ·  " + (pl.p.count - pl.p.index - 1) + JD.tr(" в очереди") : "")
                        color: JD.text3; font.pixelSize: 11; Layout.fillWidth: true
                    }
                }
                IconButton { icon: "window-close"; size: 26; Layout.alignment: Qt.AlignTop; onClicked: JD.playerOpen = false }
            }
            SeekBar {
                Layout.fillWidth: true
                Layout.topMargin: 4
                tint: pl.tint
                value: pl.p.duration > 0 ? pl.pos / pl.p.duration : 0
                onSeek: frac => {
                    const to = frac * (pl.p.duration || 0)
                    JD.media("seek", to)
                    JD.player = Object.assign({}, JD.player, { pos: to })
                    JD.playerAt = Date.now()
                }
            }
            RowLayout {
                Layout.topMargin: -8
                Label2 { text: JD.fmtTime(pl.pos); color: JD.text3; font.pixelSize: 11; font.features: { "tnum": 1 } }
                Item { Layout.fillWidth: true }
                Label2 { text: "−" + JD.fmtTime((pl.p.duration || 0) - pl.pos); color: JD.text3; font.pixelSize: 11; font.features: { "tnum": 1 } }
            }
            RowLayout {
                spacing: 14
                IconButton { icon: "document-open-folder"; size: 30; onClicked: { Quickshell.execDetached(["dolphin", "--select", pl.p.file]); JD.closeAll() } }
                Item { Layout.fillWidth: true }
                IconButton { icon: "media-skip-backward"; size: 38; onClicked: JD.media("prev") }
                Rectangle {
                    implicitWidth: 54; implicitHeight: 54; radius: 27
                    color: ppHover.hovered ? Qt.lighter(pl.tint, 1.15) : pl.tint
                    scale: ppTap.pressed ? 0.92 : 1
                    Behavior on scale { NumberAnimation { duration: 120 } }
                    PlayGlyph { anchors.centerIn: parent; paused: !!pl.p.paused; size: 20; tint: "black" }
                    HoverHandler { id: ppHover; cursorShape: Qt.PointingHandCursor }
                    TapHandler { id: ppTap; onTapped: { JD.media("toggle"); JD.player = Object.assign({}, JD.player, { pos: pl.pos, paused: !pl.p.paused }); JD.playerAt = Date.now() } }
                }
                IconButton { icon: "media-skip-forward"; size: 38; onClicked: JD.media("next") }
                Item { Layout.fillWidth: true }
                IconButton { icon: "media-playback-stop"; size: 30; onClicked: { JD.media("stop"); JD.playerOpen = false } }
            }
        }
    }

    // a video inside the island (downloaded first; played by Qt right here)
    component VideoView: View {
        id: vv
        readonly property var v: JD.video || ({})
        readonly property bool ready: !!v.file
        property bool ended: false
        readonly property bool busyLine: ["thinking", "speaking", "transcribing"].includes(JD.dstate) || JD.answerOpen
        implicitWidth: JD.videoBig ? 960 : 640
        implicitHeight: Math.round(implicitWidth * 9 / 16)

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
        function toggle() {
            if (vv.ended) { player.position = 0; vv.ended = false; player.play() }
            else if (player.playbackState === MediaPlayer.PlayingState) player.pause()
            else player.play()
        }

        MediaPlayer {
            id: player
            source: vv.ready ? "file://" + vv.v.file : ""
            videoOutput: screenOut
            audioOutput: AudioOutput {
                // quieter while the assistant listens or talks
                volume: ["listening", "speaking", "approval"].includes(JD.dstate) ? 0.25 : 1.0
                muted: Quickshell.env("JUSTDAY_ISLAND_MUTE") === "1"  // the headless test stand stays silent
            }
            onSourceChanged: { vv.ended = false; if (source.toString() !== "") play() }
            onPlaybackStateChanged: JD.send({ cmd: "video_state", playing: playbackState === MediaPlayer.PlayingState, pos: position / 1000 })
            onMediaStatusChanged: if (mediaStatus === MediaPlayer.EndOfMedia) { vv.ended = true; endTimer.restart() }
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
                                Behavior on width { NumberAnimation { duration: 300 } } }
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
                Behavior on opacity { NumberAnimation { duration: 200 } }
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
                    IconButton { icon: JD.videoBig ? "view-restore" : "view-fullscreen"; size: 28; onClicked: JD.videoBig = !JD.videoBig }
                    IconButton { icon: "window-new"; size: 28; visible: vv.ready; onClicked: vv.popout(false) }
                    IconButton { icon: "internet-web-browser"; size: 28; visible: !!vv.v.url && vv.v.url.startsWith("http")
                                 onClicked: { Quickshell.execDetached(["xdg-open", vv.v.url + (player.position > 3000 ? "&t=" + Math.floor(player.position / 1000) + "s" : "")]); vv.close() } }
                    IconButton { icon: "window-close"; size: 28; onClicked: vv.close() }
                }
            }

            // bottom: play/pause, time, progress
            Rectangle {
                visible: vv.ready
                anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
                height: 60
                opacity: vv.chrome && !vv.busyLine ? 1 : 0
                Behavior on opacity { NumberAnimation { duration: 200 } }
                gradient: Gradient {
                    GradientStop { position: 0; color: "transparent" }
                    GradientStop { position: 1; color: Qt.rgba(0, 0, 0, 0.75) }
                }
                RowLayout {
                    anchors { left: parent.left; right: parent.right; bottom: parent.bottom; leftMargin: 22; rightMargin: 26; bottomMargin: 12 }
                    spacing: 12
                    IconButton { icon: player.playbackState === MediaPlayer.PlayingState ? "media-playback-pause" : "media-playback-start"; size: 30; onClicked: vv.toggle() }
                    Label2 { text: JD.fmtTime(player.position / 1000) + " / " + JD.fmtTime(player.duration / 1000); color: JD.text1; font.pixelSize: 11; font.features: { "tnum": 1 } }
                    SeekBar {
                        Layout.fillWidth: true
                        tint: JD.accentPink
                        value: player.duration > 0 ? player.position / player.duration : 0
                        onSeek: frac => { player.position = frac * player.duration; vv.ended = false }
                    }
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
                Behavior on opacity { NumberAnimation { duration: 200 } }
                RowLayout {
                    id: capRow
                    anchors.centerIn: parent
                    width: Math.min(implicitWidth, vv.width - 76)
                    spacing: 10
                    Ring { size: 16 }
                    Label1 {
                        text: JD.answerOpen ? JD.answer : (JD.activity || JD.tr("Думаю…"))
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

    // ───────────── cards ─────────────
    component CardHeader: RowLayout {
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

    component AnswerView: View {
        implicitWidth: 600
        implicitHeight: Math.min(430, answerText.implicitHeight + 116)
        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 18
            spacing: 12
            RowLayout {
                spacing: 10
                Ring { size: 18 }
                Label1 { text: JD.assistantName; Layout.fillWidth: true }
                Label2 { text: JD.dstate === "speaking" ? JD.tr("говорит") : "" }
                IconButton {
                    icon: "edit-copy"; size: 26
                    onClicked: { Quickshell.execDetached(["wl-copy", "--", JD.answer]); JD.flash(JD.tr("Скопировано"), "edit-copy", JD.accentGreen); JD.answerOpen = false }
                }
            }
            Flickable {
                Layout.fillWidth: true
                Layout.fillHeight: true
                contentHeight: answerText.implicitHeight
                clip: true
                Text {
                    font.family: JD.fontFamily
                    id: answerText
                    width: parent.width
                    text: JD.answer
                    TextSwap on text {}
                    wrapMode: Text.Wrap
                    color: JD.text1
                    font.pixelSize: 15
                    lineHeight: 1.18
                    textFormat: Text.PlainText
                }
            }
            // reply: opens the text field (or press the shortcut)
            Rectangle {
                Layout.fillWidth: true
                implicitHeight: 34
                radius: 17
                color: replyHover.hovered ? JD.fill2 : JD.fill1
                Behavior on color { ColorAnimation { duration: 120 } }
                RowLayout {
                    anchors { fill: parent; leftMargin: 14; rightMargin: 12 }
                    Label2 { text: JD.tr("Ответить…"); color: JD.text3; Layout.fillWidth: true }
                    Label2 { text: JD.hotkeys.type || ""; color: JD.text3; font.pixelSize: 11 }
                }
                HoverHandler { id: replyHover; cursorShape: Qt.IBeamCursor }
                TapHandler { onTapped: JD.openCompose() }
            }
        }
    }

    component ApprovalView: View {
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

    component CardView: View {
        id: cv
        readonly property var c: JD.card || ({})
        readonly property string mediaIcon: ({ image: "image-x-generic", video: "video-x-generic", music: "audio-x-generic",
                                               speech: "audio-x-generic", "3d": "application-x-blender" })[c.kind] || "folder-pictures"
        implicitWidth: 600
        implicitHeight: cardCol.implicitHeight + 36
        ColumnLayout {
            id: cardCol
            anchors { left: parent.left; right: parent.right; top: parent.top; margins: 18 }
            spacing: 12

            CardHeader {
                Layout.fillWidth: true
                icon: cv.c.type === "calendar" ? "view-calendar" : cv.c.type === "message_draft" ? "mail-send"
                    : cv.c.type === "question" ? "dialog-question" : cv.c.type === "media" ? cv.mediaIcon : "mail-message"
                tint: cv.c.type === "mail_sent" ? JD.accentGreen : cv.c.type === "calendar" ? JD.accentOrange
                    : cv.c.type === "media" ? JD.accentPurple
                    : ["message_draft", "question"].includes(cv.c.type) ? JD.accentBlue : JD.accentRed
                title: ({ message_draft: JD.tr("Сообщение") + (cv.c.to ? " · " + cv.c.to : ""), question: cv.c.header || JD.tr("Вопрос"),
                          mail_draft: JD.tr("Новое письмо"), mail_sent: JD.tr("Письмо отправлено"), mail_read: cv.c.subject || JD.tr("Письмо"),
                          mail_list: JD.tr("Почта"), calendar: JD.tr("Календарь · ") + (cv.c.when || ""),
                          media: cv.c.failed ? JD.tr("Не получилось") : JD.tr("Готово") + " · " + (cv.c.label || "") })[cv.c.type] || JD.tr("Почта")
                subtitle: ({ message_draft: (cv.c.via ? cv.c.via + " · " : "") + JD.tr("проверьте перед отправкой"), question: JD.micOn ? JD.tr("выберите или ответьте голосом") : JD.tr("выберите вариант"),
                             mail_draft: JD.tr("черновик · проверьте перед отправкой"), mail_sent: JD.tr("Кому: ") + (cv.c.to || ""),
                             mail_read: JD.tr("от ") + (cv.c.from || ""), mail_list: JD.tr("важные непрочитанные · обработано локально"),
                             calendar: (cv.c.items || []).length ? (cv.c.items || []).length + JD.tr(" · обработано локально") : JD.tr("свободно"),
                             media: cv.c.failed ? (cv.c.error || "") : (cv.c.name || "") })[cv.c.type] || ""
                IconButton { icon: "window-close"; size: 26
                             onClicked: { if (["message_draft", "question"].includes(cv.c.type)) JD.send({ cmd: "deny" }); JD.card = null } }
            }

            // a finished picture / video / track / model from the studio
            ClippingRectangle {
                id: previewBox
                visible: (cv.c.type === "media" || cv.c.type === "question") && !!cv.c.thumb
                property real ratio: 0.5625  // height / width, set once the picture is loaded
                Layout.fillWidth: true
                // the card is 600 wide (564 inside): a fixed width keeps the layout from re-polishing itself
                implicitHeight: Math.min(cv.c.type === "question" ? 210 : 300, 564 * ratio)
                radius: 14
                color: JD.fill1
                Image {
                    id: preview
                    anchors.fill: parent
                    source: cv.c.thumb ? (cv.c.thumb.startsWith("http") ? cv.c.thumb : "file://" + cv.c.thumb) : ""
                    sourceSize.width: 1128
                    fillMode: Image.PreserveAspectFit
                    asynchronous: true
                    cache: false
                    // (sourceSize.height stays 0 when only the width is requested — the implicit size is the real one)
                    onStatusChanged: if (status === Image.Ready && implicitWidth > 0) previewBox.ratio = implicitHeight / implicitWidth
                    opacity: status === Image.Ready ? 1 : 0
                    Behavior on opacity { NumberAnimation { duration: JD.dur(220); easing.type: Easing.OutCubic } }
                }
                Rectangle {
                    visible: cv.c.kind === "video" || cv.c.type === "question"
                    anchors.centerIn: parent
                    width: 52; height: 52; radius: 26
                    color: Qt.rgba(0, 0, 0, 0.55)
                    Icon { anchors.centerIn: parent; name: "media-playback-start"; implicitSize: 24 }
                }
                TapHandler { enabled: cv.c.type === "media"; onTapped: Quickshell.execDetached(["xdg-open", cv.c.file]) }
                HoverHandler { cursorShape: cv.c.type === "media" ? Qt.PointingHandCursor : Qt.ArrowCursor }
            }
            RowLayout {
                visible: cv.c.type === "media" && !cv.c.failed
                Layout.alignment: Qt.AlignRight
                spacing: 10
                PillButton { label: JD.tr("Показать в папке"); onClicked: { Quickshell.execDetached(["dolphin", "--select", cv.c.file]); JD.card = null } }
                PillButton { visible: cv.c.kind === "image"; label: JD.tr("Копировать")
                             onClicked: { Quickshell.execDetached(["sh", "-c", 'wl-copy < "$1"', "sh", cv.c.file]); JD.flash(JD.tr("Скопировано"), "edit-copy", JD.accentGreen); JD.card = null } }
                PillButton { label: JD.tr("Открыть"); tint: JD.accentPurple; labelColor: "white"
                             onClicked: { Quickshell.execDetached(["xdg-open", cv.c.file]); JD.card = null } }
            }

            // draft: To / Subject / Body + Send
            GridLayout {
                visible: cv.c.type === "mail_draft"
                Layout.fillWidth: true
                columns: 2
                columnSpacing: 12
                rowSpacing: 6
                Label2 { text: JD.tr("Кому") }
                Label1 { text: (cv.c.to || "") + (cv.c.address && cv.c.address !== cv.c.to ? "  <" + cv.c.address + ">" : ""); Layout.fillWidth: true }
                Label2 { text: JD.tr("Тема") }
                Label1 { text: cv.c.subject || JD.tr("без темы"); Layout.fillWidth: true }
            }
            Rectangle {
                visible: ["mail_draft", "mail_read", "message_draft", "question"].includes(cv.c.type) && !cardCol.tiles
                Layout.fillWidth: true
                implicitHeight: Math.min(200, bodyText.implicitHeight + 24)
                radius: 14
                color: JD.fill1
                Flickable {
                    anchors.fill: parent
                    anchors.margins: 12
                    contentHeight: bodyText.implicitHeight
                    clip: true
                    Text {
                        font.family: JD.fontFamily
                        id: bodyText
                        width: parent.width
                        text: cv.c.type === "mail_read" ? (cv.c.text || "") : cv.c.type === "question" ? (cv.c.question || "") : (cv.c.body || "")
                        wrapMode: Text.Wrap
                        color: JD.text1
                        font.pixelSize: 14
                        lineHeight: 1.15
                        textFormat: Text.PlainText
                    }
                }
            }
            RowLayout {
                visible: cv.c.type === "mail_draft"
                Layout.alignment: Qt.AlignRight
                spacing: 10
                PillButton { label: JD.tr("Не отправлять"); onClicked: JD.send({ cmd: "type", text: JD.tr("не отправляй") }) }
                PillButton { label: JD.tr("Изменить голосом"); onClicked: JD.send({ cmd: "toggle" }) }
                PillButton { label: JD.tr("Отправить"); tint: JD.accentBlue; onClicked: JD.send({ cmd: "type", text: JD.tr("да, отправляй") }) }
            }

            // message draft: shown before the assistant opens the messenger
            RowLayout {
                visible: cv.c.type === "message_draft"
                Layout.alignment: Qt.AlignRight
                spacing: 10
                PillButton { label: JD.tr("Не отправлять"); onClicked: JD.send({ cmd: "deny" }) }
                PillButton { label: JD.tr("Изменить голосом"); onClicked: JD.send({ cmd: "listen" }) }
                PillButton { label: JD.tr("Отправить"); tint: JD.accentBlue; onClicked: JD.send({ cmd: "approve" }) }
            }

            // the assistant's question: one button per option (options with icons sit side by side as tiles)
            readonly property bool tiles: cv.c.type === "question" && (cv.c.options || []).length > 0 && (cv.c.options || []).length <= 4
                                          && (cv.c.options || []).every(o => !!o.icon)
            Label1 {
                visible: cardCol.tiles && !!cv.c.question
                text: cv.c.question || ""
                font.weight: Font.Medium
                wrapMode: Text.Wrap
                maximumLineCount: 3
                Layout.fillWidth: true
            }
            RowLayout {
                visible: cardCol.tiles
                Layout.fillWidth: true
                spacing: 10
                Repeater {
                    model: cardCol.tiles ? cv.c.options : []
                    Rectangle {
                        required property var modelData
                        required property int index
                        Layout.fillWidth: true
                        Layout.preferredWidth: 1
                        implicitHeight: tileCol.implicitHeight + 24
                        radius: 16
                        color: tHover.hovered ? JD.fill2 : JD.fill1
                        border.width: index === 0 ? 1 : 0
                        border.color: Qt.rgba(JD.accentBlue.r, JD.accentBlue.g, JD.accentBlue.b, 0.6)
                        scale: tTap.pressed ? 0.96 : 1
                        Behavior on scale { NumberAnimation { duration: 120 } }
                        Behavior on color { ColorAnimation { duration: 120 } }
                        ColumnLayout {
                            id: tileCol
                            anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; margins: 12 }
                            spacing: 4
                            Icon { name: modelData.icon; implicitSize: 26; Layout.alignment: Qt.AlignHCenter }
                            Label1 { text: modelData.label; horizontalAlignment: Text.AlignHCenter; Layout.fillWidth: true }
                            Label2 { text: modelData.description || ""; font.pixelSize: 11; color: JD.text3; horizontalAlignment: Text.AlignHCenter
                                     wrapMode: Text.Wrap; maximumLineCount: 2; Layout.fillWidth: true }
                            Text {
                                visible: index === 0 && !!JD.hotkeys.yes
                                text: JD.hotkeys.yes || ""
                                color: JD.text3; font.family: JD.fontFamily; font.pixelSize: 10
                                Layout.alignment: Qt.AlignHCenter
                            }
                        }
                        HoverHandler { id: tHover; cursorShape: Qt.PointingHandCursor }
                        TapHandler { id: tTap; onTapped: JD.send({ cmd: "answer", value: modelData.label }) }
                    }
                }
            }
            Repeater {
                model: cv.c.type === "question" && !cardCol.tiles ? (cv.c.options || []) : []
                Rectangle {
                    required property var modelData
                    Layout.fillWidth: true
                    implicitHeight: optCol.implicitHeight + 16
                    radius: 12
                    color: optHover.hovered ? JD.fill2 : JD.fill1
                    ColumnLayout {
                        id: optCol
                        anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; leftMargin: 12; rightMargin: 12 }
                        spacing: 1
                        Label1 { text: modelData.label; Layout.fillWidth: true; wrapMode: Text.Wrap; maximumLineCount: 2 }
                        Label2 { visible: !!modelData.description; text: modelData.description || ""; Layout.fillWidth: true; wrapMode: Text.Wrap; maximumLineCount: 2 }
                    }
                    HoverHandler { id: optHover; cursorShape: Qt.PointingHandCursor }
                    TapHandler { onTapped: JD.send({ cmd: "answer", value: modelData.label }) }
                }
            }
            RowLayout {
                visible: cv.c.type === "question"
                Layout.alignment: Qt.AlignRight
                spacing: 10
                PillButton { label: JD.tr("Пропустить"); onClicked: JD.send({ cmd: "deny" }) }
                PillButton { visible: JD.micOn; label: JD.tr("Ответить голосом"); tint: JD.accentBlue; onClicked: JD.send({ cmd: "listen" }) }
            }

            // calendar events
            Repeater {
                model: cv.c.type === "calendar" ? (cv.c.items || []) : []
                Rectangle {
                    required property var modelData
                    Layout.fillWidth: true
                    implicitHeight: 44
                    radius: 12
                    color: JD.fill1
                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 12
                        anchors.rightMargin: 12
                        spacing: 12
                        Text {
                            text: modelData.all_day ? JD.tr("весь день") : Qt.formatTime(new Date(modelData.start), "HH:mm")
                            color: JD.accentOrange; font.family: JD.fontFamily; font.pixelSize: 13; font.weight: Font.DemiBold
                            Layout.preferredWidth: 70
                        }
                        ColumnLayout {
                            spacing: 0
                            Layout.fillWidth: true
                            Label1 { text: modelData.title; Layout.fillWidth: true }
                            Label2 { visible: !!modelData.location; text: modelData.location; Layout.fillWidth: true }
                        }
                    }
                }
            }

            // list of letters
            Label2 {
                visible: cv.c.type === "mail_list" && !!cv.c.text
                text: cv.c.text || ""
                wrapMode: Text.Wrap
                elide: Text.ElideNone
                maximumLineCount: 4
                Layout.fillWidth: true
            }
            Repeater {
                model: cv.c.type === "mail_list" ? (cv.c.items || []) : []
                Rectangle {
                    required property var modelData
                    Layout.fillWidth: true
                    implicitHeight: 44
                    radius: 12
                    color: rowHover.hovered ? JD.fill2 : JD.fill1
                    Behavior on color { ColorAnimation { duration: 120 } }
                    RowLayout {
                        anchors.fill: parent
                        anchors.leftMargin: 12
                        anchors.rightMargin: 12
                        spacing: 10
                        Rectangle {
                            implicitWidth: 26; implicitHeight: 26; radius: 13
                            color: Qt.hsla((modelData.from.charCodeAt(0) % 12) / 12, 0.55, 0.45, 1)
                            Text { font.family: JD.fontFamily; anchors.centerIn: parent; text: modelData.from.charAt(0).toUpperCase(); color: "white"; font.pixelSize: 12; font.weight: Font.Bold }
                        }
                        ColumnLayout {
                            spacing: 0
                            Layout.fillWidth: true
                            Label1 { text: modelData.from; font.pixelSize: 12; Layout.fillWidth: true }
                            Label2 { text: modelData.subject; Layout.fillWidth: true }
                        }
                    }
                    HoverHandler { id: rowHover; cursorShape: Qt.PointingHandCursor }
                    TapHandler { onTapped: JD.send({ cmd: "type", text: JD.tr("прочитай письмо номер ") + modelData.n }) }
                }
            }
        }
    }

    // ───────────── the text field (Spotlight-like) ─────────────
    component ComposeView: View {
        id: cmp
        implicitWidth: 660
        implicitHeight: cmpCol.implicitHeight + 32
        property int recall: -1               // index in JD.sent / history while browsing with ↑↓
        property int pick: 0                  // highlighted slash command
        readonly property var recallList: JD.sent.concat(JD.history.map(h => h.q).filter(q => q && !JD.sent.includes(q)))
        readonly property var commands: [
            { cmd: "/new", title: JD.tr("Новый разговор"), icon: "document-new", run: () => JD.send({ cmd: "new_session" }) },
            { cmd: "/stop", title: JD.tr("Остановить всё"), icon: "media-playback-stop", run: () => JD.send({ cmd: "stop" }) },
            { cmd: "/image", title: JD.tr("Нарисовать картинку"), icon: "image-x-generic", fill: JD.tr("Нарисуй ") },
            { cmd: "/video", title: JD.tr("Сделать видео"), icon: "video-x-generic", fill: JD.tr("Сделай видео: ") },
            { cmd: "/play", title: JD.tr("Включить песню"), icon: "media-playback-start", fill: JD.tr("Включи песню ") },
            { cmd: "/watch", title: JD.tr("Включить видео"), icon: "video-x-generic", fill: JD.tr("Включи видео ") },
            { cmd: "/music", title: JD.tr("Сделать музыку"), icon: "audio-x-generic", fill: JD.tr("Сделай трек: ") },
            { cmd: "/install", title: JD.tr("Установить программу"), icon: "system-software-install", fill: JD.tr("Установи ") },
            { cmd: "/screen", title: JD.tr("Что на экране?"), icon: "view-preview", fill: JD.tr("Посмотри на экран и ") },
            { cmd: "/mic", title: JD.micOn ? JD.tr("Выключить микрофон (только текст)") : JD.tr("Включить микрофон"), icon: "audio-input-microphone",
              run: () => JD.run(["config", "set", "audio.microphone", String(!JD.micOn)]) },
            { cmd: "/menu", title: JD.tr("Меню"), icon: "view-grid", run: () => { JD.expanded = true } },
            { cmd: "/settings", title: JD.tr("Настройки"), icon: "configure", run: () => JD.openSettings("general") },
            { cmd: "/keys", title: JD.tr("Сочетания клавиш"), icon: "input-keyboard", run: () => JD.openSettings("buttons") },
            { cmd: "/help", title: JD.tr("Руководство"), icon: "help-contents", run: () => JD.openManual() }
        ]
        readonly property var matches: {
            const t = field.text
            if (!t.startsWith("/") || t.includes(" ")) return []
            return commands.filter(c => c.cmd.startsWith(t.toLowerCase()) || c.title.toLowerCase().includes(t.slice(1).toLowerCase())).slice(0, 8)
        }
        onMatchesChanged: pick = 0

        function focusField() {
            field.text = JD.composeText
            field.cursorPosition = field.length
            recall = -1
            field.forceActiveFocus()
        }
        onShownChanged: if (shown) focusField()
        Connections { target: JD; function onComposeSerialChanged() { if (cmp.shown) cmp.focusField() } }

        function runCommand(c) {
            if (c.fill) { field.text = c.fill; field.cursorPosition = field.length; return }
            JD.composeOpen = false
            c.run()
        }
        function browse(step) {
            const list = recallList
            if (!list.length) return
            recall = Math.max(-1, Math.min(list.length - 1, recall + step))
            field.text = recall < 0 ? "" : list[recall]
            field.cursorPosition = field.length
        }

        ColumnLayout {
            id: cmpCol
            anchors { left: parent.left; right: parent.right; top: parent.top; margins: 16 }
            spacing: 10

            RowLayout {
                spacing: 12
                Ring { size: 22; Layout.alignment: Qt.AlignTop; Layout.topMargin: 3 }
                Flickable {
                    id: fieldFlick
                    Layout.fillWidth: true
                    implicitHeight: Math.min(field.implicitHeight, 6 * 21)
                    contentHeight: field.implicitHeight
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    function ensureVisible(r) {
                        if (contentY >= r.y) contentY = r.y
                        else if (contentY + height <= r.y + r.height) contentY = r.y + r.height - height
                    }
                    TextEdit {
                        id: field
                        width: fieldFlick.width
                        font.family: JD.fontFamily
                        font.pixelSize: 17
                        color: JD.text1
                        selectionColor: Qt.rgba(JD.accentBlue.r, JD.accentBlue.g, JD.accentBlue.b, 0.5)
                        wrapMode: TextEdit.Wrap
                        selectByMouse: true
                        textFormat: TextEdit.PlainText
                        onCursorRectangleChanged: fieldFlick.ensureVisible(cursorRectangle)
                        Text {
                            visible: !field.text && !field.preeditText
                            text: JD.composeContext.selection ? JD.tr("Что сделать с выделенным? Объясни, переведи, ответь…")
                                                              : JD.tr("Спросите или попросите что-нибудь…")
                            color: JD.text3
                            font: field.font
                        }
                        Keys.onPressed: event => {
                            const k = event.key
                            if (k === Qt.Key_Escape) { JD.composeOpen = false; event.accepted = true; return }
                            if (cmp.matches.length) {
                                if (k === Qt.Key_Down || k === Qt.Key_Up) {
                                    cmp.pick = (cmp.pick + (k === Qt.Key_Down ? 1 : -1) + cmp.matches.length) % cmp.matches.length
                                    event.accepted = true; return
                                }
                                if (k === Qt.Key_Tab || k === Qt.Key_Return || k === Qt.Key_Enter) {
                                    cmp.runCommand(cmp.matches[cmp.pick]); event.accepted = true; return
                                }
                            }
                            if ((k === Qt.Key_Return || k === Qt.Key_Enter) && !(event.modifiers & Qt.ShiftModifier)) {
                                JD.submit(field.text); event.accepted = true; return
                            }
                            if (k === Qt.Key_Up && (field.cursorRectangle.y < 4 || cmp.recall >= 0)) { cmp.browse(1); event.accepted = true; return }
                            if (k === Qt.Key_Down && cmp.recall >= 0) { cmp.browse(-1); event.accepted = true; return }
                            if (k === Qt.Key_Backspace && !field.text && JD.composeContext.selection) {
                                JD.composeContext = ({}); event.accepted = true; return
                            }
                        }
                    }
                }
                IconButton {
                    visible: JD.micOn
                    Layout.alignment: Qt.AlignTop
                    icon: "audio-input-microphone"; size: 30
                    onClicked: { JD.composeOpen = false; JD.send({ cmd: "listen" }) }
                }
                Rectangle {
                    Layout.alignment: Qt.AlignTop
                    implicitWidth: 30; implicitHeight: 30; radius: 15
                    color: field.text.trim() ? JD.accentBlue : JD.fill1
                    Behavior on color { ColorAnimation { duration: 140 } }
                    Icon { anchors.centerIn: parent; name: "go-up"; implicitSize: 16 }
                    TapHandler { onTapped: JD.submit(field.text) }
                    HoverHandler { cursorShape: Qt.PointingHandCursor }
                }
            }

            // selected text that goes along with the request
            Rectangle {
                visible: !!JD.composeContext.selection
                Layout.fillWidth: true
                implicitHeight: 34
                radius: 10
                color: JD.fill1
                RowLayout {
                    anchors { fill: parent; leftMargin: 10; rightMargin: 4 }
                    spacing: 8
                    Icon { name: "edit-select-text"; fallback: "format-text-bold"; implicitSize: 16 }
                    Label2 {
                        Layout.fillWidth: true
                        text: JD.tr("Выделенное: ") + "«" + (JD.composeContext.selection || "").replace(/\s+/g, " ") + "»"
                    }
                    IconButton { icon: "window-close"; size: 24; onClicked: JD.composeContext = ({}) }
                }
            }

            // slash commands
            Repeater {
                model: cmp.matches
                Rectangle {
                    required property var modelData
                    required property int index
                    Layout.fillWidth: true
                    implicitHeight: 36
                    radius: 10
                    color: index === cmp.pick ? JD.fill2 : (cmdHover.hovered ? JD.fill1 : "transparent")
                    RowLayout {
                        anchors { fill: parent; leftMargin: 10; rightMargin: 12 }
                        spacing: 10
                        Icon { name: modelData.icon; implicitSize: 18 }
                        Label1 { text: modelData.title; font.weight: Font.Normal; Layout.fillWidth: true }
                        Label2 { text: modelData.cmd; color: JD.text3; font.family: "monospace" }
                    }
                    HoverHandler { id: cmdHover; cursorShape: Qt.PointingHandCursor }
                    TapHandler { onTapped: cmp.runCommand(modelData) }
                }
            }

            // key hints
            RowLayout {
                spacing: 14
                Repeater {
                    model: [
                        { k: "↵", t: JD.tr("отправить") }, { k: "⇧↵", t: JD.tr("строка") },
                        { k: "↑", t: JD.tr("прошлые") }, { k: "/", t: JD.tr("команды") }, { k: "Esc", t: JD.tr("закрыть") }
                    ]
                    RowLayout {
                        required property var modelData
                        spacing: 5
                        Rectangle {
                            implicitWidth: Math.max(18, kt.implicitWidth + 8); implicitHeight: 18; radius: 5
                            color: JD.fill1
                            Text { id: kt; anchors.centerIn: parent; text: modelData.k; color: JD.text2; font.family: JD.fontFamily; font.pixelSize: 10; font.weight: Font.DemiBold }
                        }
                        Text { text: modelData.t; color: JD.text3; font.family: JD.fontFamily; font.pixelSize: 11 }
                    }
                }
                Item { Layout.fillWidth: true }
                Text {
                    text: (JD.settings.provider || "") + (JD.settings.model ? " · " + JD.settings.model : "")
                    color: JD.text3; font.family: JD.fontFamily; font.pixelSize: 11
                }
            }
        }
    }

    // ───────────── expanded control center ─────────────
    component Tile: Rectangle {
        id: tile
        property string icon: ""
        property string title: ""
        property bool on: false
        signal toggled()
        Layout.fillWidth: true
        implicitHeight: 64
        radius: 18
        color: on ? Qt.rgba(JD.accentBlue.r, JD.accentBlue.g, JD.accentBlue.b, 0.9) : (tileHover.hovered ? JD.fill2 : JD.fill1)
        scale: tileTap.pressed ? 0.96 : 1
        Behavior on color { ColorAnimation { duration: 180 } }
        Behavior on scale { NumberAnimation { duration: 120 } }
        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 12
            spacing: 4
            Icon { name: tile.icon; implicitSize: 18 }
            Label1 { text: tile.title; font.pixelSize: 12; Layout.fillWidth: true }
        }
        HoverHandler { id: tileHover; cursorShape: Qt.PointingHandCursor }
        TapHandler { id: tileTap; onTapped: tile.toggled() }
    }

    component ExpandedView: View {
        id: ev
        property string pendingProvider: ""
        readonly property var player: Mpris.players.values.length ? Mpris.players.values.find(p => p.isPlaying) || Mpris.players.values[0] : null
        implicitWidth: 680
        implicitHeight: col.implicitHeight + 40

        function setting(key, value) { JD.run(["config", "set", key, String(value)]) }

        ColumnLayout {
            id: col
            anchors { left: parent.left; right: parent.right; top: parent.top; margins: 20 }
            spacing: 16

            // header
            RowLayout {
                spacing: 14
                Ring { size: 34 }
                ColumnLayout {
                    spacing: 1
                    Label1 { text: JD.assistantName; font.pixelSize: 17 }
                    Label2 {
                        text: ({ idle: JD.tr("Готов"), listening: JD.tr("Слушаю"), transcribing: JD.tr("Распознаю"), thinking: JD.activity || JD.tr("Работаю"),
                                 speaking: JD.tr("Говорит"), approval: JD.tr("Ждёт подтверждения"), offline: JD.tr("Демон не запущен") })[JD.dstate] || JD.dstate
                        Layout.maximumWidth: 380
                    }
                }
                Item { Layout.fillWidth: true }
                Rectangle {
                    implicitWidth: chip.implicitWidth + 20; implicitHeight: 26; radius: 13
                    color: JD.fill1
                    Label2 { id: chip; anchors.centerIn: parent; text: (JD.settings.provider || "?") + " · " + (JD.settings.model || "?") }
                }
                IconButton { icon: "configure"; size: 28; onClicked: JD.openSettings("general") }
                IconButton { icon: "window-close"; size: 28; onClicked: JD.expanded = false }
            }

            // update available
            Rectangle {
                visible: !!JD.update
                Layout.fillWidth: true
                implicitHeight: 48
                radius: 16
                color: Qt.rgba(JD.accentBlue.r, JD.accentBlue.g, JD.accentBlue.b, 0.16)
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 14
                    anchors.rightMargin: 8
                    spacing: 10
                    Label1 { text: JD.tr("Доступно обновление JustDay"); Layout.fillWidth: false }
                    Label2 { text: JD.update ? (JD.update.changes || [])[0] || "" : ""; Layout.fillWidth: true }
                    PillButton { label: JD.tr("Обновить"); tint: JD.accentBlue; onClicked: JD.runUpdate() }
                }
            }

            // ask by text: opens the text field
            Rectangle {
                Layout.fillWidth: true
                implicitHeight: 44
                radius: 22
                color: askHover.hovered ? JD.fill2 : JD.fill1
                Behavior on color { ColorAnimation { duration: 120 } }
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 16
                    anchors.rightMargin: 6
                    spacing: 8
                    Text { font.family: JD.fontFamily; text: JD.tr("Спросите или попросите что-нибудь…"); color: JD.text3; font.pixelSize: 14; Layout.fillWidth: true }
                    Rectangle {
                        visible: !!JD.hotkeys.type
                        implicitWidth: hk.implicitWidth + 12; implicitHeight: 22; radius: 6
                        color: JD.fill1
                        Text { id: hk; anchors.centerIn: parent; text: JD.hotkeys.type || ""; color: JD.text2; font.family: JD.fontFamily; font.pixelSize: 11 }
                    }
                    IconButton { visible: JD.micOn; icon: "audio-input-microphone"; size: 32; onClicked: { JD.expanded = false; JD.send({ cmd: "listen" }) } }
                }
                HoverHandler { id: askHover; cursorShape: Qt.IBeamCursor }
                TapHandler { onTapped: JD.openCompose() }
            }

            // quick toggles
            RowLayout {
                spacing: 10
                Tile { icon: "audio-volume-high"; title: JD.tr("Звуки"); on: !!JD.settings.earcons; onToggled: ev.setting("audio.earcons", !on) }
                Tile { icon: "preferences-desktop-notification-bell"; title: JD.tr("Уведомления"); on: !!JD.settings.notifications; onToggled: ev.setting("ui.notifications", !on) }
                Tile { icon: "mail-message"; title: JD.settings.mail ? JD.tr("Объявлять письма") : JD.tr("Почта не настроена"); on: !!JD.settings.mail && !!JD.settings.mail_announce; onToggled: if (JD.settings.mail) ev.setting("mail.announce", !on); else JD.openSettings("mail") }
                Tile { icon: "input-mouse"; title: JD.tr("Метки кнопок"); on: !!JD.settings.accessibility; onToggled: ev.setting("desktop.accessibility", !on) }
            }

            // model
            ColumnLayout {
                spacing: 8
                Label2 { text: JD.tr("Модель") }
                RowLayout {
                    spacing: 6
                    Repeater {
                        model: [
                            { id: "claude", label: "Claude", model: "sonnet", hint: JD.tr("подписка") },
                            { id: "ollama_cloud", label: JD.tr("Бесплатная"), model: "kimi-k3:cloud", hint: JD.tr("облако Ollama") },
                            { id: "ollama", label: JD.tr("Локальная"), model: "qwen3.5:9b", hint: JD.tr("приватно") },
                            { id: "openrouter", label: "OpenRouter", model: "openrouter/free", hint: JD.tr("50 в день") },
                            { id: "deepseek", label: "DeepSeek", model: "deepseek-v4-pro", hint: JD.tr("ключ") }
                        ]
                        Rectangle {
                            required property var modelData
                            readonly property bool current: (ev.pendingProvider || JD.settings.provider) === modelData.id
                            Layout.fillWidth: true
                            implicitHeight: 50
                            radius: 14
                            color: current ? JD.text1 : (segHover.hovered ? JD.fill2 : JD.fill1)
                            Behavior on color { ColorAnimation { duration: 180 } }
                            ColumnLayout {
                                anchors.centerIn: parent
                                spacing: 0
                                Text { font.family: JD.fontFamily; text: modelData.label; color: parent.parent.current ? "black" : JD.text1; font.pixelSize: 13; font.weight: Font.DemiBold; Layout.alignment: Qt.AlignHCenter }
                                Text { font.family: JD.fontFamily; text: modelData.hint; color: parent.parent.current ? Qt.rgba(0, 0, 0, 0.55) : JD.text3; font.pixelSize: 11; Layout.alignment: Qt.AlignHCenter }
                            }
                            HoverHandler { id: segHover; cursorShape: Qt.PointingHandCursor }
                            TapHandler {
                                onTapped: {
                                    if (modelData.id === JD.settings.provider && !ev.pendingProvider) return
                                    ev.pendingProvider = modelData.id
                                    JD.run(["model", "use", modelData.id, modelData.model])
                                }
                            }
                        }
                    }
                }
                RowLayout {
                    visible: !!ev.pendingProvider && ev.pendingProvider !== JD.settings.provider
                    spacing: 10
                    Label2 { text: JD.tr("Модель сменится после перезапуска (текущий разговор начнётся заново)"); Layout.fillWidth: true }
                    PillButton { label: JD.tr("Перезапустить"); tint: JD.accentBlue; onClicked: { JD.run(["restart"]); ev.pendingProvider = "" } }
                }
            }

            // now playing: our player first, otherwise any MPRIS player (browser, Spotify…)
            Rectangle {
                visible: JD.musicOn || !!ev.player
                Layout.fillWidth: true
                implicitHeight: 64
                radius: 18
                color: JD.fill1
                TapHandler { enabled: JD.musicOn; onTapped: { JD.expanded = false; JD.playerOpen = true } }
                RowLayout {
                    anchors.fill: parent
                    anchors.margins: 10
                    spacing: 12
                    ClippingRectangle {
                        implicitWidth: 44; implicitHeight: 44; radius: 10
                        color: JD.fill2
                        Icon { anchors.centerIn: parent; name: "media-album-cover"; fallback: "audio-x-generic"; implicitSize: 22; visible: art.status !== Image.Ready }
                        Image { id: art; anchors.fill: parent; fillMode: Image.PreserveAspectCrop; asynchronous: true
                                source: JD.musicOn ? (JD.player.thumb ? "file://" + JD.player.thumb : "") : (ev.player ? ev.player.trackArtUrl : "") }
                    }
                    ColumnLayout {
                        spacing: 0
                        Layout.fillWidth: true
                        Label1 { text: JD.musicOn ? (JD.player.title || "") : ev.player ? (ev.player.trackTitle || ev.player.identity) : ""; Layout.fillWidth: true }
                        Label2 { text: JD.musicOn ? (JD.player.artist || "") : ev.player ? (ev.player.trackArtist || "") : ""; Layout.fillWidth: true }
                    }
                    IconButton { icon: "media-skip-backward"; onClicked: JD.musicOn ? JD.media("prev") : ev.player.previous() }
                    IconButton {
                        icon: (JD.musicOn ? !JD.player.paused : ev.player && ev.player.isPlaying) ? "media-playback-pause" : "media-playback-start"; size: 36
                        onClicked: JD.musicOn ? JD.media("toggle") : ev.player.togglePlaying()
                    }
                    IconButton { icon: "media-skip-forward"; onClicked: JD.musicOn ? JD.media("next") : ev.player.next() }
                }
            }

            // recent notifications
            ColumnLayout {
                visible: JD.notifications.length > 0 && JD.island.show_notifications !== false
                spacing: 6
                RowLayout {
                    Label2 { text: JD.tr("Уведомления"); Layout.fillWidth: true }
                    Label2 { text: JD.tr("очистить"); color: JD.accentBlue; TapHandler { onTapped: JD.notifications = [] } HoverHandler { cursorShape: Qt.PointingHandCursor } }
                }
                Repeater {
                    model: JD.notifications.slice(0, 3)
                    RowLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        spacing: 10
                        Label2 { text: modelData.ts; color: JD.text3; font.features: { "tnum": 1 } }
                        Icon { name: modelData.icon || (modelData.app || "").toLowerCase(); fallback: "preferences-desktop-notification-bell"; implicitSize: 16 }
                        Label1 { text: modelData.summary; font.weight: Font.Normal; Layout.preferredWidth: 220 }
                        Label2 { text: (modelData.body || "").replace(/\s+/g, " "); Layout.fillWidth: true }
                    }
                }
            }

            // recent
            ColumnLayout {
                visible: JD.history.length > 0
                spacing: 6
                Label2 { text: JD.tr("Недавнее") }
                Repeater {
                    model: JD.history.slice(0, 4)
                    RowLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        spacing: 10
                        Label2 { text: modelData.ts; color: JD.text3; font.features: { "tnum": 1 } }
                        Label1 { text: modelData.q; font.weight: Font.Normal; Layout.preferredWidth: 250 }
                        Label2 { text: modelData.a; Layout.fillWidth: true }
                    }
                }
            }

            // footer
            RowLayout {
                spacing: 8
                PillButton { label: JD.tr("Новый разговор"); onClicked: JD.send({ cmd: "new_session" }) }
                PillButton { label: JD.tr("Остановить"); onClicked: JD.send({ cmd: "stop" }) }
                Item { Layout.fillWidth: true }
                PillButton { label: JD.tr("Журнал"); onClicked: Quickshell.execDetached(["kitty", "--detach", "justday", "logs", "-f"]) }
                PillButton { label: JD.tr("Руководство"); onClicked: JD.openManual() }
            }
        }
    }
}
