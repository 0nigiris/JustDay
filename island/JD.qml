pragma Singleton
// Shared state of the Dynamic Island: daemon connection, live status, theme, UI mode.
import QtQuick
import Quickshell
import Quickshell.Services.Mpris
import Quickshell.Services.Pipewire
import Quickshell.Io
import Quickshell.Wayland

Singleton {
    id: jd

    // ───────────── live state from the daemon ─────────────
    property string dstate: "offline"      // idle listening transcribing thinking speaking approval offline
    property bool followup: false          // слушаем продолжение разговора, а не новый зов: ответ остаётся на виду
    property real level: 0
    property int workers: 0
    property var settings: ({})
    property var history: []
    property var weather: null
    property var notification: null   // desktop notification being shown
    property var notifications: []    // recent ones for the menu
    property bool notifExpanded: false  // the whole text, unfolded inside the island (the ⌄ button)
    // Tap a toast like Plasma: invoke the notification's default action (ActionInvoked) so the
    // app opens the matching dialog/chat. Focus/launch is only a fallback when no action exists
    // (eavesdrop-only copy with no live Notify object). No per-app hardcoding.
    property var _notifActionRefs: []   // keep action QObjects; Quickshell may clear live.actions
    function _cacheNotifActions(live) {
        _notifActionRefs = []
        if (!live) return
        const acts = live.actions || []
        for (let i = 0; i < acts.length; i++)
            _notifActionRefs.push(acts[i])
    }
    function openNotification(n) {
        if (!n) return
        let acted = false
        const pool = []
        const liveActs = (liveNotification && liveNotification.actions) ? liveNotification.actions : []
        for (let i = 0; i < liveActs.length; i++) pool.push(liveActs[i])
        for (let i = 0; i < _notifActionRefs.length; i++) pool.push(_notifActionRefs[i])

        function tryInvoke(a) {
            // QML action objects expose invoke() as a method; typeof is unreliable here.
            if (!a) return false
            try { a.invoke(); return true } catch (e) { return false }
        }
        // Same order plasmashell uses: "default", then empty id, then a lone action.
        for (const a of pool) {
            const id = String(a.identifier || "").toLowerCase()
            if (id === "default" || id === "open" || id === "activate" || id === "") {
                if (tryInvoke(a)) { acted = true; break }
            }
        }
        if (!acted && pool.length === 1)
            acted = tryInvoke(pool[0])

        // Fallback only when there is nothing to Activate — e.g. daemon eavesdrop without live.
        if (!acted) {
            const desk = n.desktop || ""
            const icon = n.icon || ""
            const deskOrIcon = desk || ((icon && !icon.startsWith("/") && !icon.startsWith("file:") && !icon.includes("/")) ? icon : "")
            send({ cmd: "notification_open", app: n.app || "", desktop: deskOrIcon })
        }

        if (n === notification) { notification = null; notifExpanded = false }
        if (liveNotification) { try { liveNotification.dismiss() } catch (e) {}; liveNotification = null }
        _notifActionRefs = []
        expanded = false
    }
    function dismissNotification() {
        if (liveNotification) { liveNotification.dismiss(); liveNotification = null }
        _notifActionRefs = []
        notification = null
        notifExpanded = false
    }
    // Уведомление, пришедшее к нам напрямую, а не подслушиванием: у него есть кнопки и его можно
    // честно закрыть — программа узнает, что его увидели, и не станет показывать второй раз.
    property var liveNotification: null
    property string _notifDedupeKey: ""
    property double _notifDedupeAt: 0
    function takeNotification(n, live) {
        if (island.show_notifications === false) { if (live) live.dismiss(); return }
        const key = (n.app || "") + "\0" + (n.summary || "") + "\0" + (n.body || "").slice(0, 120)
        const now = Date.now()
        if (key && key === _notifDedupeKey && now - _notifDedupeAt < 2000) {
            // Eavesdrop may arrive first; attach the live Notify object when it shows up.
            if (live) {
                liveNotification = live
                _cacheNotifActions(live)
            }
            return
        }
        _notifDedupeKey = key
        _notifDedupeAt = now
        liveNotification = live || null
        _cacheNotifActions(live)
        // Р2-38: в полноэкранной игре уведомление не выскакивает — оно ждёт в истории.
        if (gameMode) return
        notification = n
        notifExpanded = false
        notifTimer.restart()
    }
    function runNotificationAction(which) {
        const pool = []
        const liveActs = (liveNotification && liveNotification.actions) ? liveNotification.actions : []
        for (let i = 0; i < liveActs.length; i++) pool.push(liveActs[i])
        for (let i = 0; i < _notifActionRefs.length; i++) pool.push(_notifActionRefs[i])
        for (const a of pool)
            if (a.identifier === which) { try { a.invoke() } catch (e) {}; break }
        dismissNotification()
    }
    property var alarm: null          // the timer or alarm ringing right now
    property var reminders: []        // timers, alarms and reminders still waiting, soonest first
    property var jobs: []             // background jobs: {id, title, state, started, ended, code}
    readonly property var runningJob: jobs.find(j => j.state === "running") || null
    function jobTime(j) { return j ? fmtTime(((j.ended || tick) - j.started)) : "" }
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
    // ───────────── существо ─────────────
    //
    // Настроение считается здесь, а не в самом существе: про ассистента островок знает больше, чем
    // нарисованное лицо, и знание это нужно ещё в двух местах. Само существо только показывает.
    readonly property bool buddyOn: island.buddy !== false
    // Скины маскота: список от демона и выбранный. Пусто — рисуем своего, кодом.
    property var mascots: ({})
    readonly property var mascotSkin: mascots.picked || null
    function mascotRefresh() { send({ cmd: "mascots" }) }
    // Сменили скин в настройках — список надо перечитать: выбранного в нём ещё нет, и островок
    // продолжал бы рисовать прежнего. Сравниваем с тем, что демон сам считает выбранным.
    onSettingsChanged: {
        const want = String((island && island.mascot) || "")
        if (mascots.want !== undefined && mascots.want !== want) mascotRefresh()
    }
    // Насколько крупно показывать зверя. У нарисованного тела своя плотность: кот с большой головой
    // при том же размере читается мельче, чем голый шарик, поэтому размер отдельной настройкой.
    readonly property real mascotZoom: Math.max(0.5, Math.min(3, (island.mascot_size || 100) / 100))
    property real pointerX: -99999                 // курсор, пока он над полосой островка
    property real pointerY: -99999
    property bool buddyHappy: false                // короткая радость после законченного дела
    // Состояния те же, что в перенесённой таблице. Порядок проверок — это порядок важности: то, что
    // ждёт человека, перебивает то, что идёт само, а идущее перебивает покой.
    readonly property string buddyMood: {
        if (dstate === "offline") return "sleeping"
        if (approvalText !== "") return "approval"
        if (buddyHappy) return "finished"
        if (dstate === "listening") return "listening"
        if (dstate === "transcribing") return "thinking"
        if (dstate === "thinking") return searchingNow ? "searching" : "thinking"
        if (dstate === "speaking") return "talking"
        if (workers > 0) return "working"
        return "idle"
    }
    // Ищет или думает — видно по тому, чем занят инструмент: поиск по файлам и в сети выглядит
    // иначе, чем размышление, и показывать их одинаково значит потерять половину смысла.
    readonly property bool searchingNow: {
        const i = String(activityIcon || "").toLowerCase()
        return i === "search" || i === "globe" || i === "folder-open"
    }
    // Радуется делу, которое кончилось, а не любому переходу в покой: молчание после «не расслышал»
    // — не повод прыгать.
    property string buddyWas: "idle"
    onDstateChanged: {
        const was = buddyWas
        buddyWas = dstate
        if (dstate === "idle" && (was === "speaking" || was === "thinking")) { buddyHappy = true; happyOff.restart() }
    }
    property Timer happyOff: Timer { interval: 1800; onTriggered: jd.buddyHappy = false }

    property real tick: Date.now() / 1000          // one clock for every countdown on screen
    Timer { running: jd.reminders.length > 0 || !!jd.runningJob; interval: 500; repeat: true; onTriggered: jd.tick = Date.now() / 1000 }
    function dismissAlarm(id) { send({ cmd: "alarm_dismiss", id: id || "" }) }

    property var nextEvent: null      // calendar event starting within 2 hours
    property var update: null      // {behind, changes} when GitHub has a newer version
    function runUpdate() { send({ cmd: "terminal_run", what: "update" }); closeAll() }

    // ── Режим сервера из меню пуска ──
    // Он просил включать его оттуда: «дал задачу и лёг спать» не должно начинаться с терминала.
    // Состояние спрашиваем при открытии меню — один дешёвый запрос, зато кнопка не врёт.
    property bool serverMode: false
    function askServerMode() { serverProbe.running = true }
    Process {
        id: serverProbe
        command: ["justday", "server", "status"]
        stdout: StdioCollector {
            onStreamFinished: {
                try { jd.serverMode = !!JSON.parse(text).on } catch (e) { jd.serverMode = false }
            }
        }
    }
    function toggleServerMode() {
        const wasOn = jd.serverMode
        serverSwitch.command = ["justday", "server", wasOn ? "off" : "on"]
        serverSwitch.running = true
        flash(wasOn ? tr("Возвращаю машину: экраны и звук") : tr("Режим сервера: гашу экраны"),
              wasOn ? "sun" : "moon")
    }
    Process {
        id: serverSwitch
        onExited: jd.askServerMode()
    }

    // Быстрая проверка обновления из меню: кнопка в настройках была, но на самом дне страницы
    // «О программе» — человек её не находил. Здесь ответ приходит сразу всплывашкой на островке.
    function checkUpdate() {
        flash(tr("Проверяю обновления…"), "refresh-cw")
        updProbe.running = true
    }
    Process {
        id: updProbe
        command: ["justday", "update", "--check"]
        stdout: StdioCollector {
            onStreamFinished: {
                let got = null
                try { got = JSON.parse(text) } catch (e) {}
                if (!got || !got.ok)
                    jd.flash(jd.tr("Не удалось проверить обновления"), "alert-triangle", jd.accentRed)
                else if (got.behind)
                    jd.flash(jd.tr("Есть обновление — открываю"), "download")
                else
                    jd.flash(jd.tr("Установлена последняя версия"), "check")
                if (got && got.ok && got.behind)
                    jd.openSettings("about")
            }
        }
    }

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
    property var flashAct: null         // [подпись, команда]: кнопка в тосте (Р2-45 «Показать»)
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
    // «Молчит по просьбе» — не то же, что «голоса нет вовсе»: первое снимается одной кнопкой.
    readonly property bool muted: settings.muted === true
    function setMuted(on) {
        settings = Object.assign({}, settings, { muted: on, voice: !on })   // кнопка отзывается сразу
        send({ cmd: "voice_mute", on: !on })
    }
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
    property string playerPage: "now"   // страница плеера: "now" | "library" (Р2-32)
    property var libTracks: []          // медиатека: приходит от демона по music_library
    property string libSort: "recent"
    // Чат (Р2-42): окно ChatWindow.qml; ответы приходят строками подписки kind:"chat", в динамик не идут
    property int crashCount: 0          // сохранённых отчётов о сбоях (Р2-45)
    property bool chatOpen: false
    property var chatList: []
    property string chatCurrent: ""
    property var chatMessages: []
    property bool chatBusy: false
    property bool _chatWantNew: false
    function chatRefresh() { send({ cmd: "chat_list" }) }
    function chatOpenOne(id) { chatCurrent = id; chatMessages = []; send({ cmd: "chat_get", id: id }) }
    function chatNew() { _chatWantNew = true; send({ cmd: "chat_new" }) }
    function chatSend(text) { if (chatCurrent && text.trim()) send({ cmd: "chat_send", id: chatCurrent, text: text }) }
    function chatDelete(id) { send({ cmd: "chat_delete", id: id }); if (id === chatCurrent) { chatCurrent = ""; chatMessages = [] }; chatRefresh() }
    // «Показать в папке» через D-Bus: сработает с любым файловым менеджером, а не только с Dolphin (Р2-15).
    // Нет службы — просто открываем папку.
    function showInFolder(path) {
        Quickshell.execDetached(["sh", "-c",
            "gdbus call --session --dest org.freedesktop.FileManager1 --object-path /org/freedesktop/FileManager1 " +
            "--method org.freedesktop.FileManager1.ShowItems \"['file://$2']\" '' >/dev/null 2>&1 || xdg-open \"$(dirname \"$1\")\"",
            "sh", path, encodeURI(path)])
    }
    // Системные настройки есть не у всех (не KDE): без программы честно говорим об этом, а не молчим (Р2-15).
    function systemSettings(page) {
        Quickshell.execDetached(["sh", "-c",
            "command -v systemsettings >/dev/null && exec systemsettings \"$@\" || notify-send 'JustDay' 'Системные настройки не найдены на этом компьютере'",
            "sh"].concat(page ? [page] : []))
    }
    function libRefresh() { send({ cmd: "music_library", sort: libSort }) }
    property bool artOpen: false        // the cover, large, inside the player (a click on the cover)
    onPlayerOpenChanged: if (!playerOpen) { artOpen = false; playerPage = "now" }
    property var video: null            // {title, channel, thumb, file, progress} — a video playing inside the island
    // ширина кадра в точках: её тянут за уголок, а запомненная лежит в island.video_width
    property real videoWidth: videoFit(island.video_width || 640)
    property bool videoResizing: false   // пока тянут за уголок, остров не пружинит, а следует за курсором
    property real screenWidth: 1920      // shell.qml подставляет настоящие размеры монитора
    property real screenHeight: 1080
    readonly property bool videoBig: videoWidth >= videoRoom - 1   // уже во всю ширину, некуда расти
    // кадр 16:9 целиком на экране: и в ширину, и в высоту, с местом под панель сверху
    readonly property real videoRoom: Math.max(360, Math.min(screenWidth - 40, Math.round((screenHeight - topMargin - 70) * 16 / 9)))
    function videoFit(w) { return Math.max(360, Math.min(videoRoom, Math.round(w))) }
    function setVideoWidth(w) { videoWidth = videoFit(w) }
    // громкость кадра запоминается, как и его размер; приглушение на время разговора идёт сверху
    property real videoVolume: island.video_volume === undefined ? 1 : Math.max(0, Math.min(1, island.video_volume))
    function setVideoVolume(v) { videoVolume = Math.max(0, Math.min(1, v)); volumeSave.restart() }
    function saveVideoVolume() { setConfig("island.video_volume", videoVolume.toFixed(2)) }
    // ползунок двигают пикселями, а в файл пишем один раз, когда его отпустили
    Timer { id: volumeSave; interval: 900; onTriggered: jd.saveVideoVolume() }
    property real videoRate: 1.0         // скорость: 0.5 … 2
    property bool videoLoop: false       // повтор одного ролика
    property bool videoMini: false       // кадр свёрнут в пилюлю, звук идёт дальше
    property bool videoPlaying: false    // что делает кадр прямо сейчас — для пилюли
    property real videoPos: 0
    property real videoDur: 0
    property var videoLast: null         // закрытый ролик: {title, pos, in_window} — его можно продолжить
    function videoResume() { send({ cmd: "video_resume" }) }     // продолжить с того же места
    function videoPopin() { send({ cmd: "video_popin" }) }       // забрать ролик из отдельного окна
    function videoDrop(target) { send({ cmd: "video_drop", target: target }) }   // бросили файл или ссылку на остров
    // размер запоминается, когда уголок отпустили: не на каждый пиксель перетаскивания
    function saveVideoWidth() { setConfig("island.video_width", Math.round(videoWidth)) }
    signal videoCommand(string action)  // pause / resume / toggle / restart from the daemon ("пауза" by voice)
    readonly property var mediaCfg: settings.media || ({})
    readonly property bool musicOn: !!player && (!!player.file || !!player.loading)
    // the pill stays while music plays and for a little while after a pause
    property bool pauseGrace: false
    // На чём он сейчас думает. Лёгкая модель работает молча, а про переход на сильную сказать
    // стоит: человек видит, что задача признана крупной, и может возразить одним словом.
    property string brainModel: ""
    property string brainWhy: ""
    readonly property bool brainStrong: brainWhy !== "" && brainModel !== ""

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
    // Only lightness is corrected (so the colour reads on black); a pale cover stays pale, a grey one stays
    // grey. Measured by chroma, not HSL saturation: near black the latter is noise, and #030000 used to
    // come out as pure red.
    function artTint(c) {
        if (!c) return accentPink
        const q = Qt.color(c)
        const chroma = Math.max(q.r, q.g, q.b) - Math.min(q.r, q.g, q.b)
        if (chroma < 0.08) return Qt.hsla(0, 0, 0.74, 1)                        // colourless: a soft white
        if (chroma < 0.3)                                                       // muted: keep it muted
            return Qt.hsla(q.hslHue, Math.min(0.42, Math.max(0.2, q.hslSaturation)), Math.min(0.74, Math.max(0.62, q.hslLightness)), 1)
        return Qt.hsla(q.hslHue, Math.max(0.55, q.hslSaturation), Math.min(0.68, Math.max(0.52, q.hslLightness)), 1)
    }

    // ───────────── панель инструментов: эмодзи, буфер обмена, нагрузка ─────────────
    //
    // Островок — не только лицо ассистента. То, за чем в оболочках для Hyprland держат по отдельной
    // программе (выбиралка эмодзи, история буфера, монитор нагрузки), здесь лежит в нём же: одно
    // окно, одни клавиши, одни цвета. Искать умеет демон — он же отвечает и ассистенту, поэтому
    // «вставь эмодзи с котиком» и сетка на экране находят одно и то же.
    property string toolsPage: ""          // "" — закрыта; emoji | clip | mixer | plans | claude | load
    property int toolsPick: 0             // выбранная строка в списке: стрелками и Enter
    property string toolsQuery: ""
    property var toolsItems: []           // что нашлось: эмодзи или записи буфера
    property var emojiGroups: []
    property string emojiGroup: ""
    property var load: null               // последний взгляд на машину
    property var loadHistory: ({ cpu: [], mem: [], gpu: [] })   // для графиков: последние 60 секунд
    property var focusNow: null           // идёт окно тишины по расписанию: {name, until} или null
    property var qrRows: []               // страница «QR»: матрица из «0» и «1»; стирается при закрытии панели
    function qrAsk(what) { if (what.text || what.wifi) send(Object.assign({ cmd: "qr" }, what)); else qrRows = [] }
    property bool clipPaused: false
    property int clipSkipped: 0           // сколько не запомнили как похожее на пароль
    property int toolsSerial: 0           // растёт на каждое открытие: поле ввода снова берёт фокус

    function openTools(page) {
        toolsPage = page || "emoji"
        toolsQuery = ""
        toolsPick = 0
        emojiGroup = ""
        settingsOpen = false
        expanded = false
        composeOpen = false
        playerOpen = false
        toolsSerial++
        refreshTools()
        send({ cmd: "load_watch", on: toolsPage === "load" })
    }
    function closeTools() {
        if (toolsPage === "load") send({ cmd: "load_watch", on: false })
        toolsPage = ""
        toolsItems = []
        qrRows = []
    }
    function setToolsPage(page) {
        if (page === toolsPage) return
        const wasLoad = toolsPage === "load"
        toolsPage = page
        toolsQuery = ""
        toolsPick = 0
        toolsItems = []
        qrRows = []
        if (wasLoad !== (page === "load")) send({ cmd: "load_watch", on: page === "load" })
        refreshTools()
    }
    // Ищет демон, а не островок: набор эмодзи лежит там, история буфера тоже, и второй такой же
    // поиск на QML разошёлся бы с первым в тот же день.
    // ───────────── планы ─────────────
    //
    // Они лежат в Obsidian и правятся руками — островок их только показывает и отмечает сделанным.
    // Заводить им вторую жизнь здесь нельзя: два списка одного и того же расходятся в первый день.
    property var plans: []
    function plansRefresh() { send({ cmd: "plan_list", open: false }) }

    // ───────────── живые сессии Claude Code ─────────────
    //
    // «Клод работает ×3» — это не сведения, а обещание, что что-то происходит. Здесь видно, что
    // именно: какая сессия что читает, правит и запускает.
    property var sessions: []
    // История разговоров: что сказал человек и что ответили (страница «История» в панели).
    property var talk: []
    function sessionsRefresh() { send({ cmd: "sessions" }) }
    // Список присылает демон, пока страница открыта и когда что-то изменилось; страница раз в полминуты
    // подтверждает, что смотрит (демон ждёт сорок пять секунд), и один раз сообщает, что закрылась.
    function sessionsWatch(on) { send({ cmd: "sessions_watch", on: on }) }
    function planDone(which) { send({ cmd: "plan_done", which: String(which) }); plansLater.restart() }
    function planAdd(text) {
        const s = String(text || "").trim()
        if (!s) return
        send({ cmd: "plan_add", text: s })
        plansLater.restart()
    }
    // Список перечитывается не сразу: демон успевает записать файл, а мы успеваем не увидеть
    // собственную правку и решить, что ничего не вышло.
    property Timer plansLater: Timer { interval: 350; onTriggered: jd.plansRefresh() }

    function refreshTools() {
        if (toolsPage === "emoji") send({ cmd: "emoji", query: toolsQuery, group: emojiGroup, limit: 400 })
        else if (toolsPage === "clip") send({ cmd: "clip_list", query: toolsQuery, limit: 80 })
        else if (toolsPage === "history") send({ cmd: "history", query: toolsQuery, limit: 80 })
        else if (toolsPage === "load") send({ cmd: "load" })
    }
    // Сначала закрыть панель, потом просить вставить. Пока панель на экране, клавиатура принадлежит
    // ей: напечатанное уходит в никуда, и человек видит «скопировано» вместо вставленного символа.
    function useEmoji(ch) { closeTools(); send({ cmd: "emoji_use", char: ch }) }
    function useClip(which) { closeTools(); send({ cmd: "clip_use", which: String(which) }) }
    function forgetClip(which) { send({ cmd: "clip_forget", which: String(which) }); refreshTools() }
    function pauseClip(on) { send({ cmd: "clip_pause", on: on }) }
    function pinClip(which, on) { send({ cmd: "clip_pin", which: String(which), on: on === undefined ? null : on }) }
    function editClip(which, text) {
        send({ cmd: "clip_edit", which: String(which), text: String(text || "") })
    }
    property string clipEditing: ""       // id записи, которую правят в панели буфера
    property string clipEditDraft: ""

    // ───────────── меню приложений ─────────────
    //
    // Замена кикоффу KDE. Отдельное окно, а не страница острова: меню открывается от своего угла
    // экрана и живёт по своим размерам, а остров в это время может показывать таймер или плеер.
    // Общего у них — цвета, значки, клавиши и демон; этого и хотелось.
    property bool menuOpen: false
    property var menuCatalog: ({})        // разделы, программы, закреплённое, кто за машиной
    property string menuCatalogRaw: ""   // его же текстом: чтобы не пересобирать сетку тем же самым
    property string menuGroup: "fav"
    property string menuQuery: ""
    property var menuFound: []            // что нашёл поиск: программы, игры, открытые окна
    property int menuPick: 0
    property int menuSerial: 0            // растёт на каждое открытие: поле снова берёт фокус
    property string menuConfirm: ""       // выключение ждёт второго щелчка
    property bool menuSearchMode: false   // Alt+Space Spotlight: узкий поиск, не полное меню
    // «Launchpad»: то же меню, но карточка во весь экран, значки крупнее и справа плитки управления.
    // Выбирается `island.menu_style`; Spotlight от него не зависит.
    readonly property bool menuLaunchpad: !menuSearchMode && (island.menu_style || "card") === "launchpad"

    readonly property var menuUser: menuCatalog.user || ({})
    readonly property var menuGroups: menuCatalog.groups || []
    readonly property var sessionActions: menuCatalog.session || []
    readonly property bool menuSearching: menuQuery.trim() !== ""
    // Закреплённые — по ключам, чтобы порядок был тот, в каком их закрепляли, а не алфавитный.
    readonly property var menuPinned: {
        const all = menuCatalog.apps || [], want = menuCatalog.pinned || []
        const by = ({})
        for (const a of all) by[a.kind + ":" + a.id] = a
        return want.map(k => by[k]).filter(a => a !== undefined)
    }
    // Что показать сеткой: закреплённые, всё подряд или один раздел.
    readonly property var menuShown: {
        // Spotlight / набор в поиске — один список от лаунчера (пустой запрос = недавние).
        if (menuSearchMode || menuSearching) return menuFound
        if (menuGroup === "fav") return menuPinned
        const all = menuCatalog.apps || []
        return menuGroup === "all" ? all : all.filter(a => a.cat === menuGroup)
    }
    function isPinned(item) {
        return item && (menuCatalog.favourites || []).indexOf(item.kind + ":" + item.id) >= 0
    }

    function openMenu() {
        menuSearchMode = false
        menuQuery = ""
        menuFound = []
        menuPick = 0
        menuConfirm = ""
        menuOpen = true
        askServerMode()          // кнопка режима сервера не должна врать о том, что сейчас включено
        menuSerial++
        closeAll()
        send({ cmd: "apps_catalog" })
        if (dockOn) dockRefresh()      // заодно: программы могли поставить или удалить
    }
    // Spotlight (Alt+Space / justday tools apps): тот же поиск, без разделов и полки питания.
    function openSearch() {
        menuSearchMode = true
        menuQuery = ""
        menuPick = 0
        menuConfirm = ""
        menuFound = []
        menuOpen = true
        menuSerial++
        closeAll()
        searchMenu()                   // пустой запрос → недавние (launcher.items)
    }
    // Закрытие гасит только menuOpen. Режим, запрос и найденное сбрасывают openMenu и openSearch.
    // Раньше всё обнулялось здесь же — и пока Spotlight таял, он уже был «полным меню»: карточка
    // уезжала вниз к доку, а вместо строк поиска на миг вспыхивала сетка программ.
    function closeMenu() {
        menuOpen = false
        menuConfirm = ""
    }
    function toggleMenu() { menuOpen && !menuSearchMode ? closeMenu() : openMenu() }
    function toggleSearch() { menuOpen && menuSearchMode ? closeMenu() : openSearch() }
    // Ищет тот же демон, что отвечает и ассистенту: «открой дискорд» голосом и строка в меню
    // находят одно и то же. Поиск шире сетки — в нём есть ещё и открытые окна.
    function searchMenu() { send({ cmd: "apps", query: menuQuery, limit: 60 }) }
    // Открыть из меню. Если окно программы уже есть — перейти к нему, а не запускать заново.
    //
    // Из-за этого «Telegram не запускается из пуска»: он уже работал, свёрнутый в лоток. Нажатие
    // честно звало gtk-launch, телеграм честно отвечал «я уже тут» и ничего не делал, и со стороны
    // это выглядело как сломанная кнопка. Док эту развилку знал с самого начала, меню — нет.
    function runFromMenu(item) {
        if (!item) return
        const open = windowsOf(item)
        if (open.length) {
            const up = open.find(w => !w.minimized) || open[0]
            windowDo("focus", up.id)
            closeMenu()
            return
        }
        send({ cmd: "apps_run", kind: item.kind, id: item.id })
        closeMenu()
    }
    // Окна этой программы: сопоставление то же самое, которым живёт док, — другого у нас нет, и
    // заводить второе значило бы развести их в первый же день.
    function windowsOf(item) {
        if (!item || item.kind === "game" || !item.id) return []
        const key = "app:" + item.id
        return windows.filter(w => {
            const hit = dockLookup(String(w.app || "").toLowerCase())
            return hit && hit.key === key
        })
    }
    // Ничего не нашлось — не тупик: строка уходит ассистенту. Ради этого меню и своё.
    function askFromMenu(text) { closeMenu(); send({ cmd: "type", text: text }) }
    function pinFromMenu(item) {
        if (!item || item.kind === "file" || item.kind === "window") return
        send({ cmd: "apps_pin", kind: item.kind, id: item.id })
        pinRefresh.restart()
    }
    // Опасное — со вторым щелчком. Не «Вы уверены?» окном, а той же кнопкой, которая на секунду
    // становится красной: подтверждение на месте, без окна поверх окна.
    function sessionDo(what, danger) {
        if (danger && menuConfirm !== what) { menuConfirm = what; confirmTimeout.restart(); return }
        menuConfirm = ""
        send({ cmd: "session_do", what: what, confirm: true })
        closeMenu()
    }
    Timer { id: confirmTimeout; interval: 4000; onTriggered: jd.menuConfirm = "" }
    Timer { id: pinRefresh; interval: 60; onTriggered: jd.send({ cmd: "apps_catalog" }) }

    // ───────────── док и трей ─────────────
    //
    // Док — не второе меню. Меню отвечает на «найти что-нибудь», док — на «то, чем пользуюсь
    // всегда», и его смысл в том, что до него не надо ничего нажимать. Поэтому в нём нет ни поиска,
    // ни разделов: закреплённое, открытое и один значок, из которого достаётся меню.
    //
    // Окна док берёт у вейланда напрямую (ToplevelManager), а имена и значки — у демона: у
    // открытого окна есть только appId вроде «org.kde.dolphin», и превратить его в «Finder» с
    // правильным значком может лишь тот, кто читал .desktop-файлы.
    readonly property var dockCfg: settings.dock || ({})
    readonly property var trayCfg: settings.tray || ({})
    readonly property bool dockOn: dockCfg.enabled !== false
    // Полоса лотка: 0 — как в настройках, 1 — показана кнопкой, −1 — спрятана кнопкой.
    // Кнопка в доке должна делать ровно то, что кнопка: показывать спрятанное и прятать показанное.
    property int trayPeek: 0
    function trayToggle() { trayPeek = trayOn ? -1 : 1 }
    readonly property bool trayOn: trayPeek === 1 || (trayPeek !== -1 && trayCfg.enabled !== false)
    // Выкл. — лоток не занимает край рабочего стола. Значки сети, Bluetooth и языка остаются на полосе.
    readonly property bool trayDesktop: trayCfg.on_desktop !== false
    property bool netOn: false
    property string netKind: ""
    property string netName: ""
    property string vpnName: ""
    readonly property bool vpnOn: vpnName !== ""
    property bool btOn: false
    readonly property bool barNet: (settings.island || ({})).bar_net !== false
    readonly property bool barBt: (settings.island || ({})).bar_bt !== false
    readonly property bool barLang: (settings.island || ({})).bar_lang !== false
    function askLinks() { if (!linkProbe.running) linkProbe.running = true }
    // Спрашиваем, только когда есть кому показывать. Это три внешние программы на каждый опрос,
    // и каждые пять секунд круглые сутки — это пятьдесят тысяч запусков в день ради значка,
    // который меняется раз в час. При островке и вырезе правого края полосы вовсе нет.
    readonly property bool linksWanted: islandStyle === "bar" && (barNet || barBt)
    Timer {
        interval: 15000
        running: jd.linksWanted
        repeat: true
        triggeredOnStart: true
        onTriggered: jd.askLinks()
    }
    Process {
        id: linkProbe
        command: ["python3", Quickshell.shellDir + "/links.py"]
        stdout: StdioCollector {
            onStreamFinished: {
                try {
                    const o = JSON.parse(text)
                    jd.netOn = !!o.net
                    jd.netKind = o.kind || ""
                    jd.netName = o.name || ""
                    jd.vpnName = o.vpn || ""
                    jd.btOn = !!o.bt
                } catch (e) {}
            }
        }
    }
    // ───────────── что играет ─────────────
    // Один выбор источника на весь островок. Раньше полоска знала только Spotify — имя или
    // desktop entry должны были содержать «spotify», — и у всех, кто слушает не его (YouTube в
    // браузере, VLC, местный плеер), она просто пустовала. Карточка при этом брала первого
    // попавшегося, так что полоска и карточка могли показывать разное.
    //
    // Порядок выбора: сначала выбрасываем нежеланных (island.player_ignore), потом среди
    // играющих берём первого по списку предпочтений (island.player_prefer), потом любого
    // играющего, и только если не играет никто — первого на паузе.
    readonly property var playerPrefer: (settings.island || ({})).player_prefer || ["spotify"]
    readonly property var playerIgnore: (settings.island || ({})).player_ignore || []
    readonly property bool playerInPeek: (settings.island || ({})).player_peek !== false
    readonly property bool playerInExpanded: (settings.island || ({})).player_expanded !== false
    function playerName(p) {
        return (String(p.identity || "") + " " + String(p.desktopEntry || "")).toLowerCase()
    }
    function playerWanted(p) {
        if (!p) return false
        const name = jd.playerName(p)
        for (const bad of jd.playerIgnore) if (bad && name.indexOf(String(bad).toLowerCase()) >= 0) return false
        return true
    }
    readonly property var musicPlayer: {
        const all = Mpris.players.values.filter(p => jd.playerWanted(p))
        if (!all.length) return null
        const playing = all.filter(p => p.isPlaying)
        for (const want of jd.playerPrefer) {
            const w = String(want || "").toLowerCase()
            if (!w) continue
            const hit = playing.find(p => jd.playerName(p).indexOf(w) >= 0)
            if (hit) return hit
        }
        return playing.length ? playing[0] : all[0]
    }
    readonly property bool musicPlaying: !!musicPlayer && musicPlayer.isPlaying
    // Название, как его отдаёт браузер: «(2) natori - Absolute Zero - YouTube». Счётчик вкладки
    // и хвост сервиса — мусор, а дефис между исполнителем и песней — тире.
    function cleanTitle(s) {
        let t = String(s || "").replace(/^\(\d+\)\s+/, "")
        t = t.replace(/\s+[-–—|·]\s+(YouTube Music|YouTube|SoundCloud|Spotify|Twitch|Bandcamp|Deezer|Apple Music|VK Музыка|ВКонтакте|Яндекс[ .]Музыка)\s*$/i, "")
        return t.replace(/\s+-\s+/, " — ").trim()
    }
    // Громкость именно этого плеера. MPRIS умеет её не у всех: браузеры свою не отдают, и тогда
    // берём его поток в PipeWire — тот же, что крутит микшер (MixerView), по имени программы.
    function playerStream(p) {
        if (!p) return null
        const name = playerName(p) + " " + String(p.dbusName || "").toLowerCase()
        return Pipewire.nodes.values.find(n => {
            if (!n || !n.isStream || !n.audio) return false
            const pr = n.properties || {}
            if (pr["media.class"] !== "Stream/Output/Audio") return false
            const who = String(pr["application.process.binary"] || pr["application.name"] || "").toLowerCase()
            return who.length > 2 && name.indexOf(who) >= 0
        }) || null
    }

    readonly property string dockPlace: dockCfg.position || "bottom"
    readonly property string trayPlace: trayCfg.position || "left"
    readonly property real dockIconSize: Math.max(24, Math.min(96, dockCfg.icon_size || 44))
    readonly property real trayIconSize: Math.max(14, Math.min(48, trayCfg.icon_size || 22))
    readonly property bool trayAutohide: trayCfg.autohide === true
    // Что в лотке не показывать. Сравнение без учёта регистра: значки называют себя как попало.
    // Prefixed aliases count too: hidden "discord" also covers "discord-tray", and vice versa.
    readonly property var trayHidden: (trayCfg.hidden || []).map(k => String(k).toLowerCase())
    function trayNames(item) {
        if (!item) return []
        const out = []
        for (const raw of [item.id, item.title, item.tooltipTitle]) {
            if (!raw) continue
            const n = String(raw).toLowerCase().trim()
            if (n && out.indexOf(n) < 0) out.push(n)
        }
        return out
    }
    function trayKeyHits(hiddenKey, name) {
        if (!hiddenKey || !name) return false
        if (hiddenKey === name) return true
        // Alias family: "discord" ↔ "discord-tray". Require a real stem (4+ chars) so
        // a one-letter hide key cannot wipe the whole strip.
        if (hiddenKey.length < 4 || name.length < 4) return false
        return name.indexOf(hiddenKey) === 0 || hiddenKey.indexOf(name) === 0
    }
    // Фирменные цветные значки (мессенджеры, браузеры) под палитру не красим: пропадает узнаваемость.
    function trayKeepColor(item) {
        const s = [item.id, item.title, item.tooltipTitle, item.tooltipDescription, item.icon].map(x => String(x || "")).join(" ").toLowerCase()
        return /discord|waywallen|steam|telegram|chrome|firefox|chromium|slack|signal|element|vesktop/.test(s)
    }
    // Какую вуаль из `tray.icon_style` надеть на значок трея на полосе. Лоток (TrayView) читает тот же
    // ключ, а полоса раньше его не знала и рисовала чужие цвета как есть — на светлой палитре часть
    // значков сливалась. `auto` — только лоток (он умеет смотреть пиксели), на полосе это «как есть».
    function trayWash(item) {
        const w = String(trayCfg.icon_style || "original").trim().toLowerCase()
        if (["light", "clear", "tinted", "mono"].indexOf(w) < 0 || !item || trayKeepColor(item)) return "none"
        return w
    }
    function trayShows(item) {
        const names = trayNames(item)
        if (!names.length) return false
        return !trayHidden.some(h => names.some(n => trayKeyHits(h, n)))
    }
    // Раскладка клавиатуры: демон узнаёт о смене сигналом плазмы и присылает уже готовое.
    property var layout: null
    readonly property string layoutShort: layout ? String(layout.id || "").toUpperCase().slice(0, 2) : ""
    function layoutNext() { send({ cmd: "layout_next" }) }
    // Спрашиваем при подключении: демон сам присылает только смены, а островок мог подключиться
    // позже и первой смены не дождаться до вечера.
    function layoutRefresh() { send({ cmd: "layout" }) }

    // Нажатие по значку многие программы отрабатывают наполовину: Activate они принимают, а
    // поднять своё свёрнутое окно под Wayland не могут — KWin не даёт поднять себя тому, у кого
    // нет фокуса. Telegram так пропадал совсем: значок в лотке есть, окна нет, войти некуда.
    // Поэтому после activate() просим KWin сами — и только если окно действительно свёрнуто,
    // иначе отняли бы у программы право спрятать окно щелчком по тому же значку.
    property var trayWakeWho: null
    function trayWake(item) {
        const names = trayNames(item)
        if (!names.length) return
        trayWakeWho = names[0]
        trayWaker.restart()
    }
    Timer {
        id: trayWaker
        interval: 450          // даём программе успеть самой: вмешиваемся только если не вышло
        onTriggered: {
            if (!jd.trayWakeWho) return
            trayWakeRun.command = ["justday", "windows", "wake", String(jd.trayWakeWho)]
            trayWakeRun.running = true
        }
    }
    Process { id: trayWakeRun }

    function trayHide(ident, on, aliases) {
        if (!ident && !(aliases && aliases.length)) return
        const msg = { cmd: "tray_hide", id: String(ident || ""), on: on === undefined ? null : on }
        if (aliases && aliases.length) msg.aliases = aliases.map(a => String(a))
        send(msg)
    }
    // Settings toggle / Ctrl+right-click: hide by primary id, show by clearing the whole
    // alias family so a leftover "discord-tray" cannot keep Discord dark after enabling.
    function trayHideItem(item, hide) {
        const names = trayNames(item)
        if (!names.length) return
        if (hide)
            trayHide(names[0], true)
        else
            trayHide(names[0], false, names)
    }
    // Чьё меню лотка открыто и от какой точки оно растёт. Меню живёт в своём окне во весь экран —
    // иначе его нечем закрыть щелчком мимо, — а окно узнаёт о нажатии отсюда.
    property var trayMenu: null           // сам значок (SystemTrayItem): у него спрашиваем item.menu
    property real trayMenuX: 0
    property real trayMenuY: 0
    property bool trayMenuFromBar: false  // меню с полосы растёт влево, под значок, а не вправо от него
    readonly property int barTraySize: {
        const n = (settings.island || ({})).bar_tray_size
        return Math.max(14, Math.min(32, n || 22))
    }
    function openTrayMenu(item, x, y) {
        if (!item || !item.hasMenu) return
        trayMenuX = x
        trayMenuY = y
        trayMenu = item
    }
    function closeTrayMenu() { trayMenu = null; trayMenuFromBar = false }
    // Насколько занят процессор — для кошки в доке. Демон присылает сам, раз в две секунды и
    // только когда есть кому смотреть.
    property real cpu: 0
    property real mem: 0                  // занятая память в процентах — подсказка над кошкой
    // Где кошка на сплошной полосе. Своё значение до ответа демона: иначе отпущенная кошка
    // прыгала бы обратно на миг, пока `config set` доходит до файла и возвращается.
    property string catPlaceNow: ""
    readonly property string catPlace: catPlaceNow || island.cat_place || "clock"
    function moveCat(place) {
        if (place === catPlace) return
        catPlaceNow = place
        setConfig("island.cat_place", place)
    }
    property Item catTipAt: null          // над какой кошкой держат курсор — под ней подсказка
    // Кошку несут рукой (CatCarry в shell.qml): какую, где рука в координатах окна и над треем ли.
    property Item catFrom: null
    property point catHand: Qt.point(0, 0)
    property bool catOverTray: false
    function catDrop() {
        if (catFrom) moveCat(catOverTray ? "tray" : "clock")
        catFrom = null
    }
    property var dockData: ({})           // {items, pinned, match, skip} — от демона
    // Seed from on-disk catalog before the daemon hello arrives (qs restart / hot-reload
    // otherwise paints only launcher+trash+cat for a beat — the "empty dock flash").
    property bool dockSeeded: false
    readonly property string dockCatalogPath: {
        const st = Quickshell.env("XDG_STATE_HOME")
        if (st) return st + "/justday/dock-catalog.json"
        return (Quickshell.env("HOME") || "") + "/.local/state/justday/dock-catalog.json"
    }
    FileView {
        id: dockCatalogFile
        path: jd.dockCatalogPath
        blockLoading: true
        watchChanges: false
    }
    function seedDockFromDisk() {
        if (dockData && dockData.items && dockData.items.length) return
        try {
            const raw = String(dockCatalogFile.text() || "").trim()
            if (!raw) return
            const d = JSON.parse(raw)
            if (d && d.items && d.items.length) {
                dockData = d
                if (d.trash_full !== undefined) trashFull = !!d.trash_full
                dockSeeded = true
            }
        } catch (e) {}
    }
    Component.onCompleted: seedDockFromDisk()
    // Открытые окна. Спрашивать вейланд бесполезно: KWin не отдаёт список окон обычным клиентам —
    // ни wlr-foreign-toplevel, ни org_kde_plasma_window_management в реестре нет. Список приходит от
    // демона, которому о нём рассказывает скрипт, живущий внутри самого KWin.
    // `windows` меняется только когда поменялся состав или состояние окон (открыли, закрыли, свернули, сменили
    // название); `windowRects` — тот же список с геометрией, он обновляется на каждое движение окна. Док
    // пересобирает ячейки по `windows`, а когда окно просто тащат за угол, ему пересобирать нечего: раньше
    // ячейки пересоздавались около пяти раз в секунду, пока окно двигали (Р-40). Геометрия нужна только
    // тем, кто смотрит, накрыло ли окно док или оно во весь экран, — они читают `windowRects`.
    property var windows: []
    property var windowRects: []
    property string _windowShape: ""
    function setWindows(list) {
        windowRects = list
        const shape = windowShape(list)
        if (shape === _windowShape) return
        _windowShape = shape
        windows = list
    }
    // Состояние окон без геометрии — по нему решаем, трогать ли `windows`.
    function windowShape(list) {
        return JSON.stringify(list.map(w => {
            const c = Object.assign({}, w)
            for (const k of ["x", "y", "w", "h", "ox", "oy", "ow", "oh"]) delete c[k]
            return c
        }))
    }
    // Есть ли впереди окно во весь экран. Считается здесь, а не в доке: то же самое пригодится
    // и островку, и уведомлениям — поверх игры им тоже не место.
    readonly property bool fullscreen: windows.some(w => w && w.full === true && !w.minimized)
    // Оценка высоты полосы дока (карточка + отступ), пока окно дока ещё не посчитало cardHeight.
    readonly property real dockStripGuess: Math.max(48, dockIconSize + Math.round(dockIconSize * 0.36) + 17)
    // Island peek strip when mode is hidden (shared with EdgeReveal timings).
    function islandPeekHeight(hoverReveal) { return hoverReveal !== false ? 3 : 0 }
    // Apps whose windows must never hide the dock (our own layers, Plasma chrome).
    readonly property var dockCoverIgnore: ["quickshell", "plasmashell", "org.kde.plasmashell",
                                            "kwin_wayland", "ksplashqml", "xwaylandvideobridge",
                                            "xdg-desktop-portal-kde"]
    // islandX/islandW = screen-local dock card rect (icons+padding). Hit-test that island,
    // not the full bottom/top strip — otherwise any window along the edge hides the dock.
    function windowCoversDockStrip(w, screen, stripPx, atTop, islandX, islandW) {
        if (!w || !screen || w.minimized) return false
        const app = String(w.app || "").toLowerCase()
        if (app && (dockCoverIgnore.indexOf(app) >= 0 || (dockSkip || []).indexOf(app) >= 0))
            return false
        // Prefer the window's own output geometry when KWin sent it — Quickshell screen
        // x/y can disagree with KWin for a frame on reconnect.
        const sx = (w.ow > 0 ? (w.ox || 0) : screen.x)
        const sy = (w.ow > 0 ? (w.oy || 0) : screen.y)
        const sw = (w.ow > 0 ? w.ow : screen.width)
        const sh = (w.oh > 0 ? w.oh : screen.height)
        if (sw <= 0 || sh <= 0) return false

        if (w.full === true) {
            // True KWin fullscreen only hides the dock on the output it occupies.
            if (w.screen && screen.name)
                return w.screen === screen.name
            if (w.ow > 0)
                return Math.abs((w.ox || 0) - screen.x) <= 4 && Math.abs((w.oy || 0) - screen.y) <= 4
            return false
        }

        const strip = Math.max(24, stripPx || dockStripGuess)
        let onScreen = false
        if (w.screen && screen.name && w.screen === screen.name) onScreen = true
        else if (w.ow > 0 && w.oh > 0
                 && Math.abs((w.ox || 0) - screen.x) <= 4 && Math.abs((w.oy || 0) - screen.y) <= 4)
            onScreen = true
        else {
            const ww0 = w.w || 0, wh0 = w.h || 0
            if (ww0 <= 0 || wh0 <= 0) return false
            const wx0 = w.x || 0, wy0 = w.y || 0
            onScreen = wx0 < sx + sw && wx0 + ww0 > sx && wy0 < sy + sh && wy0 + wh0 > sy
        }
        if (!onScreen) return false

        const ww = w.w || 0, wh = w.h || 0
        if (ww <= 0 || wh <= 0) return false
        const wx = w.x || 0, wy = w.y || 0
        // Horizontal miss vs this output.
        if (wx >= sx + sw || wx + ww <= sx) return false

        // True cover of the output (maximise / borderless) → overlaps dock island for sure.
        const fullCover = Math.abs(wy - sy) <= 8 && Math.abs(wh - sh) <= 8
                          && Math.abs(wx - sx) <= 8 && Math.abs(ww - sw) <= 8
        if (fullCover) return true

        // Unknown island geometry → do not hide (avoids full-width-strip false positives).
        const iw = Number(islandW) || 0
        if (iw <= 0) return false
        const il = sx + (Number(islandX) || 0)
        const ir = il + iw
        // Miss the centered card horizontally (window only opposite empty edge).
        if (wx >= ir || wx + ww <= il) return false

        // Require a meaningful bite of the strip — a 1px graze from shadows / resize
        // handles was a false positive that hid the dock on an otherwise empty edge.
        const minBite = Math.min(20, Math.max(8, Math.round(strip * 0.35)))
        let overlapY = 0
        if (atTop) {
            const stripBottom = sy + strip
            overlapY = Math.min(wy + wh, stripBottom) - Math.max(wy, sy)
        } else {
            const stripTop = sy + sh - strip
            overlapY = Math.min(wy + wh, sy + sh) - Math.max(wy, stripTop)
        }
        if (overlapY < minBite) return false

        // Overlap the real dock island (icons+padding), not the full bottom/top edge.
        const overlapX = Math.min(wx + ww, ir) - Math.max(wx, il)
        const minX = Math.min(24, Math.max(8, Math.round(iw * 0.08)))
        return overlapX >= minX
    }
    // Окно наезжает на островок дока на этом экране (или true-fullscreen на нём).
    // Empty window list → never hide (false positive guard for startup / watch restart).
    // islandX/islandW — локальные к экрану координаты карточки (dock.x / dock.width).
    function dockCoveredOn(screen, stripPx, atTop, islandX, islandW) {
        if (dockCfg.hide_on_fullscreen === false) return false
        if (!screen) return false
        if (!windowRects || !windowRects.length) return false
        const strip = stripPx || dockStripGuess
        const top = !!atTop
        for (let i = 0; i < windowRects.length; i++) {
            if (windowCoversDockStrip(windowRects[i], screen, strip, top, islandX, islandW))
                return true
        }
        return false
    }
    readonly property var dockItems: dockData.items || []
    readonly property var dockMatch: dockData.match || ({})
    readonly property var dockSkip: dockData.skip || []
    // WM_CLASS values that get one dock slot per window (anti-detect browser profiles).
    readonly property var dockSeparate: dockData.separate || []   // список приходит от демона (dock.SEPARATE_INSTANCES), своего у острова нет
    // Готовый файл значка меню: демон нашёл его в теме и перекрасил в белый. Пусто — рисуем свою
    // сетку точек.
    readonly property string dockLauncher: dockData.launcher || ""
    // Кадры кошки. Пусто — у островка есть свои; иначе это кадры виджета CatWalk с этой машины.
    readonly property var dockCat: dockData.cat || ({})
    // Корзина: пустая и полная — разные значки. Демон следит и говорит, когда меняется.
    property bool trashFull: false
    // Где на экране значок меню. Меню вырастает оттуда и туда же садится: иначе оно появляется
    // ниоткуда, и непонятно, что его открыл именно этот значок.
    property var dockAnchor: null
    // Где на экране лежат карточка дока и полоса лотка. Нужно меню: оно перекрывает весь экран,
    // чтобы закрываться щелчком мимо, и без дырок в этом перекрытии док под ним становится
    // картинкой — по значку видно, а нажать нельзя.
    // Размер меню приложений: его задаёт человек, потянув карточку за угол, и он же запоминается.
    // Считать размер по содержимому нельзя — тогда лента разделов уезжает после каждого нажатия.
    readonly property real menuWidth: Math.max(520, island.menu_width || 760)
    readonly property real menuHeight: Math.max(360, island.menu_height || 620)
    function saveMenuSize(w, h) {
        setConfig("island.menu_width", Math.round(w))
        setConfig("island.menu_height", Math.round(h))
    }

    property var dockRect: null
    property var trayRect: null
    // Чисто для проверки руками: `qs -p island ipc call island dock` показывает, где курсор и
    // насколько включено увеличение. Без этого «навёл — не увеличилось» проверяется линейкой по
    // снимку экрана, а это не проверка.
    property var dockHover: []

    // appId окна → программа, которой оно принадлежит. Промах — не беда: значок всё равно будет,
    // только подписанный тем, как окно назвало себя само.
    function dockLookup(appId) {
        const a = String(appId || "").toLowerCase()
        if (!a) return null
        return dockMatch[a] || (a.indexOf(".") > 0 ? dockMatch[a.split(".").pop()] : undefined) || null
    }
    function dockRefresh() { send({ cmd: "dock" }) }
    function dockRun(item) { if (item) send({ cmd: "apps_run", kind: item.kind || "app", id: item.id }) }
    // Бросили файлы на значок — отдать их этой программе. Пути снимаются с ссылок один раз, здесь:
    // дальше по дороге они только портятся, а программа ждёт обычный путь, а не file://.
    function dropOn(item, urls) {
        const files = plainPaths(urls)
        if (!item || !files.length) return
        send({ cmd: "apps_run", kind: item.kind || "app", id: item.id, files: files })
    }
    function dropToTrash(urls) {
        const files = plainPaths(urls)
        if (!files.length) return
        send({ cmd: "trash_put", files: files })
        // Ответ разбирается здесь же: выбросить файл можно не всегда — с временных разделов,
        // например, система этого не позволяет нарочно. Молча проглотить отказ нельзя: человек
        // отпустил файл над корзиной и уверен, что дело сделано.
        trashWaiting = true
    }
    property bool trashWaiting: false
    function plainPaths(urls) {
        const out = []
        for (const u of (urls || [])) {
            let s = String(u)
            if (s.startsWith("file://")) s = decodeURIComponent(s.slice(7))
            if (s && s[0] === "/") out.push(s)
        }
        return out
    }
    function dockPin(kind, ident, on) {
        if (!ident) return
        send({ cmd: "dock_pin", kind: kind || "app", id: ident, on: on === undefined ? null : on })
    }
    function dockArrange(keys) { send({ cmd: "dock_arrange", keys: keys }) }
    // Содержимое закреплённой папки: спрашивается при каждом открытии стопки, потому что за минуту
    // между двумя нажатиями папка могла и поменяться — показать вчерашнее содержимое хуже, чем
    // подождать полкадра.
    property var folderItems: []
    property string folderPath: ""
    property int folderMore: 0
    function folderList(path) { send({ cmd: "folder_list", path: String(path) }) }
    function folderOpen(path) { send({ cmd: "folder_open", path: String(path) }) }
    function windowDo(action, id) { if (id) send({ cmd: "window_do", action: action, id: id }) }

    // ─── dock hover thumbnails ───
    property var thumbs: ({})          // window id → jpeg path
    property var thumbPending: ({})
    property int thumbFailCount: 0
    // After repeated capture failures, tip stays macOS-style (name / title list; no empty frames).
    property bool thumbCaptureBroken: false
    function thumbPath(id) {
        const k = String(id || "")
        return (thumbs && thumbs[k]) ? thumbs[k] : ""
    }
    function requestThumb(id) {
        const k = String(id || "")
        if (!k || thumbCaptureBroken || thumbPending[k]) return
        if (thumbs[k]) return
        const nextPend = Object.assign({}, thumbPending)
        nextPend[k] = true
        thumbPending = nextPend
        send({ cmd: "window_thumb", id: k })
    }
    property var lastDockIcons: ({})
    function publishDockIcons(icons, forceReconfigure) {
        lastDockIcons = icons || ({})
        send({ cmd: "dock_icons", icons: lastDockIcons,
               reconfigure: forceReconfigure === true ? true : null })
    }
    // Screen rect of a dock cell (geom is local to DockView; dockRect is screen-ish).
    function dockIconScreenRect(g) {
        if (!g || !dockRect) return null
        const atTop = !!(dockRect.y !== undefined && dockPlace !== "bottom")
        // dockRect.y is the card's top on screen when at top; when at bottom it's card top too.
        const cardY = dockRect.y
        const cardX = dockRect.x
        // geom x is relative to DockView; DockView is centered — dockRect.x is the view's left.
        return {
            x: Math.round(cardX + g.x + (g.w - Math.min(g.w, dockIconSize)) / 2),
            y: Math.round(cardY + (dockPlace === "bottom" ? Math.max(0, (dockRect.h || 0) - dockIconSize - 8) : 8)),
            w: Math.round(Math.min(g.w, dockIconSize + 8)),
            h: Math.round(dockIconSize + 8)
        }
    }

    // ─── genie minimize ───
    // Primary: KWin justday_genie effect scales the real window toward dock icon
    // rects published via dock_icons. QML overlay is a fallback if the effect is off.
    property var genie: null
    property bool genieEffect: true
    function minimizeGenie(win, iconRect) {
        if (!win || !win.id) return
        // Dock already publishes full icon map; do not overwrite it with a one-key patch.
        if (!genieEffect) {
            const from = {
                x: win.x || 0, y: win.y || 0,
                w: Math.max(32, win.w || 200), h: Math.max(32, win.h || 120)
            }
            const to = iconRect || {
                x: Math.round(screenWidth / 2 - 24),
                y: dockPlace === "top" ? 12 : Math.round(screenHeight - 60),
                w: 48, h: 48
            }
            const hit = dockLookup(win.app)
            genie = {
                id: String(win.id), app: String(win.app || ""),
                icon: hit ? hit.icon : String(win.app || ""),
                title: String(win.title || ""), from: from, to: to
            }
            genieKick.restart()
            return
        }
        // Fresh IconsJson into the effect right before minimize (debounced path may be stale).
        publishDockIcons(lastDockIcons, true)
        windowDo("minimize", String(win.id))
    }
    Timer {
        id: genieKick
        interval: 40
        onTriggered: {
            if (jd.genie && jd.genie.id)
                jd.windowDo("minimize", jd.genie.id)
        }
    }
    function dockIsPinned(key) { return (dockData.pinned || []).indexOf(key) >= 0 }
    onLinkedChanged: if (linked) { dockRefresh(); mascotRefresh(); layoutRefresh() }

    property bool settingsOpen: false
    property string settingsPage: "general"
    function openSettings(page) { settingsPage = page || "general"; settingsOpen = true; expanded = false }
    function closeAll() { settingsOpen = false; expanded = false; composeOpen = false; playerOpen = false; trayMenu = null; closeTools() }
    function openManual() { Quickshell.execDetached(["xdg-open", "https://github.com/0nigiris/JustDay/blob/main/docs/MANUAL.md"]); closeAll() }

    // animation style from settings: spring (bouncy), smooth (no overshoot) or off
    readonly property var island: settings.island || ({})
    readonly property string animStyle: island.animations || "spring"
    // Игровой режим (Р2-46): игра на весь экран — оболочка не анимирует ничего. Все Behavior и
    // таймеры уже гасятся через animOn, так что одно условие снимает с видеокарты и процессора
    // всё, что оболочка делала бы поверх игры.
    property string game: ""          // имя запущенной игры от демона, "" — нет
    readonly property bool gameMode: game !== "" && fullscreen
    readonly property bool animOn: animStyle !== "off" && !gameMode
    readonly property real springK: animStyle === "smooth" ? 7.5 : 4.2
    readonly property real springDamping: animStyle === "smooth" ? 1.0 : 0.36
    // Fixed-duration OutCubic reads clean at high Hz; soft springs sample like ~60 fps.
    readonly property int slideMs: 200
    // macOS-like: fast start, soft settle (no Spring hitch at end)
    readonly property int slideEase: Easing.OutQuint
    function dur(ms) { return animOn ? ms : 0 }
    // Три длительности и две кривые на весь проект. Раньше в Behavior стояли числа от 55 до 450 без
    // системы, а линейная кривая по умолчанию делала отклик на нажатие «деревянным». Гасит их всех
    // одно место — animOn: каждый Behavior пишет `enabled: JD.animOn`.
    readonly property int durFast: 120    // отклик на нажатие и наведение
    readonly property int durBase: 200    // появление, смена размера
    readonly property int durSlow: 400    // смена обложки, взгляд: то, что должно быть плавным
    readonly property int easeOut: Easing.OutCubic     // обычное затухание
    readonly property int easeSoft: Easing.OutQuint    // крупные карточки: быстрый старт, мягкая посадка
    // Жест нажатия один на все кнопки: сжатие и его длительность лежат здесь, а не в девяти копиях.
    readonly property real pressScale: 0.94           // обычная кнопка
    readonly property real pressScaleSmall: 0.9       // значок: он мал, и 0.94 не видно
    // сколько оставить сверху: панель KDE у верхнего края больше не уходит под остров
    // Где висит остров и в какую сторону он растёт. Пилюля горизонтальная, поэтому «слева» и
    // «справа» — это край по горизонтали, а не поворот на бок: повёрнутая пилюля не вмещает ни
    // строки ответа, ни волны голоса, ни плеера.
    // Frost under dock/tray/menu. Do NOT gate on global `fullscreen`: that property is
    // true if ANY output has a fullscreen window, which killed blur on every monitor
    // (and darkened card tints via DockView/TrayView). Per-screen hide already drops
    // blur with the strip: dockBlur/trayBlur use `… && dockWin.shown` / `trayWin.shown`,
    // and shown follows dockCoveredOn (true-fullscreen / overlap on THAT output only).
    readonly property bool blurOn: island.blur !== false
    readonly property string place: island.position || "top-center"
    readonly property bool atTop: !place.startsWith("bottom")
    readonly property string side: place.split("-")[1] || "center"
    readonly property real sideMargin: 16
    // Toast placement (Settings → Виджеты). Independent of the island pill.
    readonly property string notifPlace: island.notification_position || place || "top-right"
    function resolveNotifScreen() {
        const screens = Quickshell.screens
        if (!screens.length) return null
        const want = String(island.notification_screen ?? "secondary")
        const primary = screens.find(s => s.x === 0 && s.y === 0) || screens[0]
        if (want === "primary") return primary
        if (want === "secondary") return screens.find(s => s !== primary) || primary
        if (want === "" || want === "island") {
            const named = island.screen ? screens.find(s => s.name === island.screen) : null
            return named || primary
        }
        return screens.find(s => s.name === want) || primary
    }
    // System OSD (volume / layout / brightness) — Noctalia-like, separate from app toasts.
    readonly property string osdPlace: island.osd_position || place || "top-center"
    function resolveOsdScreen() {
        const screens = Quickshell.screens
        if (!screens.length) return null
        const want = String(island.osd_screen ?? "island")
        const primary = screens.find(s => s.x === 0 && s.y === 0) || screens[0]
        if (want === "primary") return primary
        if (want === "secondary") return screens.find(s => s !== primary) || primary
        if (want === "" || want === "island") {
            const named = island.screen ? screens.find(s => s.name === island.screen) : null
            return named || primary
        }
        return screens.find(s => s.name === want) || primary
    }
    property bool osdShow: false
    property string osdKind: ""       // volume | layout | brightness
    property real osdValue: 0         // 0–1 for bars; unused for layout
    property string osdLabel: ""
    property string osdIcon: ""
    property bool osdMuted: false
    property bool _osdPrimed: false   // skip first volume snapshot at UI start
    property bool _brightPrimed: false
    property real _lastBrightFrac: -1
    function showOsd(kind, value, label, icon, muted) {
        if (island.show_osd === false) return
        osdKind = String(kind || "")
        osdValue = Math.max(0, Math.min(1, Number(value) || 0))
        osdLabel = String(label || "")
        osdIcon = String(icon || "")
        osdMuted = !!muted
        osdShow = true
        osdTimer.restart()
    }
    Timer { id: osdTimer; interval: 1600; onTriggered: jd.osdShow = false }
    readonly property real topMargin: island.top_margin === undefined ? 8 : Math.max(0, Math.min(400, island.top_margin))
    property bool peeking: false
    // Вид верхней полосы. Это не вкусовщина: капсула посреди верхнего края физически перекрывает
    // вкладки браузера, и тому, кто много живёт в браузере, нужен другой вид, а не уговоры привыкнуть.
    //   island — капсула, плавающая под краем (как сейчас);
    //   bar    — сплошная полоса во всю ширину, вплотную к краю;
    //   notch  — вырез: прижат к краю, скруглён только снизу.
    readonly property string islandStyle: {
        const want = String(island.style || "island").toLowerCase()
        return ["island", "bar", "notch"].indexOf(want) >= 0 ? want : "island"
    }
    readonly property bool barAutohide: island.bar_autohide === true
    // Толщина сплошной полосы. Карточка настроек растёт вниз от неё, сама полоса не едет.
    readonly property real barHeight: {
        const n = Number(island.bar_height)
        if (!isFinite(n) || n <= 0) return 44
        return Math.max(28, Math.min(96, Math.round(n)))
    }
    // Пока играет музыка, работа не отбирает островок себе: обложка остаётся на месте, а о работе
    // говорит точка рядом с ней. Молчать о работе вообще — не то же самое: когда острову нечего
    // показывать, кроме работы, человек должен видеть, чем он занят, а не кружок без слов.
    readonly property bool workQuiet: island.work_quiet !== false
    property int workStep: 1
    function workMore() { workStep = workStep >= 2 ? 1 : 2; detailOpen = workStep >= 2 }
    // Подробности раскрыты: или шагом по значку работы, или стрелкой на карточке.
    property bool detailOpen: false
    property bool islandHovered: false

    // Полноэкранное окно на том мониторе, где висит полоса. Не путать с «окно задело док»:
    // здесь только настоящий fullscreen KWin, и только этот экран.
    function screenHasFullscreen(screen) {
        if (!screen || !windowRects || !windowRects.length) return false
        for (let i = 0; i < windowRects.length; i++) {
            const w = windowRects[i]
            if (!w || w.minimized || w.full !== true) continue
            const app = String(w.app || "").toLowerCase()
            if (app && dockCoverIgnore.indexOf(app) >= 0) continue
            if (w.screen && screen.name) {
                if (w.screen === screen.name) return true
                continue
            }
            if ((w.ow || 0) > 0 && Math.abs((w.ox || 0) - screen.x) <= 4 && Math.abs((w.oy || 0) - screen.y) <= 4)
                return true
        }
        return false
    }
    readonly property bool barFullscreen: {
        if (islandStyle !== "bar") return false
        const screens = Quickshell.screens
        if (!screens || !screens.length) return false
        const named = island.screen ? screens.find(s => s.name === island.screen) : null
        const screen = named || screens.find(s => s.x === 0 && s.y === 0) || screens[0]
        return screenHasFullscreen(screen)
    }

    readonly property string mode: {
        if (alarm) return "alarm"                      // a timer going off outranks everything: it is waiting on you
        // Игра или любое окно во весь экран убирает полосу само. Это не настройка:
        // автоскрытие по курсору остаётся отдельно и складывается с этим.
        if (islandStyle === "bar" && barFullscreen) return "hidden"
        if (composeOpen && !approvalText) return "compose"
        if (expanded && !approvalText && !settingsOpen) return "expanded"
        if (approvalText) return "approval"
        if (settingsOpen) return "settings"
        if (toolsPage) return "tools"
        if (card) return "card"
        // видео выше слушания: оно не исчезает, когда заговорили с ассистентом — слушание,
        // «думаю…» и ответ идут строкой поверх кадра, как субтитры
        if (video && !videoMini) return "video"
        if (dstate === "listening") return answerOpen ? "answer" : "listening"
        if (playerOpen && musicOn) return "player"
        // notifications render on notifWin (corner toast); keep the island free
        // if (notification) return "notification"
        if (flashText) return "flash"
        if (answerOpen) return "answer"
        if (dstate === "transcribing") return "transcribing"
        // Музыка на островке — обложка и эквалайзер, и это самое красивое, что он показывает.
        // Работа поверх неё — чёрная полоса с текстом вместо обложки; поэтому, пока играет
        // музыка, работа остаётся точкой на её карточке, а островок себе не забирает.
        if ((dstate === "thinking" || dstate === "speaking") && !(workQuiet && musicShown)) return "thinking"
        if (video && videoMini && workers === 0) return "videopill"
        if (musicShown && (!workQuiet ? workers === 0 : true)) return "music"
        if (peeking || workers > 0) return "peek"
        // Меню-бар не прячется сам: иначе у верхнего края пусто, пока не подведёшь курсор.
        // Прятать его — отдельная настройка, и только для сплошной полосы.
        if (islandStyle === "bar" && !barAutohide) return "peek"
        return "hidden"
    }
    onModeChanged: if (mode !== "thinking") { detailOpen = false; workStep = 1 }
    // Прятать и возвращать полосу от полноэкранного окна быстрее, чем обычное раскрытие.
    // Флаг живёт ещё немного после выхода: анимация показа стартует, когда fullscreen уже false.
    property bool armedQuick: false
    onBarFullscreenChanged: {
        if (barFullscreen) {
            armedQuick = true
            expanded = false
            settingsOpen = false
            composeOpen = false
        } else {
            barQuickOff.restart()
        }
    }
    Timer { id: barQuickOff; interval: 200; onTriggered: jd.armedQuick = false }

    // ───────────── look ─────────────
    readonly property color ink: "#000000"
    readonly property color text1: "#f5f5f7"
    readonly property color text2: Qt.rgba(235 / 255, 235 / 255, 245 / 255, 0.62)
    // 0.48 keeps captions at ~4.8:1 on the island's black; 0.34 measured 2.8:1, below the 4.5:1 floor
    readonly property color text3: Qt.rgba(235 / 255, 235 / 255, 245 / 255, 0.48)
    // Поверхность меню приложений. Она почти непрозрачная нарочно: на ней читают и целятся, а
    // размытие под ней — только чтобы край карточки не выглядел вырезанным из картона. Док и лоток
    // — наоборот, накладки поверх работы, и там прозрачность на месте.
    readonly property color menuSurface: Qt.rgba(0.04, 0.04, 0.05, 0.93)
    // Карточка меню почти непрозрачна, поэтому те же стеклянные заливки здесь слабее терялись бы;
    // оттенки принадлежат общей палитре, но сохраняют нужную контрастность этой поверхности.
    readonly property color menuFill1: Qt.rgba(1, 1, 1, 0.10)
    readonly property color menuFill2: Qt.rgba(1, 1, 1, 0.18)
    readonly property color menuFill3: Qt.rgba(1, 1, 1, 0.26)
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
        "moon": "moon", "cloud": "cloud",
        // Без этих имён шапка почты, календаря и вопроса показывала запасные «искры» вместо своего
        // значка — человек это и назвал «иконки как будто не там».
        "mail-message": "mail", "mail-send": "mail", "mail-unread": "mail", "view-calendar": "calendar-clock",
        "dialog-question": "circle-help", "view-restore": "minimize-2"
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
        "video", "volume-2", "volume-x", "wand-sparkles", "x", "zap",
        // значки панели инструментов
        "smile", "clipboard", "memory-stick", "hard-drive", "thermometer", "network", "wifi", "bluetooth", "gauge",
        "trash-2", "grip-vertical", "camera", "minus", "star", "wifi-off", "list-plus", "arrow-left", "pencil", "minimize-2",
        "mic-off", "sliders-horizontal", "volume-1", "lock", "star",
        "arrow-right", "circle-stop"
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

    // ───────────── сидит ли человек за машиной ─────────────
    // Режим сервера гасил и запирал экран под руками у работающего человека. Простой ввода по
    // Wayland знает только тот, у кого есть окно, а у KWin нет GetSessionIdleTime, — поэтому
    // спрашиваем здесь и пишем в файл, который читает `server.here()`. Запрет простоя от видео не в
    // счёт (respectInhibitors: false): ушёл спать с фильмом — значит ушёл. Переписываем раз в 30 с,
    // чтобы мёртвый островок не оставил после себя вечное «сидит» или «ушёл».
    IdleMonitor { id: presence; timeout: 60; respectInhibitors: false; onIsIdleChanged: jd.writePresence() }
    FileView { id: presenceFile; path: (Quickshell.env("XDG_RUNTIME_DIR") || "/tmp") + "/justday-presence.json"; atomicWrites: true }
    function writePresence() { presenceFile.setText(JSON.stringify({ idle: presence.isIdle, at: Date.now() / 1000 })) }
    Timer { interval: 30000; repeat: true; running: true; triggeredOnStart: true; onTriggered: jd.writePresence() }

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
            onError: jd.lastMessage = Date.now()
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
        onTriggered: {
            const silent = Date.now() - jd.lastMessage
            const due = jd.linked ? silent > 12000 : silent > 4000
            if (due) { jd.lastMessage = Date.now(); jd.reconnect() }
        }
    }

    // one-shot commands: a short-lived connection per request (the daemon answers one line and closes)
    Component {
        id: commandSocket
        Socket {
            property string payload
            path: jd.socketPath
            // Ответ на команду разбираем, а не выбрасываем. Раньше сокет умирал на первой строке,
            // и всё, что демон отвечает (сетка эмодзи, история буфера, нагрузка), не доходило вовсе:
            // островок узнавал только то, что демон присылает сам.
            parser: SplitParser {
                onRead: line => {
                    try { jd.handle(JSON.parse(line)) } catch (e) { console.warn("island reply:", e, line) }
                    destroy()
                }
            }
            onConnectedChanged: if (connected) { write(payload + "\n"); flush() }
            Component.onCompleted: connected = true
        }
    }
    function send(obj) { commandSocket.createObject(jd, { payload: JSON.stringify(obj) }) }
    function run(args) { Quickshell.execDetached(["justday"].concat(args)) }
    // Настройка — сообщением демону, а не запуском `justday config set`: тот поднимал Python с импортом
    // всего пакета на каждый щелчок и сдвиг ползунка. Список записывается через запятую, как в командной строке.
    function setConfig(key, value) {
        send({ cmd: "config_set", key: key, value: Array.isArray(value) ? value.join(",") : String(value) })
    }

    function handle(m) {
        if (m.settings !== undefined) settings = m.settings
        if (m.history !== undefined) history = m.history
        if (m.workers !== undefined) workers = m.workers
        if (m.weather !== undefined) weather = m.weather
        if (m.update !== undefined) update = m.update
        if (m.next_event !== undefined) nextEvent = m.next_event
        if (m.game !== undefined) game = m.game || ""
        if (m.crash !== undefined) {
            crashCount = m.crash.count || 0
            if (m.crash.new > 0) flash(tr("Островок перезапустился после сбоя. Отчёт сохранён"), "circle-alert", accentOrange,
                                     [tr("Показать"), ["xdg-open", Quickshell.env("HOME") + "/.local/state/justday/crashes"]])
        }
        if (m.level !== undefined) level = Math.max(level * 0.6, m.level)
        if (m.followup !== undefined) followup = m.followup
        if (m.player !== undefined) {
            const was = player
            if (m.player && m.player.paused && was && !was.paused) { pauseGrace = true; graceTimer.restart() }
            player = m.player
            playerAt = Date.now()
            if (!m.player) playerOpen = false
        }
        // размер кадра не сбрасывается: его выбрали руками. Новый ролик всегда открывается развёрнутым
        if (m.video !== undefined) { if (!!m.video !== !!video) videoMini = false; video = m.video }
        if (m.video_last !== undefined) videoLast = m.video_last
        if (m.reminders !== undefined) reminders = m.reminders
        if (m.jobs !== undefined) jobs = m.jobs || []
        // ── панель инструментов ──
        if (m.panel !== undefined) { if (m.panel) openTools(m.panel); else closeTools() }
        if (m.menu !== undefined) {
            if (m.menu === "search") toggleSearch()
            else if (m.menu === "toggle") toggleMenu()
            else if (m.menu) openMenu()
            else closeMenu()
        }
        if (m.catalog !== undefined) {
            // Меню просит каталог при каждом открытии, и почти всегда приходит тот же самый. Подмена
            // объекта пересобирала всю сетку (сто шестьдесят значков, каждый грузится в главном потоке),
            // и именно этот кадр был самым долгим из всех при открытии: курсор ждал сетку, которая
            // ничем не отличалась от уже стоящей.
            const raw = JSON.stringify(m.catalog)
            if (raw !== menuCatalogRaw) {
                menuCatalogRaw = raw
                menuCatalog = m.catalog
                // Пустое «Избранное» в первый день выглядит поломкой, а не подсказкой: пока в нём ничего
                // нет, меню открывается на всех программах и молча ждёт, когда что-нибудь закрепят.
                if (menuGroup === "fav" && menuPinned.length === 0) menuGroup = "all"
            }
        }
        if (m.tracks !== undefined) libTracks = m.tracks || []
        if (m.chats !== undefined) chatList = m.chats || []
        if (m.messages !== undefined && m.kind === undefined) chatMessages = m.messages || []
        if (m.id !== undefined && _chatWantNew) { _chatWantNew = false; chatOpenOne(m.id); chatRefresh() }
        if (m.apps !== undefined) { menuFound = m.apps; menuPick = 0 }
        if (m.moved !== undefined || (trashWaiting && m.trash_full !== undefined && m.ok !== undefined)) {
            trashWaiting = false
            if (m.ok) flash(m.moved === 1 ? tr("В корзину") : tr("В корзину: ") + m.moved,
                            "user-trash-full", accentGreen)
            else flash(flat(m.error) || tr("Не вышло выбросить"), "circle-alert", accentRed)
        }
        if (m.layout !== undefined) {
            const prev = layout ? String(layout.id || "") : ""
            layout = m.layout
            const cur = layout ? String(layout.id || "") : ""
            if (prev && cur && prev !== cur)
                showOsd("layout", 0, (layoutShort || cur).toUpperCase(), "keyboard", false)
        }
        if (m.items !== undefined && m.file !== undefined) plans = m.items
        if (m.sessions !== undefined) sessions = m.sessions
        if (m.talk !== undefined) talk = m.talk
        if (m.items !== undefined && m.path !== undefined) {
            folderPath = m.path; folderItems = m.items; folderMore = m.more || 0
        }
        if (m.brain_model !== undefined) { brainModel = m.brain_model; brainWhy = m.brain_why || "" }
        if (m.brightness !== undefined && m.brightness_max) {
            const frac = Math.max(0, Math.min(1, Number(m.brightness) / Number(m.brightness_max)))
            const prev = _lastBrightFrac
            _lastBrightFrac = frac
            if (_brightPrimed && Math.abs(frac - prev) > 0.004)
                showOsd("brightness", frac, Math.round(frac * 100) + "%", "sun", false)
            _brightPrimed = true
        }
        if (m.mascots !== undefined) mascots = m.mascots
        if (m.dock !== undefined) {
            const incoming = m.dock || {}
            const hasItems = !!(incoming.items && incoming.items.length)
            // Never replace a good catalog with {} / empty items (hello race, watch gap).
            if (!hasItems && dockData && dockData.items && dockData.items.length) {
                if (incoming.trash_full !== undefined) trashFull = !!incoming.trash_full
                if (incoming.launcher || incoming.cat) {
                    const keep = Object.assign({}, dockData)
                    if (incoming.launcher) keep.launcher = incoming.launcher
                    if (incoming.cat) keep.cat = incoming.cat
                    if (incoming.trash_full !== undefined) keep.trash_full = incoming.trash_full
                    dockData = keep
                }
            } else {
                dockData = incoming
                if (incoming.trash_full !== undefined) trashFull = !!incoming.trash_full
                if (hasItems) dockSeeded = true
            }
        }
        if (m.cpu !== undefined) cpu = m.cpu
        if (m.mem !== undefined) mem = m.mem
        if (m.trash_full !== undefined) trashFull = m.trash_full
        if (m.windows !== undefined) {
            const next = m.windows || []
            // Watch restart / journal gap briefly publishes []; blanking the dock then
            // repainting every icon looked like icons "vanishing". Keep the last list
            // for a short grace unless we really have zero windows for a while.
            if (next.length === 0 && windows.length > 0) {
                _pendingEmptyWindows = true
                emptyWinGrace.restart()
            } else {
                _pendingEmptyWindows = false
                emptyWinGrace.stop()
                setWindows(next)
            }
        }
        if (m.emoji !== undefined) {
            toolsItems = m.emoji; emojiGroups = m.groups || emojiGroups
            if (toolsPick >= toolsItems.length) toolsPick = Math.max(0, toolsItems.length - 1)
        }
        if (m.qr !== undefined) qrRows = m.qr
        if (m.focus !== undefined) focusNow = m.focus
        if (m.clip !== undefined) {
            toolsItems = m.clip; clipPaused = !!m.paused; clipSkipped = m.skipped || 0
            if (toolsPick >= toolsItems.length) toolsPick = Math.max(0, toolsItems.length - 1)
        }
        // Полный текст для правки в панели буфера (preview обрезан).
        if (m.cmd === "window_thumb") {
            const id = String(m.id || "")
            if (id) {
                const nextPend = Object.assign({}, thumbPending)
                delete nextPend[id]
                thumbPending = nextPend
                if (m.ok && m.path) {
                    const next = Object.assign({}, thumbs)
                    next[id] = m.path
                    thumbs = next
                    thumbFailCount = 0
                } else if (!m.minimized && !m.private) {
                    // Capture unavailable (grim/KWin) or permanently broken → stop asking this session.
                    if (m.permanent)
                        thumbCaptureBroken = true
                    else {
                        thumbFailCount = thumbFailCount + 1
                        if (thumbFailCount >= 2)
                            thumbCaptureBroken = true
                    }
                }
            }
        }
        if (m.cmd === "clip_text" && m.ok && m.id && clipEditing === m.id)
            clipEditDraft = m.text || ""
        if (m.cmd === "clip_edit" && m.ok) { clipEditing = ""; clipEditDraft = ""; refreshTools() }
        if (m.cmd === "clip_pin" && m.ok) refreshTools()
        if (m.load !== undefined) {
            load = m.load
            // Графики держат минуту: дольше — уже не «что происходит сейчас», а история, которой
            // место не в островке. Массивы пересобираем целиком — QML замечает только это.
            if (m.load) {
                const keep = 60
                const push = (arr, v) => (arr.length >= keep ? arr.slice(arr.length - keep + 1) : arr).concat([v])
                loadHistory = {
                    cpu: push(loadHistory.cpu, m.load.cpu ? m.load.cpu.percent : 0),
                    mem: push(loadHistory.mem, m.load.memory ? m.load.memory.percent : 0),
                    gpu: push(loadHistory.gpu, m.load.gpu ? m.load.gpu.percent : 0),
                }
            }
        }
        if (m.state !== undefined && m.state !== dstate) {
            const was = dstate
            dstate = m.state
            if (m.state === "listening") {
                activity = ""; activityIcon = ""
                // продолжение разговора: ответ дочитывается, пока микрофон ждёт — отсчёт замирает
                if (followup && answerOpen) answerTimer.stop()
                else answerOpen = false
            }
            // заговорили в ответ — прошлая реплика больше не нужна, её место занимает «Думаю…»
            if ((m.state === "thinking" || m.state === "transcribing") && was === "listening") answerOpen = false
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
        case "chat":
            if (m.chat === chatCurrent) chatMessages = chatMessages.concat([m.message])
            chatRefresh()
            break
        case "chat_open": chatOpen = true; break
        case "wake_check": flash(m.matched ? tr("Услышал имя: «") + m.heard + "»" : (m.heard ? tr("Не то имя, услышал: «") + m.heard + "»" : tr("Ничего не услышал")), m.matched ? "check" : "mic", m.matched ? accentGreen : accentOrange); break
        case "chat_busy": if (m.chat === chatCurrent) chatBusy = !!m.busy; break
        case "notification":
            if (island.show_notifications === false) break
            if (!gameMode) { notification = m.notification; notifExpanded = false; notifTimer.restart() }
            notifications = [Object.assign({ ts: Qt.formatTime(new Date(), "HH:mm") }, m.notification)].concat(notifications).slice(0, 8)
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

    function flash(textValue, iconName, color, act) {
        flashAct = act || null
        flashTimer.interval = act ? 7000 : 2200
        flashText = textValue
        flashIcon = iconName || ""
        flashColor = color
        flashTimer.restart()
    }
    Timer { id: flashTimer; interval: 2200; onTriggered: { jd.flashText = ""; jd.flashAct = null } }
    property bool _pendingEmptyWindows: false
    Timer {
        id: emptyWinGrace
        interval: 900
        onTriggered: {
            if (jd._pendingEmptyWindows) {
                jd._pendingEmptyWindows = false
                jd.setWindows([])
            }
        }
    }
    Timer { id: notifTimer; interval: 6000; onTriggered: if (jd.islandHovered || jd.notifExpanded) restart(); else jd.notification = null }
    Timer {
        id: answerTimer
        // without a voice the text is all there is: give time to read it
        interval: jd.voiceOn && jd.micOn ? Math.min(15000, 4000 + jd.answer.length * 45) : Math.min(60000, 8000 + jd.answer.length * 70)
        onTriggered: if (jd.islandHovered || jd.dstate === "listening") restart(); else jd.answerOpen = false
    }
    Timer { id: cardTimer; onTriggered: if (jd.islandHovered) restart(); else jd.card = null }
    property bool revealLock: false
    function holdIsland() { leaveTimer.stop() }
    function revealFromEdge() {
        leaveTimer.stop()
        peeking = true
        revealLock = true
        revealLockTimer.restart()
    }
    function scheduleIslandHide() {
        if (revealLock || islandHovered) { if (islandHovered) leaveTimer.stop(); return }
        if (!leaveTimer.running) leaveTimer.restart()
    }
    function kickIslandHide() {
        if (revealLock || islandHovered) return
        leaveTimer.restart()
    }
    Timer {
        id: revealLockTimer
        interval: jd.slideMs + 80
        onTriggered: {
            jd.revealLock = false
            jd.scheduleIslandHide()
        }
    }
    Timer {
        id: leaveTimer
        interval: 420
        onTriggered: {
            if (jd.revealLock || jd.islandHovered) return
            jd.peeking = false
        }
    }
    onIslandHoveredChanged: {
        if (islandHovered) leaveTimer.stop()
        else if (!revealLock) leaveTimer.restart()
    }
}
