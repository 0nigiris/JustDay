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

    // test backdrop (JUSTDAY_ISLAND_WALLPAPER=1): a colourful "wallpaper" so the black island is visible in headless sessions
    Loader {
        active: Quickshell.env("JUSTDAY_ISLAND_WALLPAPER") === "1"
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
        readonly property bool big: island.mode === "expanded" || island.mode === "settings"
        WlrLayershell.keyboardFocus: big ? WlrKeyboardFocus.OnDemand : WlrKeyboardFocus.None
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
                expanded: expandedView, settings: settingsHolder, approval: approvalView, card: cardView, listening: listeningView,
                notification: notificationView, flash: flashView, answer: answerView, transcribing: thinkingView, thinking: thinkingView,
                peek: peekView, hidden: peekView })[mode]
            readonly property bool compact: ["listening", "flash", "transcribing", "thinking", "peek", "hidden"].includes(mode) && !JD.detailOpen

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
                enabled: !["expanded", "settings", "approval", "card"].includes(island.mode)
                onTapped: {
                    if (island.mode === "answer") { JD.answerOpen = false; return }
                    if (island.mode === "notification") { JD.notification = null; return }
                    JD.expanded = true
                }
            }

            // Every view is laid out at its own natural size; the island springs to it and cross-fades.
            PeekView { id: peekView; shown: island.mode === "peek" }
            ListeningView { id: listeningView; shown: island.mode === "listening" }
            ThinkingView { id: thinkingView; shown: island.mode === "thinking" || island.mode === "transcribing" }
            FlashView { id: flashView; shown: island.mode === "flash" }
            NotificationView { id: notificationView; shown: island.mode === "notification" }
            AnswerView { id: answerView; shown: island.mode === "answer" }
            ApprovalView { id: approvalView; shown: island.mode === "approval" }
            CardView { id: cardView; shown: island.mode === "card" }
            ExpandedView { id: expandedView; shown: island.mode === "expanded" }
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

        // soft shadow under the island
        MultiEffect {
            source: island
            anchors.fill: island
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
        property bool shown: false
        anchors.top: parent.top
        anchors.horizontalCenter: parent.horizontalCenter
        width: implicitWidth
        height: implicitHeight
        opacity: shown ? 1 : 0
        scale: shown ? 1 : 0.94
        visible: opacity > 0.01
        Behavior on opacity { enabled: JD.animOn; NumberAnimation { duration: shown ? 240 : 120; easing.type: Easing.OutCubic } }
        Behavior on scale { enabled: JD.animOn; NumberAnimation { duration: 320; easing.type: JD.animStyle === "smooth" ? Easing.OutCubic : Easing.OutBack; easing.overshoot: 1.2 } }
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
                    Behavior on height { NumberAnimation { duration: 70 } }
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
                Layout.fillWidth: true
                opacity: JD.detailOpen ? 0 : 1
                Behavior on opacity { NumberAnimation { duration: 150 } }
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
            Label1 { text: JD.flashText; Layout.maximumWidth: 520 }
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
                Label1 { text: n.summary || ""; Layout.fillWidth: true; Layout.maximumWidth: 460 }
                Label2 { visible: !!n.body; text: (n.body || "").replace(/\s+/g, " "); wrapMode: Text.Wrap; maximumLineCount: 2; Layout.fillWidth: true; Layout.maximumWidth: 460 }
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
            Label1 { text: title; font.pixelSize: 14; Layout.fillWidth: true }
            Label2 { text: subtitle; visible: !!subtitle; Layout.fillWidth: true }
        }
    }

    component AnswerView: View {
        implicitWidth: 600
        implicitHeight: Math.min(380, answerText.implicitHeight + 70)
        ColumnLayout {
            anchors.fill: parent
            anchors.margins: 18
            spacing: 12
            RowLayout {
                spacing: 10
                Ring { size: 18 }
                Label1 { text: JD.assistantName; Layout.fillWidth: true }
                Label2 { text: JD.dstate === "speaking" ? JD.tr("говорит") : "" }
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
                    wrapMode: Text.Wrap
                    color: JD.text1
                    font.pixelSize: 15
                    lineHeight: 1.18
                    textFormat: Text.PlainText
                }
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
        implicitWidth: 600
        implicitHeight: cardCol.implicitHeight + 36
        ColumnLayout {
            id: cardCol
            anchors { left: parent.left; right: parent.right; top: parent.top; margins: 18 }
            spacing: 12

            CardHeader {
                Layout.fillWidth: true
                icon: cv.c.type === "calendar" ? "view-calendar" : "mail-message"
                tint: cv.c.type === "mail_sent" ? JD.accentGreen : cv.c.type === "calendar" ? JD.accentOrange : JD.accentRed
                title: ({ mail_draft: JD.tr("Новое письмо"), mail_sent: JD.tr("Письмо отправлено"), mail_read: cv.c.subject || JD.tr("Письмо"),
                          mail_list: JD.tr("Почта"), calendar: JD.tr("Календарь · ") + (cv.c.when || "") })[cv.c.type] || JD.tr("Почта")
                subtitle: ({ mail_draft: JD.tr("черновик · проверьте перед отправкой"), mail_sent: JD.tr("Кому: ") + (cv.c.to || ""),
                             mail_read: JD.tr("от ") + (cv.c.from || ""), mail_list: JD.tr("важные непрочитанные · обработано локально"),
                             calendar: (cv.c.items || []).length ? (cv.c.items || []).length + JD.tr(" · обработано локально") : JD.tr("свободно") })[cv.c.type] || ""
                IconButton { icon: "window-close"; size: 26; onClicked: JD.card = null }
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
                visible: cv.c.type === "mail_draft" || cv.c.type === "mail_read"
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
                        text: cv.c.type === "mail_read" ? (cv.c.text || "") : (cv.c.body || "")
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

        onShownChanged: if (shown) input.forceActiveFocus()
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

            // ask by text
            Rectangle {
                Layout.fillWidth: true
                implicitHeight: 44
                radius: 22
                color: JD.fill1
                border.width: input.activeFocus ? 1 : 0
                border.color: Qt.rgba(JD.accentBlue.r, JD.accentBlue.g, JD.accentBlue.b, 0.7)
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 16
                    anchors.rightMargin: 6
                    spacing: 8
                    TextInput {
                        font.family: JD.fontFamily
                        id: input
                        Layout.fillWidth: true
                        color: JD.text1
                        font.pixelSize: 14
                        clip: true
                        selectByMouse: true
                        onAccepted: if (text.trim()) { JD.send({ cmd: "type", text: text }); text = ""; JD.expanded = false }
                        Text { font.family: JD.fontFamily; text: JD.tr("Спросите или попросите что-нибудь…"); color: JD.text3; font.pixelSize: 14; visible: !input.text && !input.preeditText }
                    }
                    IconButton { icon: "audio-input-microphone"; size: 32; onClicked: { JD.expanded = false; JD.send({ cmd: "toggle" }) } }
                }
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
                            { id: "ollama", label: JD.tr("Локальная"), model: "qwen3.5:9b", hint: JD.tr("приватно") },
                            { id: "openrouter", label: "OpenRouter", model: "nvidia/nemotron-3-super-120b-a12b:free", hint: JD.tr("бесплатно") },
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

            // now playing
            Rectangle {
                visible: !!ev.player
                Layout.fillWidth: true
                implicitHeight: 64
                radius: 18
                color: JD.fill1
                RowLayout {
                    anchors.fill: parent
                    anchors.margins: 10
                    spacing: 12
                    ClippingRectangle {
                        implicitWidth: 44; implicitHeight: 44; radius: 10
                        color: JD.fill2
                        Icon { anchors.centerIn: parent; name: "media-album-cover"; fallback: "audio-x-generic"; implicitSize: 22; visible: art.status !== Image.Ready }
                        Image { id: art; anchors.fill: parent; source: ev.player ? ev.player.trackArtUrl : ""; fillMode: Image.PreserveAspectCrop; asynchronous: true }
                    }
                    ColumnLayout {
                        spacing: 0
                        Layout.fillWidth: true
                        Label1 { text: ev.player ? (ev.player.trackTitle || ev.player.identity) : ""; Layout.fillWidth: true }
                        Label2 { text: ev.player ? (ev.player.trackArtist || "") : ""; Layout.fillWidth: true }
                    }
                    IconButton { icon: "media-skip-backward"; onClicked: ev.player.previous() }
                    IconButton { icon: ev.player && ev.player.isPlaying ? "media-playback-pause" : "media-playback-start"; size: 36; onClicked: ev.player.togglePlaying() }
                    IconButton { icon: "media-skip-forward"; onClicked: ev.player.next() }
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
