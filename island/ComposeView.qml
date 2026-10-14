// Вынесено из shell.qml (Р-80).
import QtQuick
import QtQuick.Layouts

View {
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
        { cmd: "/resume", title: JD.videoLast && JD.videoLast.in_window ? JD.tr("Вернуть видео в островок") : JD.tr("Продолжить ролик"),
          icon: "circle-play", run: () => { if (JD.videoLast && JD.videoLast.in_window) JD.videoPopin(); else JD.videoResume() } },
        { cmd: "/music", title: JD.tr("Сделать музыку"), icon: "audio-x-generic", fill: JD.tr("Сделай трек: ") },
        { cmd: "/install", title: JD.tr("Установить программу"), icon: "system-software-install", fill: JD.tr("Установи ") },
        { cmd: "/screen", title: JD.tr("Что на экране?"), icon: "view-preview", fill: JD.tr("Посмотри на экран и ") },
        { cmd: "/mic", title: JD.micOn ? JD.tr("Выключить микрофон (только текст)") : JD.tr("Включить микрофон"), icon: JD.micOn ? "mic-off" : "mic",
          run: () => JD.setConfig("audio.microphone", !JD.micOn) },
        { cmd: "/chat", title: JD.tr("Чат с ассистентом (без голоса)"), icon: "message-circle", run: () => { JD.chatOpen = true } },
        { cmd: "/mixer", title: JD.tr("Звук и микшер"), icon: "volume-2", run: () => JD.openTools("mixer") },
        { cmd: "/emoji", title: JD.tr("Эмодзи"), icon: "smile", run: () => JD.openTools("emoji") },
        { cmd: "/clip", title: JD.tr("Буфер обмена"), icon: "clipboard", run: () => JD.openTools("clip") },
        { cmd: "/load", title: JD.tr("Нагрузка машины"), icon: "activity", run: () => JD.openTools("load") },
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
                Behavior on color { enabled: JD.animOn; ColorAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
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

// a control-center toggle: a round icon that lights up, the name and its state
