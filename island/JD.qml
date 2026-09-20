pragma Singleton
// Shared state of the Dynamic Island: daemon connection, live status, theme, UI mode.
import QtQuick
import Quickshell
import Quickshell.Io

Singleton {
    id: jd

    // ───────────── live state from the daemon ─────────────
    property string dstate: "offline"      // idle listening transcribing thinking speaking approval offline
    property real level: 0
    property int workers: 0
    property var settings: ({})
    property var history: []
    property var weather: null
    property var notification: null   // desktop notification being shown
    property var notifications: []    // recent ones for the menu
    property bool notifExpanded: false  // the whole text, unfolded inside the island (the ⌄ button)
    // a tap on a notification: its app comes forward (Telegram, Discord…) and the island lets it go
    function openNotification(n) {
        if (!n) return
        send({ cmd: "notification_open", app: n.app || "", desktop: n.desktop || n.icon || "" })
        if (n === notification) { notification = null; notifExpanded = false }
        expanded = false
    }
    function dismissNotification() { notification = null; notifExpanded = false }
    property var alarm: null          // the timer or alarm ringing right now
    property var reminders: []        // timers, alarms and reminders still waiting, soonest first
    readonly property var runningTimer: {   // the soonest countdown, for the collapsed island
        for (const r of reminders)
            if (r.kind === "timer" && r.at - tick < 3600) return r
        return null
    }
    function reminderLeft(r) {         // «12:04» for an alarm, «4:31» counting down for a timer
        if (!r) return ""
        const secs = Math.max(0, Math.round(r.at - tick / 1))
        if (r.kind !== "timer") return Qt.formatTime(new Date(r.at * 1000), "HH:mm")
        const m = Math.floor(secs / 60), s = secs % 60
        return m >= 60 ? Math.floor(m / 60) + ":" + String(m % 60).padStart(2, "0") + ":" + String(s).padStart(2, "0")
                       : m + ":" + String(s).padStart(2, "0")
    }
    property real tick: Date.now() / 1000          // one clock for every countdown on screen
    Timer { running: jd.reminders.length > 0; interval: 500; repeat: true; onTriggered: jd.tick = Date.now() / 1000 }
    function dismissAlarm(id) { send({ cmd: "alarm_dismiss", id: id || "" }) }

    property var nextEvent: null      // calendar event starting within 2 hours
    property var update: null      // {behind, changes} when GitHub has a newer version
    function runUpdate() { Quickshell.execDetached(["kitty", "--hold", "justday", "update"]); closeAll() }

    property string activity: ""           // one line of what is happening (heard text, tool, draft)
    // the status line is one line by definition: a pasted script would otherwise stretch the island
    function flat(s) { return String(s || "").replace(/\s+/g, " ").trim().slice(0, 160) }
    property string activityIcon: ""
    property real busySince: Date.now()
    property string answer: ""
    property bool answerOpen: false
    property var card: null
    property string approvalText: ""
    property string approvalReason: ""
    property string flashText: ""
    property string flashIcon: ""
    property color flashColor: accentGreen

    // ───────────── UI state ─────────────
    property bool expanded: false
    // the text field (Meta+K, click, or the talk key in keyboard mode)
    property bool composeOpen: false
    property string composeText: ""
    property var composeContext: ({})     // {selection} — text selected on screen when the field was opened
    property int composeSerial: 0         // bumps on every open, so a second press re-focuses the field
    property var sent: []                 // what was typed this session, newest first (↑ in the field)
    readonly property var hotkeys: settings.hotkeys || ({})
    readonly property bool micOn: settings.microphone !== false
    readonly property bool voiceOn: settings.voice !== false
    // JustDay's own loudness (voice and signals), 0–100. The system volume belongs to the system.
    readonly property int volume: settings.volume === undefined ? 100 : settings.volume
    function setVolume(v) {
        v = Math.max(0, Math.min(100, Math.round(v)))
        settings = Object.assign({}, settings, { volume: v })   // the slider follows the finger, not the socket
        send({ cmd: "volume", value: v })
    }
    function openCompose(text, context) {
        composeText = text || ""
        composeContext = context || ({})
        settingsOpen = false
        expanded = false
        composeOpen = true
        composeSerial++
    }
    function submit(text) {
        text = text.trim()
        if (!text) return
        const msg = { cmd: "type", text: text }
        if (composeContext.selection) msg.context = composeContext
        send(msg)
        sent = [text].concat(sent.filter(t => t !== text)).slice(0, 30)
        composeOpen = false
        composeContext = ({})
        composeText = ""
    }
    // ───────────── our music player and the video inside the island ─────────────
    property var player: null           // {title, artist, thumb, color, pos, duration, paused, index, count, next, volume, loading}
    property real playerAt: Date.now()  // when `pos` was reported: the island counts on by itself between updates
    property bool playerOpen: false     // the big player (a click on the music pill)
    property var video: null            // {title, channel, thumb, file, progress} — a video playing inside the island
    property bool videoBig: false
    signal videoCommand(string action)  // pause / resume / toggle / restart from the daemon ("пауза" by voice)
    readonly property var mediaCfg: settings.media || ({})
    readonly property bool musicOn: !!player && (!!player.file || !!player.loading)
    // the pill stays while music plays and for a little while after a pause
    property bool pauseGrace: false
    readonly property bool musicShown: musicOn && mediaCfg.show_player !== false && (!player.paused || !!player.loading || pauseGrace || peeking)
    Timer { id: graceTimer; interval: 6000; onTriggered: jd.pauseGrace = false }
    function media(action, value) { send({ cmd: "media", action: action, value: value === undefined ? null : value }) }
    function playerPos(now) {
        if (!player) return 0
        const p = player.pos + (player.paused || player.loading ? 0 : (now - playerAt) / 1000)
        return player.duration > 0 ? Math.min(player.duration, p) : p
    }
    function fmtTime(s) {
        s = Math.max(0, Math.floor(s))
        const h = Math.floor(s / 3600), m = Math.floor(s % 3600 / 60), sec = s % 60
        return (h ? h + ":" + String(m).padStart(2, "0") : m) + ":" + String(sec).padStart(2, "0")
    }
    // the cover's colour, made vivid enough for bars on black
    function artTint(c) {
        if (!c) return accentPink
        const q = Qt.color(c)
        return Qt.hsla(q.hslHue < 0 ? 0.95 : q.hslHue, Math.max(0.55, q.hslSaturation), Math.min(0.68, Math.max(0.52, q.hslLightness)), 1)
    }

    property bool settingsOpen: false
    property string settingsPage: "general"
    function openSettings(page) { settingsPage = page || "general"; settingsOpen = true; expanded = false }
    function closeAll() { settingsOpen = false; expanded = false; composeOpen = false; playerOpen = false }
    function openManual() { Quickshell.execDetached(["xdg-open", "https://github.com/0nigiris/JustDay/blob/main/docs/MANUAL.md"]); closeAll() }

    // animation style from settings: spring (bouncy), smooth (no overshoot) or off
    readonly property var island: settings.island || ({})
    readonly property string animStyle: island.animations || "spring"
    readonly property bool animOn: animStyle !== "off"
    readonly property real springK: animStyle === "smooth" ? 7.5 : 4.2
    readonly property real springDamping: animStyle === "smooth" ? 1.0 : 0.36
    function dur(ms) { return animOn ? ms : 0 }
    property bool peeking: false
    property bool detailOpen: false
    property bool islandHovered: false

    readonly property string mode: {
        if (alarm) return "alarm"                      // a timer going off outranks everything: it is waiting on you
        if (composeOpen && !approvalText) return "compose"
        if (expanded && !approvalText && !settingsOpen) return "expanded"
        if (approvalText) return "approval"
        if (settingsOpen) return "settings"
        if (card) return "card"
        if (dstate === "listening") return "listening"
        if (video) return "video"                      // stays while the assistant works: a caption line shows it
        if (playerOpen && musicOn) return "player"
        if (notification) return "notification"
        if (flashText) return "flash"
        if (answerOpen) return "answer"
        if (dstate === "transcribing") return "transcribing"
        if (dstate === "thinking" || dstate === "speaking") return "thinking"
        if (musicShown && workers === 0) return "music"
        if (peeking || workers > 0) return "peek"
        return "hidden"
    }
    onModeChanged: if (mode !== "thinking") detailOpen = false

    // ───────────── look ─────────────
    readonly property color ink: "#000000"
    readonly property color text1: "#f5f5f7"
    readonly property color text2: Qt.rgba(235 / 255, 235 / 255, 245 / 255, 0.62)
    // 0.48 keeps captions at ~4.8:1 on the island's black; 0.34 measured 2.8:1, below the 4.5:1 floor
    readonly property color text3: Qt.rgba(235 / 255, 235 / 255, 245 / 255, 0.48)
    readonly property color fill1: Qt.rgba(1, 1, 1, 0.08)
    readonly property color fill2: Qt.rgba(1, 1, 1, 0.14)
    readonly property color accentBlue: "#0a84ff"
    readonly property color accentCyan: "#64d2ff"
    readonly property color accentGreen: "#30d158"
    readonly property color accentOrange: "#ff9f0a"
    readonly property color accentRed: "#ff453a"
    readonly property color accentPurple: "#bf5af2"
    readonly property color accentPink: "#fc3c44"
    readonly property string fontFamily: "Inter"

    // ───────────── icons ─────────────
    // The island draws its own set (lucide, one white stroke) so the menu never mixes
    // styles with whatever icon theme the desktop happens to use. Names that are not
    // in the table (an app's own icon on a notification) still come from the theme.
    readonly property var glyphs: ({
        "window-close": "x", "dialog-close": "x", "configure": "settings",
        "go-up": "chevron-up", "go-down": "chevron-down", "go-top": "panel-top", "go-next": "chevron-right",
        "audio-input-microphone": "mic", "audio-speakers": "headphones", "audio-volume-high": "volume-2",
        "audio-volume-medium": "volume-2", "audio-volume-muted": "volume-x", "audio-x-generic": "music",
        "audio-lines": "audio-lines",
        "preferences-desktop-notification-bell": "bell", "preferences-system": "settings",
        "media-playback-start": "play", "media-playback-pause": "pause", "media-playback-stop": "square",
        "media-skip-forward": "skip-forward", "media-skip-backward": "skip-back",
        "media-playlist-shuffle": "shuffle", "media-playlist-repeat": "repeat", "media-repeat-single": "repeat-1",
        "view-media-playlist": "list-music", "view-fullscreen": "maximize-2", "view-preview": "monitor",
        "view-grid": "layout-grid", "view-refresh": "refresh-cw",
        "image-x-generic": "image", "video-x-generic": "video", "applications-graphics": "palette",
        "system-software-install": "package", "system-software-update": "download", "system-run": "sparkles",
        "document-new": "message-square-plus", "document-open-folder": "folder-open", "folder-open": "folder-open",
        "document-edit": "text-cursor", "edit-copy": "copy", "edit-select-text": "text-cursor",
        "format-text-bold": "text-cursor", "edit-find": "search", "search": "search",
        "utilities-terminal": "terminal", "help-contents": "book-open", "internet-web-browser": "globe",
        "window-new": "app-window", "input-keyboard": "keyboard",
        "dialog-warning": "circle-alert", "dialog-ok": "check", "dialog-information": "info",
        "appointment-soon": "calendar-clock", "user-identity": "user-round", "trash-empty": "trash",
        // what tool_icon() sends while the assistant works
        "input-mouse": "mouse-pointer-click", "system-search": "search", "document-open": "file-text",
        "applications-development": "code", "games-hint": "wand-sparkles", "youtube": "circle-play",
        "applications-games": "gamepad-2", "steam": "gamepad-2", "application-x-executable": "app-window",
        "preferences-system-windows": "app-window", "git": "git-branch", "help-about": "circle-help",
        "moon": "moon", "cloud": "cloud"
    })
    // every file in island/icons, so a view can also name a lucide icon directly
    readonly property var localIcons: [
        "activity", "app-window", "audio-lines", "bell", "bell-ring", "book-open", "bot", "brain", "calendar-clock",
        "check", "chevron-down", "circle-help", "timer", "code", "gamepad-2", "git-branch", "chevron-right", "chevron-up", "circle-alert", "circle-play", "cloud", "cloud-fog",
        "cloud-lightning", "cloud-rain", "cloud-snow", "cloud-sun", "copy", "cpu", "download", "external-link",
        "file-text", "folder-open", "globe", "headphones", "house", "image", "info", "keyboard", "key-round",
        "layout-grid", "list-music", "log-out", "mail", "maximize-2", "message-circle", "message-square-plus", "mic",
        "monitor", "moon", "mouse-pointer-click", "music", "package", "palette", "panel-top", "pause", "play", "plus", "power",
        "refresh-cw", "repeat", "repeat-1", "rotate-ccw", "search", "settings", "shield", "shuffle", "skip-back",
        "skip-forward", "sparkles", "square", "sun", "terminal", "text-cursor", "trash", "user-round", "users",
        "video", "volume-2", "volume-x", "wand-sparkles", "x", "zap"
    ]
    // "" when the island has no glyph of its own for this name
    function glyph(name) { return name ? (glyphs[name] || (localIcons.indexOf(name) >= 0 ? name : "")) : "" }

    // ───────────── language ─────────────
    // UI strings are written in Russian; tr() swaps them for island/i18n/<lang>.json when another language is chosen
    readonly property string lang: settings.language || "ru"
    FileView { id: dictFile; path: jd.lang === "ru" ? "" : Quickshell.shellDir + "/i18n/" + jd.lang + ".json"; blockLoading: true }
    readonly property var dict: { try { return lang === "ru" ? ({}) : JSON.parse(dictFile.text()) } catch (e) { return ({}) } }
    function tr(s) { return dict[s] || s }
    readonly property string assistantName: settings.assistant_name || "JustDay"

    function accentFor(s) {
        return ({ listening: accentCyan, transcribing: accentCyan, thinking: accentOrange, speaking: accentBlue,
                  approval: accentOrange, offline: accentRed })[s] || text3
    }

    // ───────────── daemon connection ─────────────
    readonly property bool connected: linked
    readonly property string socketPath: Quickshell.env("JUSTDAY_SOCKET") || (Quickshell.env("XDG_RUNTIME_DIR") + "/justday.sock")

    // The subscription socket is recreated on every reconnect: toggling `connected` on a failed Socket does not redial.
    // The daemon sends a heartbeat every 5 s; 12 s of silence or any socket error → new connection.
    property real lastMessage: Date.now()
    property bool linked: false
    Loader {
        id: busLoader
        sourceComponent: Socket {
            path: jd.socketPath
            Component.onCompleted: connected = true
            onConnectedChanged: {
                jd.linked = connected
                if (connected) {
                    jd.lastMessage = Date.now()
                    write('{"cmd": "subscribe"}\n')
                    flush()
                }
            }
            onError: jd.lastMessage = 0
            parser: SplitParser {
                onRead: line => {
                    jd.lastMessage = Date.now()
                    try { jd.handle(JSON.parse(line)) } catch (e) { console.warn("island:", e, line) }
                }
            }
        }
    }
    function reconnect() {
        linked = false
        dstate = "offline"
        busLoader.active = false
        Qt.callLater(() => busLoader.active = true)
    }
    Timer {
        interval: 2000
        repeat: true
        running: true
        onTriggered: if (!jd.linked || Date.now() - jd.lastMessage > 12000) { jd.lastMessage = Date.now(); jd.reconnect() }
    }

    // one-shot commands: a short-lived connection per request (the daemon answers one line and closes)
    Component {
        id: commandSocket
        Socket {
            property string payload
            path: jd.socketPath
            parser: SplitParser { onRead: _ => destroy() }
            onConnectedChanged: if (connected) { write(payload + "\n"); flush() }
            Component.onCompleted: connected = true
        }
    }
    function send(obj) { commandSocket.createObject(jd, { payload: JSON.stringify(obj) }) }
    function run(args) { Quickshell.execDetached(["justday"].concat(args)) }

    function handle(m) {
        if (m.settings !== undefined) settings = m.settings
        if (m.history !== undefined) history = m.history
        if (m.workers !== undefined) workers = m.workers
        if (m.weather !== undefined) weather = m.weather
        if (m.update !== undefined) update = m.update
        if (m.next_event !== undefined) nextEvent = m.next_event
        if (m.level !== undefined) level = Math.max(level * 0.6, m.level)
        if (m.player !== undefined) {
            const was = player
            if (m.player && m.player.paused && was && !was.paused) { pauseGrace = true; graceTimer.restart() }
            player = m.player
            playerAt = Date.now()
            if (!m.player) playerOpen = false
        }
        if (m.video !== undefined) { video = m.video; if (!m.video) videoBig = false }
        if (m.reminders !== undefined) reminders = m.reminders
        if (m.state !== undefined && m.state !== dstate) {
            const was = dstate
            dstate = m.state
            if (m.state === "listening") { activity = ""; activityIcon = ""; answerOpen = false }
            if ((m.state === "thinking" || m.state === "transcribing") && was !== "thinking" && was !== "speaking")
                busySince = Date.now()
            if (m.state === "idle" && answerOpen) answerTimer.restart()
        }
        switch (m.kind) {
        case "heard": activity = "«" + flat(m.detail) + "»"; activityIcon = "audio-input-microphone"; break
        case "tool": activity = flat(m.detail); activityIcon = m.icon || ""; break
        case "draft": activity = flat(m.detail); break
        case "say": answer = m.detail; answerOpen = true; answerTimer.stop(); break
        case "fast": flash(m.detail, m.icon, accentGreen); break
        case "approval": approvalText = m.detail; approvalReason = m.reason || ""; break
        case "approval_result": approvalText = ""; break
        case "cancel":
            approvalText = ""; answerOpen = false; card = null; alarm = null
            flash(tr("Отменено"), "dialog-cancel", accentRed)
            break
        case "error": flash(m.detail, "dialog-error", accentRed); break
        case "notification":
            if (island.show_notifications === false) break
            notification = m.notification
            notifExpanded = false
            notifications = [Object.assign({ ts: Qt.formatTime(new Date(), "HH:mm") }, m.notification)].concat(notifications).slice(0, 8)
            notifTimer.restart()
            break
        case "compose": openCompose(m.text, m.context); break
        case "video_cmd": videoCommand(m.action); break
        case "card_close": card = null; alarm = null; break
        case "card":
            if (!m.card) { card = null; break }
            if (m.card.type === "alarm") { alarm = m.card; break }   // its own view, and no timeout: it rings until dismissed
            card = m.card
            // cards waiting for an answer stay until the daemon closes them (it gives up after 120 s)
            cardTimer.interval = ["message_draft", "question"].includes(m.card.type) ? 130000
                               : m.card.type === "mail_draft" ? 90000 : (m.card.type === "mail_sent" ? 3500 : 25000)
            cardTimer.restart()
            break
        }
    }

    function flash(textValue, iconName, color) {
        flashText = textValue
        flashIcon = iconName || ""
        flashColor = color
        flashTimer.restart()
    }
    Timer { id: flashTimer; interval: 2200; onTriggered: jd.flashText = "" }
    Timer { id: notifTimer; interval: 6000; onTriggered: if (jd.islandHovered || jd.notifExpanded) restart(); else jd.notification = null }
    Timer {
        id: answerTimer
        // without a voice the text is all there is: give time to read it
        interval: jd.voiceOn && jd.micOn ? Math.min(15000, 4000 + jd.answer.length * 45) : Math.min(60000, 8000 + jd.answer.length * 70)
        onTriggered: if (jd.islandHovered) restart(); else jd.answerOpen = false
    }
    Timer { id: cardTimer; onTriggered: if (jd.islandHovered) restart(); else jd.card = null }
    Timer { id: leaveTimer; interval: 700; onTriggered: jd.peeking = false }
    onIslandHoveredChanged: if (islandHovered) leaveTimer.stop(); else leaveTimer.restart()
}
