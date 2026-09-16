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
    property var nextEvent: null      // calendar event starting within 2 hours
    property var update: null      // {behind, changes} when GitHub has a newer version
    function runUpdate() { Quickshell.execDetached(["kitty", "--hold", "justday", "update"]); closeAll() }

    property string activity: ""           // one line of what is happening (heard text, tool, draft)
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
    property bool settingsOpen: false
    property string settingsPage: "general"
    function openSettings(page) { settingsPage = page || "general"; settingsOpen = true; expanded = false }
    function closeAll() { settingsOpen = false; expanded = false }
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
        if (expanded && !approvalText && !settingsOpen) return "expanded"
        if (approvalText) return "approval"
        if (settingsOpen) return "settings"
        if (card) return "card"
        if (dstate === "listening") return "listening"
        if (notification) return "notification"
        if (flashText) return "flash"
        if (answerOpen) return "answer"
        if (dstate === "transcribing") return "transcribing"
        if (dstate === "thinking" || dstate === "speaking") return "thinking"
        if (peeking || workers > 0) return "peek"
        return "hidden"
    }
    onModeChanged: if (mode !== "thinking") detailOpen = false

    // ───────────── look ─────────────
    readonly property color ink: "#000000"
    readonly property color text1: "#f5f5f7"
    readonly property color text2: Qt.rgba(235 / 255, 235 / 255, 245 / 255, 0.62)
    readonly property color text3: Qt.rgba(235 / 255, 235 / 255, 245 / 255, 0.34)
    readonly property color fill1: Qt.rgba(1, 1, 1, 0.08)
    readonly property color fill2: Qt.rgba(1, 1, 1, 0.14)
    readonly property color accentBlue: "#0a84ff"
    readonly property color accentCyan: "#64d2ff"
    readonly property color accentGreen: "#30d158"
    readonly property color accentOrange: "#ff9f0a"
    readonly property color accentRed: "#ff453a"
    readonly property color accentPurple: "#bf5af2"
    readonly property string fontFamily: "Inter"

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
        if (m.state !== undefined && m.state !== dstate) {
            const was = dstate
            dstate = m.state
            if (m.state === "listening") { activity = ""; activityIcon = ""; answerOpen = false }
            if ((m.state === "thinking" || m.state === "transcribing") && was !== "thinking" && was !== "speaking")
                busySince = Date.now()
            if (m.state === "idle" && answerOpen) answerTimer.restart()
        }
        switch (m.kind) {
        case "heard": activity = "«" + m.detail + "»"; activityIcon = "audio-input-microphone"; break
        case "tool": activity = m.detail; activityIcon = m.icon || ""; break
        case "draft": activity = m.detail; break
        case "say": answer = m.detail; answerOpen = true; answerTimer.stop(); break
        case "fast": flash(m.detail, m.icon, accentGreen); break
        case "approval": approvalText = m.detail; approvalReason = m.reason || ""; break
        case "approval_result": approvalText = ""; break
        case "cancel":
            approvalText = ""; answerOpen = false; card = null
            flash(tr("Отменено"), "dialog-cancel", accentRed)
            break
        case "error": flash(m.detail, "dialog-error", accentRed); break
        case "notification":
            if (island.show_notifications === false) break
            notification = m.notification
            notifications = [Object.assign({ ts: Qt.formatTime(new Date(), "HH:mm") }, m.notification)].concat(notifications).slice(0, 8)
            notifTimer.restart()
            break
        case "card_close": card = null; break
        case "card":
            if (!m.card) { card = null; break }
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
    Timer { id: notifTimer; interval: 5000; onTriggered: if (jd.islandHovered) restart(); else jd.notification = null }
    Timer {
        id: answerTimer
        interval: Math.min(15000, 4000 + jd.answer.length * 45)
        onTriggered: if (jd.islandHovered) restart(); else jd.answerOpen = false
    }
    Timer { id: cardTimer; onTriggered: if (jd.islandHovered) restart(); else jd.card = null }
    Timer { id: leaveTimer; interval: 700; onTriggered: jd.peeking = false }
    onIslandHoveredChanged: if (islandHovered) leaveTimer.stop(); else leaveTimer.restart()
}
