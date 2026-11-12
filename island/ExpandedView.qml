// Вынесено из shell.qml (Р-80).
import QtQuick
import QtQuick.Layouts
import Quickshell
import Quickshell.Services.Pipewire

View {
    id: ev
    property string pendingProvider: ""
    property int voiceWas: 0   // the level the mute button came from, for the way back
    property int musicWas: 0
    readonly property var player: JD.playerInExpanded ? JD.musicPlayer : null
    readonly property var sink: Pipewire.defaultAudioSink
    PwObjectTracker { objects: ev.sink ? [ev.sink] : [] }
    SystemClock { id: evClock; precision: SystemClock.Minutes }
    implicitWidth: 740
    implicitHeight: Math.min(col.implicitHeight + 40, 800)

    // Правка самого меню, как раскладка значков на айфоне: блоки подрагивают, у каждого красный минус
    // (или правая кнопка мыши) прячет его, перетаскиванием меняется порядок, а спрятанное лежит внизу
    // и возвращается нажатием. Порядок хранит GridLayout (Layout.row у блоков), поэтому блоки не пришлось
    // дробить на компоненты; поверх них в режиме правки лежит слой с перехватом мыши (`eo`).
    readonly property bool editing: JD.menuEditing
    readonly property var blockIds: ["ask", "player", "sound", "event", "model", "lists"]
    readonly property var blocks: ({ ask: blkAsk, player: blkPlayer, sound: blkSound, event: blkEvent, model: blkModel, lists: blkLists })
    readonly property var blockNames: ({ ask: JD.tr("Строка запроса"), player: JD.tr("Музыка и плитки"),
        sound: JD.tr("Громкость"), event: JD.tr("Ближайшее событие"), model: JD.tr("Модель"),
        notifs: JD.tr("Уведомления"), recent: JD.tr("Недавнее"),
        top_chat: JD.tr("Кнопка чата"), top_tools: JD.tr("Кнопка инструментов"), top_settings: JD.tr("Кнопка настроек") })
    readonly property var topIds: ["top_chat", "top_tools", "top_settings"]
    // Верхняя кнопка: в правке нажатие прячет её (красный минус в углу), в обычном режиме — делает своё.
    component TopBtn: IconButton {
        id: tb
        property string bid
        property var act
        size: 32
        visible: ev.isShown(tb.bid)
        onClicked: ev.editing ? ev.hide(tb.bid) : tb.act()
        Rectangle {
            visible: ev.editing
            width: 14; height: 14; radius: 7
            anchors { top: parent.top; right: parent.right; margins: -3 }
            color: JD.accentRed
            Rectangle { anchors.centerIn: parent; width: 7; height: 2; color: "white" }
        }
    }
    // Неизвестное из конфига отбрасываем, пропавшее (новый блок после обновления) дописываем в конец.
    // `forced` держит порядок до ответа демона: иначе блок после броска на миг прыгал бы обратно.
    property var forced: null
    readonly property var order: {
        if (forced) return forced
        const saved = Array.isArray(JD.island.menu_order) ? JD.island.menu_order.filter((x, i, a) => blockIds.includes(x) && a.indexOf(x) === i) : []
        return saved.concat(blockIds.filter(x => !saved.includes(x)))
    }
    Connections { target: JD; function onIslandChanged() { ev.forced = null } }
    function row(id) { return 10 + 2 * order.indexOf(id) }   // через один: между блоками остаётся место для хвоста (пересадка модели)
    function isShown(id) { return JD.island["menu_" + id] !== false }
    // Спрятанное, что можно вернуть: пять блоков и две половины нижнего ряда.
    readonly property var hidden: {
        const r = ["ask", "player", "sound", "event", "model"].concat(topIds).filter(id => JD.island["menu_" + id] === false)
        if (JD.island.show_notifications === false) r.push("notifs")
        if (JD.island.menu_recent === false) r.push("recent")
        return r
    }
    function flagKey(id) { return id === "notifs" ? "island.show_notifications" : "island.menu_" + id }
    function hide(id) { JD.setConfig(flagKey(id), false) }
    function unhide(id) { JD.setConfig(flagKey(id), true) }
    function sign(id) { return order.indexOf(id) % 2 ? -1 : 1 }   // соседние блоки качаются в разные стороны
    function resetMenu() {
        forced = null
        JD.setConfig("island.menu_order", blockIds)
        for (const id of ["ask", "player", "sound", "event", "model", "notifs", "recent"].concat(topIds)) unhide(id)
    }

    // Перетаскивание: пока блок тянут, он едет за пальцем (dragDy), порядок меняется при отпускании.
    property string dragId: ""
    property real dragDy: 0
    property real wig: 0
    SequentialAnimation on wig {
        running: ev.editing && JD.animOn
        loops: Animation.Infinite
        NumberAnimation { to: 0.45; duration: 110 }
        NumberAnimation { to: -0.45; duration: 220 }
        NumberAnimation { to: 0; duration: 110 }
    }
    function drop() {
        const id = dragId
        if (!id) return
        const b = blocks[id], down = dragDy > 0, c = b.y + b.height / 2 + dragDy
        let hit = ""
        for (const o of order) {
            const t = blocks[o]
            if (o !== id && t.visible && c >= t.y && c <= t.y + t.height) { hit = o; break }
        }
        dragId = ""; dragDy = 0
        if (!hit) return
        const next = order.filter(x => x !== id)
        next.splice(next.indexOf(hit) + (down ? 1 : 0), 0, id)
        forced = next
        JD.setConfig("island.menu_order", next)
    }
    Shortcut { sequence: "Escape"; enabled: JD.menuEditing; onActivated: JD.menuEditing = false }
    // Долгое нажатие на пустое место меню: тот же вход, что и карандаш.
    TapHandler { onLongPressed: JD.menuEditing = true }

    function setting(key, value) { JD.setConfig(key, value) }
    function ask(text) { JD.expanded = false; JD.send({ cmd: "type", text: text }) }
    // Выключить голос можно двумя разными способами, и раньше плитка знала только один: она
    // трогала движок, а «молчи» её не касалось — нажатие на выключенной молчанием плитке
    // ничего не возвращало. Теперь сначала снимается то, чем голос выключили на самом деле.
    function toggleVoice() {
        if (JD.muted) { JD.setMuted(false); return }
        if (JD.voiceOn) { setting("tts.previous_engine", JD.settings.tts_engine || "silero"); setting("tts.engine", "none") }
        else setting("tts.engine", JD.settings.tts_previous || "silero")
    }

    Flickable {
        id: evFlick
        anchors.fill: parent
        contentHeight: col.implicitHeight + 40
        clip: true
        interactive: contentHeight > height
        boundsBehavior: Flickable.StopAtBounds

    GridLayout {
        id: col
        x: 20
        y: 20
        width: evFlick.width - 40
        columns: 1
        rowSpacing: 14
        columnSpacing: 0

        // ── header: who, what it is doing · time, date, weather · settings
        RowLayout {
            Layout.row: 0
            Layout.fillWidth: true
            spacing: 14
            Orb { visible: JD.orbsOn; main: true; size: 36 }
            Ring { size: 36; visible: !JD.orbsOn }
            // the status takes whatever width is left and elides: a long request (plus «Стоп») used to
            // push the whole menu past the island's right edge
            ColumnLayout {
                spacing: 1
                Layout.fillWidth: true
                Layout.minimumWidth: 0
                Label1 { text: JD.assistantName; font.pixelSize: 18; font.weight: Font.Bold; Layout.fillWidth: true }
                Label2 {
                    Layout.fillWidth: true
                    Layout.minimumWidth: 0
                    text: JD.workers > 0 ? JD.tr("Клод работает") + (JD.workers > 1 ? " ×" + JD.workers : "")
                        // Р3-5: длинная подсказка обрезалась многоточием; клавиша — единственное, что
                        // из неё нужно, и она помещается.
                        : ({ idle: JD.tr("Готов · ") + (JD.micOn ? (JD.hotkeys.talk || "Meta+J") : (JD.hotkeys.type || "Meta+K")),
                             listening: JD.tr("Слушаю"), transcribing: JD.tr("Распознаю"), thinking: JD.activity || JD.tr("Работаю"),
                             speaking: JD.tr("Говорит"), approval: JD.tr("Ждёт подтверждения"), offline: JD.tr("Демон не запущен") })[JD.dstate] || JD.dstate
                    color: JD.workers > 0 ? JD.accentPurple : JD.dstate === "offline" ? JD.accentRed : JD.text2
                }
            }
            ColumnLayout {
                spacing: 0
                Text { text: Qt.formatTime(evClock.date, "HH:mm"); color: JD.text1; font.family: JD.fontFamily; font.pixelSize: 22; font.weight: Font.Bold; font.features: { "tnum": 1 }; Layout.alignment: Qt.AlignRight }
                Label2 { text: evClock.date.toLocaleDateString(Qt.locale(JD.lang === "ru" ? "ru_RU" : "en_US"), "dddd, d MMMM"); font.pixelSize: 11; Layout.alignment: Qt.AlignRight }
            }
            Rectangle {
                visible: !!JD.weather
                implicitWidth: wRow.implicitWidth + 20; implicitHeight: 44; radius: 14
                color: JD.fill1
                RowLayout {
                    id: wRow
                    anchors.centerIn: parent
                    spacing: 6
                    Image { source: JD.weather ? Quickshell.shellDir + "/icons/" + JD.weather.icon + ".svg" : ""; sourceSize: Qt.size(40, 40); Layout.preferredWidth: 20; Layout.preferredHeight: 20 }
                    ColumnLayout {
                        spacing: -2
                        Text { text: JD.weather ? (JD.weather.temp > 0 ? "+" : "") + JD.weather.temp + "°" : ""; color: JD.text1; font.family: JD.fontFamily; font.pixelSize: 14; font.weight: Font.DemiBold }
                        Label2 { text: JD.weather ? JD.tr(JD.weather.text || "") : ""; font.pixelSize: 10; Layout.maximumWidth: 90 }
                    }
                }
            }
            PillButton {
                visible: JD.dstate !== "idle" && JD.dstate !== "offline" || JD.workers > 0
                label: JD.tr("Стоп"); tint: JD.accentRed
                onClicked: JD.send({ cmd: "stop" })
            }
            // П14: громкость голоса сверху убрана — такая же есть в блоке «Громкость». Верхние кнопки
            // прячутся в правке, как и блоки; «Править» стоит последней перед крестиком и не прячется,
            // иначе спрятав всё, человек не нашёл бы, как вернуть.
            TopBtn { bid: "top_chat"; icon: "message-circle"; act: () => { JD.expanded = false; JD.chatOpen = true } }   // отдельный чат: файлы, история
            TopBtn { bid: "top_tools"; icon: "wand-sparkles"; act: () => JD.openTools("emoji") }
            TopBtn { bid: "top_settings"; icon: "configure"; act: () => JD.openSettings("general") }
            IconButton { icon: "pencil"; size: 32; onClicked: JD.menuEditing = !JD.menuEditing }   // правка меню; правка островка — из неё же
            IconButton { icon: "window-close"; size: 32; onClicked: JD.expanded = false }
        }

        // update available
        Rectangle {
            visible: !!JD.update
            Layout.row: 1
            Layout.fillWidth: true
            implicitHeight: 46
            radius: 16
            color: Qt.rgba(JD.accentBlue.r, JD.accentBlue.g, JD.accentBlue.b, 0.16)
            RowLayout {
                anchors { fill: parent; leftMargin: 14; rightMargin: 7 }
                spacing: 10
                Icon { name: "system-software-update"; implicitSize: 18 }
                Label1 { text: JD.tr("Доступно обновление JustDay") }
                Label2 { text: JD.update ? (JD.update.changes || [])[0] || "" : ""; Layout.fillWidth: true }
                PillButton { label: JD.tr("Обновить"); tint: JD.accentBlue; onClicked: JD.runUpdate() }
            }
        }

        // ── ask by text (or the mic)
        Rectangle {
            visible: ev.isShown("ask")
            id: blkAsk
            Layout.row: ev.row("ask")
            rotation: ev.editing ? ev.wig * ev.sign("ask") : 0
            transform: Translate { y: ev.dragId === "ask" ? ev.dragDy : 0 }
            z: ev.dragId === "ask" ? 5 : 0
            Layout.fillWidth: true
            implicitHeight: 46
            radius: 23
            color: askHover.hovered ? JD.fill2 : JD.fill1
            Behavior on color { enabled: JD.animOn; ColorAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
            RowLayout {
                anchors { fill: parent; leftMargin: 16; rightMargin: 6 }
                spacing: 8
                Icon { name: "search"; fallback: "edit-find"; implicitSize: 16; opacity: 0.6 }
                Text { font.family: JD.fontFamily; text: JD.tr("Спросите или попросите что-нибудь…"); color: JD.text3; font.pixelSize: 14; Layout.fillWidth: true }
                Rectangle {
                    visible: !!JD.hotkeys.type
                    implicitWidth: hk.implicitWidth + 12; implicitHeight: 22; radius: 6
                    color: JD.fill1
                    Text { id: hk; anchors.centerIn: parent; text: JD.hotkeys.type || ""; color: JD.text2; font.family: JD.fontFamily; font.pixelSize: 11 }
                }
                IconButton { visible: JD.micOn; icon: "audio-input-microphone"; size: 34; onClicked: { JD.expanded = false; JD.send({ cmd: "listen" }) } }
            }
            HoverHandler { id: askHover; cursorShape: Qt.IBeamCursor }
            TapHandler { onTapped: JD.openCompose() }
        }

        // ── now playing  |  toggles
        RowLayout {
            visible: ev.isShown("player")
            id: blkPlayer
            Layout.row: ev.row("player")
            rotation: ev.editing ? ev.wig * ev.sign("player") : 0
            transform: Translate { y: ev.dragId === "player" ? ev.dragDy : 0 }
            z: ev.dragId === "player" ? 5 : 0
            Layout.fillWidth: true
            spacing: 12
            Rectangle {
                id: np
                readonly property bool own: JD.musicOn
                readonly property bool any: own || !!ev.player
                readonly property var p: JD.player || ({})
                property color tint: own ? JD.artTint(p.color) : JD.accentPink
                Behavior on tint { enabled: JD.animOn; ColorAnimation { duration: JD.durSlow; easing.type: JD.easeOut } }
                Layout.fillWidth: true
                Layout.preferredWidth: 1.15
                implicitHeight: 136 + (seek.visible ? 22 : 0)
                radius: 20
                color: JD.fill1
                clip: true
                Rectangle {
                    visible: np.any
                    anchors.fill: parent
                    radius: parent.radius
                    gradient: Gradient {
                        orientation: Gradient.Horizontal
                        GradientStop { position: 0; color: Qt.rgba(np.tint.r, np.tint.g, np.tint.b, 0.28) }
                        GradientStop { position: 1; color: "transparent" }
                    }
                }
                // something plays
                ColumnLayout {
                    visible: np.any
                    anchors { fill: parent; margins: 12 }
                    spacing: 8
                    RowLayout {
                        spacing: 12
                        Art {
                            size: 62; tint: np.tint; src: np.own ? (np.p.thumb || "") : (ev.player ? ev.player.trackArtUrl || "" : "")
                            HoverHandler { enabled: np.own; cursorShape: Qt.PointingHandCursor }
                            TapHandler { enabled: np.own; onTapped: { JD.expanded = false; JD.playerOpen = true; JD.artOpen = true } }
                        }
                        ColumnLayout {
                            spacing: 1
                            Layout.fillWidth: true
                            SectionLabel { text: np.own ? (np.p.source ? np.p.source.toUpperCase() : JD.tr("СЕЙЧАС ИГРАЕТ")) : (ev.player ? ev.player.identity.toUpperCase() : ""); color: np.tint; elide: Text.ElideRight; Layout.fillWidth: true }
                            Label1 { text: np.own ? (np.p.title || "") : ev.player ? (JD.cleanTitle(ev.player.trackTitle) || ev.player.identity) : ""; font.pixelSize: 14; Layout.fillWidth: true }
                            Label2 { text: np.own ? (np.p.artist || "") : ev.player ? (ev.player.trackArtist || "") : ""; Layout.fillWidth: true }
                        }
                        IconButton { visible: np.own; icon: "view-fullscreen"; size: 28; Layout.alignment: Qt.AlignTop
                                     onClicked: { JD.expanded = false; JD.playerOpen = true } }
                    }
                    // Полоса времени чужого плеера: где мы в треке, и потянуть — перемотать.
                    // Позицию MPRIS сам не присылает, её надо спрашивать: раз в секунду, пока
                    // карточка открыта и играет.
                    RowLayout {
                        id: seek
                        readonly property var pl: np.own ? null : ev.player
                        visible: !!pl && pl.lengthSupported && pl.length > 0
                        property real dragAt: -1
                        readonly property real frac: dragAt >= 0 ? dragAt : (pl && pl.length > 0 ? Math.max(0, Math.min(1, pl.position / pl.length)) : 0)
                        Layout.fillWidth: true
                        spacing: 8
                        Timer { interval: 1000; repeat: true; triggeredOnStart: true
                                running: seek.visible && ev.shown && seek.pl.isPlaying; onTriggered: seek.pl.positionChanged() }
                        Label2 { text: JD.fmtTime(seek.frac * (seek.pl ? seek.pl.length : 0)); font.pixelSize: 11; font.features: { "tnum": 1 } }
                        Item {
                            Layout.fillWidth: true
                            implicitHeight: 16
                            Rectangle {
                                anchors.verticalCenter: parent.verticalCenter
                                width: parent.width; height: seekHit.containsMouse || seek.dragAt >= 0 ? 6 : 4; radius: height / 2
                                color: JD.fill2
                                Behavior on height { enabled: JD.animOn; NumberAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
                                Rectangle { width: parent.width * seek.frac; height: parent.height; radius: parent.radius; color: np.tint }
                            }
                            MouseArea {
                                id: seekHit
                                anchors.fill: parent
                                enabled: !!seek.pl && seek.pl.canSeek
                                hoverEnabled: true
                                cursorShape: enabled ? Qt.PointingHandCursor : Qt.ArrowCursor
                                function at(mx) { return Math.max(0, Math.min(1, mx / width)) }
                                onPressed: m => seek.dragAt = at(m.x)
                                onPositionChanged: m => { if (pressed) seek.dragAt = at(m.x) }
                                onReleased: {
                                    seek.pl.position = seek.dragAt * seek.pl.length
                                    seek.pl.positionChanged()
                                    seek.dragAt = -1
                                }
                                onCanceled: seek.dragAt = -1
                            }
                        }
                        Label2 { text: JD.fmtTime(seek.pl ? seek.pl.length : 0); font.pixelSize: 11; font.features: { "tnum": 1 } }
                    }
                    RowLayout {
                        spacing: 8
                        ModeButton { visible: np.own; icon: "media-playlist-shuffle"; on: !!np.p.shuffle; tint: np.tint
                                     onClicked: JD.media("shuffle", np.p.shuffle ? "off" : "on") }
                        Item { Layout.fillWidth: true }
                        IconButton { icon: "media-skip-backward"; size: 34; onClicked: np.own ? JD.media("prev") : ev.player.previous() }
                        Rectangle {
                            implicitWidth: 42; implicitHeight: 42; radius: 21
                            color: np.tint
                            PlayGlyph { anchors.centerIn: parent; size: 16; tint: "black"; paused: np.own ? !!np.p.paused : !(ev.player && ev.player.isPlaying) }
                            HoverHandler { cursorShape: Qt.PointingHandCursor }
                            TapHandler { onTapped: np.own ? JD.media("toggle") : ev.player.togglePlaying() }
                        }
                        IconButton { icon: "media-skip-forward"; size: 34; onClicked: np.own ? JD.media("next") : ev.player.next() }
                        Item { Layout.fillWidth: true }
                        ModeButton { visible: np.own; icon: np.p.repeat === "one" ? "media-repeat-single" : "media-playlist-repeat"
                                     on: !!np.p.repeat && np.p.repeat !== "off"; tint: np.tint
                                     onClicked: JD.media("repeat", ({ off: "all", all: "one", one: "off" })[np.p.repeat || "off"]) }
                    }
                }
                // nothing plays
                ColumnLayout {
                    visible: !np.any
                    anchors { fill: parent; margins: 14 }
                    spacing: 6
                    RowLayout {
                        spacing: 10
                        Rectangle {
                            implicitWidth: 44; implicitHeight: 44; radius: 12
                            color: "#fc3c44"
                            Image { anchors.centerIn: parent; source: Quickshell.shellDir + "/icons/music.svg"; sourceSize: Qt.size(44, 44); width: 22; height: 22 }
                        }
                        ColumnLayout {
                            spacing: 0
                            Label1 { text: JD.tr("Ничего не играет"); font.pixelSize: 14 }
                            Label2 { text: JD.tr("«включи песню…», альбом или плейлист"); font.pixelSize: 11; Layout.fillWidth: true }
                        }
                    }
                    Item { Layout.fillHeight: true }
                    RowLayout {
                        spacing: 8
                        Chip { icon: "media-playback-start"; label: JD.tr("Включить"); onClicked: JD.openCompose(JD.tr("Включи песню ")) }
                        // закрытый ролик никуда не делся: его можно доглядеть с той же секунды
                        Chip {
                            visible: !!JD.videoLast
                            icon: JD.videoLast && JD.videoLast.in_window ? "go-top" : "video-x-generic"
                            label: JD.videoLast && JD.videoLast.in_window ? JD.tr("Вернуть в островок") : JD.tr("Продолжить ролик")
                            onClicked: { JD.expanded = false
                                         if (JD.videoLast && JD.videoLast.in_window) JD.videoPopin(); else JD.videoResume() }
                        }
                        Chip { icon: "document-open-folder"; label: JD.tr("Моя музыка")
                               onClicked: { JD.expanded = false; JD.playerPage = "library"; JD.libRefresh(); JD.playerOpen = true } }
                    }
                }
            }
            GridLayout {
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                columns: 2
                rowSpacing: 12
                columnSpacing: 12
                Tile { icon: JD.micOn ? "mic" : "mic-off"; title: JD.tr("Микрофон"); onText: JD.tr("голос и текст"); offText: JD.tr("только текст")
                       on: JD.micOn; tint: JD.accentCyan; onToggled: ev.setting("audio.microphone", !JD.micOn) }
                Tile { icon: "audio-speakers"; title: JD.tr("Голос")
                       onText: JD.tr("отвечает вслух")
                       offText: JD.muted ? JD.tr("молчит по просьбе") : JD.tr("только текстом")
                       on: JD.voiceOn; tint: JD.accentBlue; onToggled: ev.toggleVoice() }
                Tile { icon: "audio-lines"; title: JD.tr("Звуки"); onText: JD.tr("сигналы"); offText: JD.tr("тишина")
                       on: !!JD.settings.earcons; tint: JD.accentOrange
                       onToggled: ev.setting("audio.earcons", !JD.settings.earcons) }
                Tile { icon: "preferences-desktop-notification-bell"; title: JD.tr("Уведомления"); onText: JD.tr("на острове"); offText: JD.tr("не беспокоить")
                       on: JD.island.show_notifications !== false; tint: JD.accentPurple
                       onToggled: ev.setting("island.show_notifications", JD.island.show_notifications === false) }
                // Во всю ширину: пятая плитка в сетке на две колонки иначе висела бы одна с дырой рядом.
                Tile { icon: "coffee"; title: JD.tr("Кофе"); onText: JD.tr("экран не гаснет"); offText: JD.tr("экран гаснет сам")
                       on: JD.coffeeOn; tint: JD.accentOrange; Layout.columnSpan: 2
                       onToggled: ev.setting("desktop.coffee", !JD.coffeeOn) }
            }
        }

        // ── sound: the assistant, the music, the whole computer. Three knobs in one card, each one only
        //    moves what it names — turning the assistant down leaves every other app where it was.
        Rectangle {
            visible: ev.isShown("sound")
            id: blkSound
            Layout.row: ev.row("sound")
            rotation: ev.editing ? ev.wig * ev.sign("sound") : 0
            transform: Translate { y: ev.dragId === "sound" ? ev.dragDy : 0 }
            z: ev.dragId === "sound" ? 5 : 0
            Layout.fillWidth: true
            implicitHeight: sndCol.implicitHeight + 24
            radius: 20
            color: JD.fill1
            ColumnLayout {
                id: sndCol
                anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; leftMargin: 10; rightMargin: 16 }
                spacing: 6
                VolumeRow {
                    icon: "sparkles"; label: JD.assistantName; tint: JD.accentBlue
                    value: JD.volume / 100
                    onMoved: v => JD.setVolume(v * 100)
                    onMuteToggled: { const was = JD.volume; JD.setVolume(was > 0 ? 0 : (ev.voiceWas || 100)); ev.voiceWas = was }
                }
                // Чужой плеер — своя ручка, только его громкость: MPRIS, если он её даёт, иначе
                // его поток в PipeWire. Общая «Музыка» ниже двигала лишь нашу музыку и чужую
                // не трогала, а «Компьютер» убавлял заодно и всё остальное.
                VolumeRow {
                    id: otherVol
                    readonly property var pl: JD.musicOn ? null : ev.player
                    readonly property bool viaMpris: !!pl && pl.volumeSupported && pl.canControl
                    readonly property var stream: pl && !viaMpris ? JD.playerStream(pl) : null
                    PwObjectTracker { objects: otherVol.stream ? [otherVol.stream] : [] }
                    property real was: 0.7
                    visible: viaMpris || (!!stream && !!stream.audio)
                    icon: "audio-x-generic"; label: pl ? pl.identity : ""; tint: JD.accentPink
                    value: viaMpris ? pl.volume : (stream && stream.audio ? stream.audio.volume : 0)
                    function put(v) { if (viaMpris) pl.volume = v; else if (stream && stream.audio) stream.audio.volume = v }
                    onMoved: v => put(v)
                    onMuteToggled: { const now = value; put(now > 0 ? 0 : (was || 0.7)); was = now }
                }
                VolumeRow {
                    visible: !otherVol.visible
                    readonly property int level: JD.player && JD.player.volume !== undefined ? JD.player.volume : (JD.mediaCfg.volume !== undefined ? JD.mediaCfg.volume : 70)
                    icon: "audio-x-generic"; label: JD.tr("Музыка")
                    tint: JD.musicOn ? JD.artTint(JD.player.color) : JD.accentPink
                    value: level / 100
                    onMoved: v => JD.media("volume", Math.round(v * 100))
                    onMuteToggled: { JD.media("volume", level > 0 ? 0 : (ev.musicWas || 70)); ev.musicWas = level }
                }
                VolumeRow {
                    visible: !!ev.sink && !!ev.sink.audio
                    icon: "monitor"; label: JD.tr("Система"); tint: "#f5f5f7"
                    value: ev.sink && ev.sink.audio ? (ev.sink.audio.muted ? 0 : ev.sink.audio.volume) : 0
                    onMoved: v => { if (ev.sink && ev.sink.audio) { ev.sink.audio.volume = v; if (v > 0) ev.sink.audio.muted = false } }
                    onMuteToggled: if (ev.sink && ev.sink.audio) ev.sink.audio.muted = !ev.sink.audio.muted
                }
            }
        }

        // ── background jobs: a system update, a build — running while the assistant is free for anything else
        ColumnLayout {
            visible: JD.jobs.length > 0
            Layout.row: 2
            Layout.fillWidth: true
            spacing: 6
            Repeater {
                model: JD.jobs.slice(0, 3)
                Rectangle {
                    required property var modelData
                    readonly property bool running: modelData.state === "running"
                    readonly property color tint: running ? JD.accentBlue : modelData.state === "done" ? JD.accentGreen : JD.accentRed
                    Layout.fillWidth: true
                    implicitHeight: 44
                    radius: 14
                    color: jobHover.hovered ? JD.fill2 : JD.fill1
                    RowLayout {
                        anchors { fill: parent; leftMargin: 12; rightMargin: 8 }
                        spacing: 10
                        Item {
                            implicitWidth: 18; implicitHeight: 18
                            Ring { anchors.centerIn: parent; size: 16; visible: parent.parent.parent.running; spinning: true; tint: JD.accentBlue }
                            Icon { anchors.centerIn: parent; visible: !parent.parent.parent.running; implicitSize: 16; tint: parent.parent.parent.tint
                                   name: modelData.state === "done" ? "check" : "window-close" }
                        }
                        Label1 { text: modelData.title; font.pixelSize: 13; Layout.fillWidth: true }
                        Label2 {
                            text: parent.parent.running ? JD.tr("в фоне") : modelData.state === "done" ? JD.tr("готово")
                                  : modelData.state === "stopped" ? JD.tr("остановлено") : JD.tr("ошибка")
                            font.pixelSize: 11; color: parent.parent.running ? JD.text2 : parent.parent.tint
                        }
                        Text {
                            text: JD.jobTime(modelData)
                            color: JD.text1; font.family: JD.fontFamily; font.pixelSize: 15
                            font.weight: Font.DemiBold; font.features: { "tnum": 1 }
                        }
                        IconButton { visible: parent.parent.running; icon: "media-playback-stop"; size: 26
                                     onClicked: JD.send({ cmd: "job_stop", id: modelData.id }) }
                    }
                    HoverHandler { id: jobHover }
                }
            }
        }

        // ── timers and alarms: what is running, how long is left, and a way to stop it
        ColumnLayout {
            visible: JD.reminders.length > 0
            Layout.row: 3
            Layout.fillWidth: true
            spacing: 6
            Repeater {
                model: JD.reminders.slice(0, 3)
                Rectangle {
                    required property var modelData
                    readonly property bool isTimer: modelData.kind === "timer"
                    Layout.fillWidth: true
                    implicitHeight: 44
                    radius: 14
                    color: remHover.hovered ? JD.fill2 : JD.fill1
                    RowLayout {
                        anchors { fill: parent; leftMargin: 12; rightMargin: 8 }
                        spacing: 10
                        Icon { name: parent.parent.isTimer ? "timer" : "bell-ring"; implicitSize: 17; tint: JD.accentOrange }
                        Label1 {
                            text: modelData.label || (parent.parent.isTimer ? JD.tr("Таймер") : JD.tr("Будильник"))
                            font.pixelSize: 13; Layout.fillWidth: true
                        }
                        Label2 {
                            text: modelData.repeat === "daily" ? JD.tr("каждый день") : ""
                            font.pixelSize: 11
                        }
                        Text {
                            text: JD.reminderLeft(modelData)
                            color: JD.text1; font.family: JD.fontFamily; font.pixelSize: 15
                            font.weight: Font.DemiBold; font.features: { "tnum": 1 }
                        }
                        IconButton { icon: "window-close"; size: 26
                                     onClicked: JD.send({ cmd: "reminder_cancel", which: modelData.id }) }
                    }
                    HoverHandler { id: remHover }
                }
            }
        }

        // ── next event
        Rectangle {
            visible: !!JD.nextEvent && ev.isShown("event")
            id: blkEvent
            Layout.row: ev.row("event")
            rotation: ev.editing ? ev.wig * ev.sign("event") : 0
            transform: Translate { y: ev.dragId === "event" ? ev.dragDy : 0 }
            z: ev.dragId === "event" ? 5 : 0
            Layout.fillWidth: true
            implicitHeight: 40
            radius: 14
            color: JD.fill1
            RowLayout {
                anchors { fill: parent; leftMargin: 12; rightMargin: 12 }
                spacing: 10
                Rectangle { implicitWidth: 4; implicitHeight: 22; radius: 2; color: JD.accentOrange }
                Label1 { text: JD.nextEvent ? Qt.formatTime(new Date(JD.nextEvent.start), "HH:mm") : ""; color: JD.accentOrange }
                Label1 { text: JD.nextEvent ? JD.nextEvent.title : ""; font.weight: Font.Normal; Layout.fillWidth: true }
            }
        }

        // ── model
        RowLayout {
            visible: ev.isShown("model")
            id: blkModel
            Layout.row: ev.row("model")
            rotation: ev.editing ? ev.wig * ev.sign("model") : 0
            transform: Translate { y: ev.dragId === "model" ? ev.dragDy : 0 }
            z: ev.dragId === "model" ? 5 : 0
            Layout.fillWidth: true
            spacing: 10
            SectionLabel { text: JD.tr("МОДЕЛЬ") }
            Repeater {
                model: [
                    { id: "claude", label: "Claude", model: "sonnet", hint: JD.tr("подписка") },
                    { id: "ollama_cloud", label: JD.tr("Бесплатная"), model: "kimi-k3:cloud", hint: JD.tr("облако") },
                    { id: "ollama", label: JD.tr("Локальная"), model: "qwen3.5:9b", hint: JD.tr("приватно") },
                    { id: "openrouter", label: "OpenRouter", model: "openrouter/free", hint: JD.tr("50/день") },
                    { id: "deepseek", label: "DeepSeek", model: "deepseek-v4-pro", hint: JD.tr("ключ") }
                ]
                Rectangle {
                    required property var modelData
                    readonly property bool current: (ev.pendingProvider || JD.settings.provider) === modelData.id
                    Layout.fillWidth: true
                    implicitHeight: 40
                    radius: 12
                    color: current ? JD.text1 : (segHover.hovered ? JD.fill2 : JD.fill1)
                    Behavior on color { enabled: JD.animOn; ColorAnimation { duration: JD.durBase; easing.type: JD.easeOut } }
                    ColumnLayout {
                        anchors.centerIn: parent
                        spacing: -1
                        Text { font.family: JD.fontFamily; text: modelData.label; color: parent.parent.current ? "black" : JD.text1; font.pixelSize: 12; font.weight: Font.DemiBold; Layout.alignment: Qt.AlignHCenter }
                        Text { font.family: JD.fontFamily; text: modelData.hint; color: parent.parent.current ? Qt.rgba(0, 0, 0, 0.55) : JD.text3; font.pixelSize: 10; Layout.alignment: Qt.AlignHCenter }
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
            Layout.row: ev.row("model") + 1
            Layout.fillWidth: true
            spacing: 10
            Label2 { text: JD.tr("Модель сменится после перезапуска (текущий разговор начнётся заново)"); Layout.fillWidth: true }
            PillButton { label: JD.tr("Перезапустить"); tint: JD.accentBlue; onClicked: { JD.run(["restart"]); ev.pendingProvider = "" } }
        }

        // ── notifications | recent
        RowLayout {
            visible: (JD.notifications.length > 0 && JD.island.show_notifications !== false) || (JD.history.length > 0 && JD.island.menu_recent !== false)
            id: blkLists
            Layout.row: ev.row("lists")
            rotation: ev.editing ? ev.wig * ev.sign("lists") : 0
            transform: Translate { y: ev.dragId === "lists" ? ev.dragDy : 0 }
            z: ev.dragId === "lists" ? 5 : 0
            Layout.fillWidth: true
            spacing: 14
            ColumnLayout {
                visible: JD.notifications.length > 0 && JD.island.show_notifications !== false
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                Layout.alignment: Qt.AlignTop
                spacing: 4
                RowLayout {
                    Layout.preferredHeight: 18
                    SectionLabel { text: JD.tr("УВЕДОМЛЕНИЯ"); Layout.fillWidth: true }
                    Label2 { text: JD.tr("очистить"); color: JD.accentBlue; font.pixelSize: 11
                             TapHandler { onTapped: JD.notifications = [] } HoverHandler { cursorShape: Qt.PointingHandCursor } }
                }
                Repeater {
                    model: JD.notifications.slice(0, 3)
                    Rectangle {
                        required property var modelData
                        Layout.fillWidth: true
                        implicitHeight: 46
                        radius: 12
                        clip: true
                        color: nHover.hovered ? JD.fill2 : JD.fill1
                        RowLayout {
                            anchors { fill: parent; leftMargin: 10; rightMargin: 10 }
                            spacing: 9
                            Icon { name: modelData.icon || (modelData.app || "").toLowerCase(); fallback: "preferences-desktop-notification-bell"; implicitSize: 22 }
                            ColumnLayout {
                                spacing: 0
                                Layout.fillWidth: true
                                RowLayout {
                                    Label1 { text: JD.flat(modelData.summary); font.pixelSize: 12; Layout.fillWidth: true
                                             maximumLineCount: 1; Layout.maximumHeight: 16 }
                                    Label2 { text: modelData.ts; color: JD.text3; font.pixelSize: 10; font.features: { "tnum": 1 } }
                                }
                                Label2 { text: JD.flat(modelData.body); font.pixelSize: 11; Layout.fillWidth: true
                                         maximumLineCount: 1; Layout.maximumHeight: 15 }
                            }
                        }
                        HoverHandler { id: nHover; cursorShape: Qt.PointingHandCursor }
                        TapHandler { onTapped: JD.openNotification(modelData) }
                    }
                }
            }
            ColumnLayout {
                visible: JD.history.length > 0 && JD.island.menu_recent !== false
                Layout.fillWidth: true
                Layout.preferredWidth: 1
                Layout.alignment: Qt.AlignTop
                spacing: 4
                SectionLabel { text: JD.tr("НЕДАВНЕЕ"); Layout.preferredHeight: 18; verticalAlignment: Text.AlignVCenter }
                Repeater {
                    model: JD.history.slice(0, 3)
                    Rectangle {
                        required property var modelData
                        Layout.fillWidth: true
                        implicitHeight: 46
                        radius: 12
                        clip: true
                        color: hHover.hovered ? JD.fill2 : JD.fill1
                        ColumnLayout {
                            anchors { fill: parent; leftMargin: 12; rightMargin: 10 }
                            spacing: 0
                            RowLayout {
                                Label1 { text: JD.flat(modelData.q); font.pixelSize: 12; Layout.fillWidth: true
                                         maximumLineCount: 1; Layout.maximumHeight: 16 }
                                Label2 { text: modelData.ts; color: JD.text3; font.pixelSize: 10; font.features: { "tnum": 1 } }
                            }
                            Label2 { text: JD.flat(modelData.a); font.pixelSize: 11; Layout.fillWidth: true
                                     maximumLineCount: 1; Layout.maximumHeight: 15 }
                        }
                        HoverHandler { id: hHover; cursorShape: Qt.PointingHandCursor }
                        TapHandler { onTapped: JD.openCompose(modelData.q) }
                    }
                }
            }
        }

        // ── в режиме правки: спрятанное и кнопки выхода
        ColumnLayout {
            visible: ev.editing
            Layout.row: 100
            Layout.fillWidth: true
            spacing: 8
            Label2 { text: ev.hidden.length ? JD.tr("Спрятано, нажмите, чтобы вернуть:") : JD.tr("Красный минус или правая кнопка прячет блок, перетаскивание меняет порядок."); Layout.fillWidth: true; wrapMode: Text.WordWrap }
            Flow {
                Layout.fillWidth: true
                spacing: 8
                Repeater {
                    model: ev.hidden
                    PillButton { required property string modelData; label: "+ " + ev.blockNames[modelData]; onClicked: ev.unhide(modelData) }
                }
            }
            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                PillButton { label: JD.tr("Вернуть как было"); onClicked: ev.resetMenu() }
                Item { Layout.fillWidth: true }
                PillButton { label: JD.tr("Правка островка"); onClicked: { JD.menuEditing = false; JD.expanded = false; JD.editMode = true } }
                PillButton { label: JD.tr("Готово"); tint: JD.accentBlue; onClicked: JD.menuEditing = false }
            }
        }
    }

    // Слой правки: лежит поверх блоков, глотает нажатия (иначе кнопки под ним продолжали бы работать),
    // ловит перетаскивание и правую кнопку. Шевелится вместе с блоком, чтобы рамка не отставала.
    Item {
        id: eo
        visible: ev.editing
        width: evFlick.width
        height: col.implicitHeight + 40
        Repeater {
            model: ev.blockIds
            Item {
                id: slot
                required property string modelData
                readonly property Item blk: ev.blocks[modelData]
                readonly property bool lists: modelData === "lists"
                readonly property bool hasNotifs: JD.notifications.length > 0 && JD.island.show_notifications !== false
                readonly property bool hasRecent: JD.history.length > 0 && JD.island.menu_recent !== false
                visible: !!blk && blk.visible
                x: col.x + blk.x
                y: col.y + blk.y + (ev.dragId === modelData ? ev.dragDy : 0)
                width: blk.width
                height: blk.height
                z: ev.dragId === modelData ? 10 : 1
                rotation: ev.editing ? ev.wig * ev.sign(modelData) : 0
                Rectangle {
                    anchors.fill: parent
                    radius: 16
                    color: ev.dragId === slot.modelData ? Qt.rgba(1, 1, 1, 0.06) : "transparent"
                    border.width: 1
                    border.color: Qt.rgba(1, 1, 1, 0.16)
                }
                MouseArea {
                    anchors.fill: parent
                    acceptedButtons: Qt.AllButtons
                    cursorShape: ev.dragId === slot.modelData ? Qt.ClosedHandCursor : Qt.OpenHandCursor
                    DragHandler {
                        target: null
                        xAxis.enabled: false
                        onActiveChanged: { if (active) { ev.dragId = slot.modelData; ev.dragDy = 0 } else ev.drop() }
                        onTranslationChanged: if (active) ev.dragDy = translation.y
                    }
                    TapHandler {
                        acceptedButtons: Qt.RightButton
                        onTapped: point => {
                            if (!slot.lists) ev.hide(slot.modelData)
                            else if (slot.hasNotifs && (point.position.x < slot.width / 2 || !slot.hasRecent)) ev.hide("notifs")
                            else if (slot.hasRecent) ev.hide("recent")
                        }
                    }
                }
                // красный минус: у нижнего ряда их два, по одному на половину
                Repeater {
                    model: slot.lists ? [{ id: "notifs", on: slot.hasNotifs, at: 0 }, { id: "recent", on: slot.hasRecent, at: slot.hasNotifs ? slot.width / 2 : 0 }]
                                      : [{ id: slot.modelData, on: true, at: 0 }]
                    Rectangle {
                        required property var modelData
                        visible: modelData.on
                        x: modelData.at - 7
                        y: -7
                        width: 26; height: 26; radius: 13
                        color: "#E5484D"
                        border.width: 2
                        border.color: Qt.rgba(0, 0, 0, 0.6)
                        Icon { anchors.centerIn: parent; name: "minus"; implicitSize: 14 }
                        TapHandler { onTapped: ev.hide(modelData.id) }
                        HoverHandler { cursorShape: Qt.PointingHandCursor }
                    }
                }
            }
        }
    }
    }
}
