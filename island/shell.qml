// JustDay Dynamic Island — Quickshell (Qt Quick) layer-shell overlay.
// Talks to the daemon over $XDG_RUNTIME_DIR/justday.sock: `subscribe` for live status, one-shot commands back.
// Run: qs -p <repo>/island        (service: justday-island.service)
import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import "barTray.js" as BarTray
import Quickshell.Services.SystemTray
import Quickshell.Services.Notifications

ShellRoot {
    id: root

    // `qs -p <repo>/island ipc call island expand|collapse|toggle|peek` — e.g. bind a key to open the control center
    // ───────────── уведомления ─────────────
    //
    // Островок сам становится сервером уведомлений, когда это место свободно.
    //
    // Почему так вышло. Уведомления на фридесктопе показывает тот, кто первым занял имя на шине, и
    // это одно место на всю систему. Плазма занимает его своей панелью — а панель мы отсюда убрали,
    // ради чего всё и затевалось. Место осталось пустым, и его занял mako, демон уведомлений от
    // Sway: он и рисовал те синие плашки, которые не слушались ни «не беспокоить», ни настроек
    // плазмы, и висели часами, потому что срока жизни у них не было вовсе.
    //
    // Правильный ответ не «отобрать у mako», а «занять самим»: уведомления и так показывает остров,
    // своим шрифтом и своими цветами. Теперь они приходят напрямую, а не подслушиванием шины.
    //
    // Берём место, только если оно свободно: отбирать его у чужого сервера — чужое дело.
    // plasmashell almost always owns org.freedesktop.Notifications (history + tray). Quickshell's
    // NotificationServer only receives Notify when that name is free. The daemon's dbus-monitor
    // eavesdrop is therefore the reliable path on Plasma — keep it always on. Turning it off
    // after a flaky ownership probe used to kill the monitor and leave JustDay with zero toasts.
    // If we ever do own the bus, takeNotification dedupes against the eavesdrop copy.
    Loader {
        active: JD.island.notification_server !== false
        sourceComponent: NotificationServer {
            // Что мы умеем показать. Врать тут нельзя: программа спрашивает об этом заранее и по
            // ответу решает, что присылать. Скажем «умеем картинки» — получим картинки, которых
            // не нарисуем.
            bodySupported: true
            bodyMarkupSupported: false
            imageSupported: true
            actionsSupported: true
            inlineReplySupported: false
            persistenceSupported: true
            keepOnReload: false

            Component.onCompleted: JD.send({ cmd: "notify_watch", on: true })
            Component.onDestruction: JD.send({ cmd: "notify_watch", on: true })

            onNotification: n => {
                n.tracked = true
                JD.takeNotification({
                    id: n.id,
                    app: n.appName || "",
                    icon: n.appIcon || "",
                    desktop: n.desktopEntry || "",
                    summary: n.summary || "",
                    body: String(n.body || "").replace(/<[^>]+>/g, "").slice(0, 4000),
                    image: n.image || "",
                    urgency: String(n.urgency),
                    actions: (n.actions || []).map(a => ({ id: a.identifier, text: a.text }))
                }, n)
            }
        }
    }

    IpcHandler {
        target: "island"
        function expand(): void { JD.expanded = true }
        function collapse(): void { JD.closeAll() }
        function toggle(): void { JD.expanded = !JD.expanded }
        function settings(): void { JD.openSettings("general") }
        function chat(): void { JD.chatOpen = true }
        function settingsPage(page: string): void { JD.openSettings(page) }
        function peek(): void { JD.peeking = true; JD.islandHovered = false }
        function status(): string {
            return JSON.stringify({ screen: win.screen ? win.screen.name : null, screens: Quickshell.screens.map(s => s.name + "@" + s.x + "," + s.y),
                                    connected: JD.connected, dstate: JD.dstate, mode: JD.mode, visible: win.visible,
                                    island: [island.x, island.y, island.width, island.height, island.opacity] })
        }
        function snapshot(path: string): void { island.grabToImage(r => r.saveToFile(path)) }
        // Подать островку сообщение, как от демона: «почта выглядит криво» иначе не посмотреть, не
        // дождавшись настоящих писем. `qs ipc call island message '{"kind":"card","card":{…}}'`,
        // затем snapshot. На запертом сеансе — во вложенном `kwin_wayland --virtual` (ПЕРЕДАЧА.md).
        function message(json: string): void { JD.handle(JSON.parse(json)) }
        // Кошка без мыши: навести (clock|tray|""), взять и держать над точкой окна, отпустить.
        // Подсказка висит ниже капсулы, и snapshot её не видит: catTipShot снимает её саму, а
        // catTip отвечает, где она стоит относительно кошки.
        function catTip(which: string): void { JD.catTipAt = which === "tray" ? trayCat : which === "clock" ? peekView.cat : null }
        function catTipShot(path: string): string {
            catTip.grabToImage(r => r.saveToFile(path))
            const c = catTip.at ? catTip.at.mapToItem(catTip.parent, 0, 0) : null
            return JSON.stringify({ shown: catTip.opacity, tip: [catTip.x, catTip.y, catTip.width, catTip.height],
                                    cat: c ? [c.x, c.y, catTip.at.width, catTip.at.height] : null, text: catTipText.text })
        }
        function catHold(which: string, x: real, y: real): string {
            JD.catFrom = which === "tray" ? trayCat : peekView.cat
            JD.catHand = Qt.point(x, y)
            return JSON.stringify({ overTray: JD.catOverTray })
        }
        function catDrop(): string { JD.catDrop(); return JD.catPlace }
        // Spotlight без клавиш: открыть или закрыть и сказать, где карточка и что в ней. Рывок
        // при закрытии ловится серией таких ответов в первые полсекунды.
        // Что островок знает о чужом плеере — сырыми числами MPRIS, без нашего оформления.
        function player(): string {
            const p = JD.musicPlayer
            const st = p ? JD.playerStream(p) : null
            return JSON.stringify(p ? { identity: p.identity, dbus: p.dbusName, title: p.trackTitle, clean: JD.cleanTitle(p.trackTitle),
                                        art: p.trackArtUrl, length: p.length, position: p.position, canSeek: p.canSeek,
                                        volume: p.volume, volumeSupported: p.volumeSupported, stream: st ? st.name : null } : null)
        }
        function spotlight(on: bool): void { if (on) JD.openSearch(); else JD.closeMenu() }
        function menuState(): string {
            return JSON.stringify({ open: JD.menuOpen, search: JD.menuSearchMode, alive: menuWin.alive,
                                    body: menuWin.bodyKind,
                                    card: [menuWin.card.x, menuWin.card.y, menuWin.card.width, menuWin.card.height, menuWin.card.opacity.toFixed(2)] })
        }
        // Проверка движка увеличения без мыши: ставим курсор в заданную точку полосы, даём физике
        // сойтись и отдаём получившуюся раскладку. Синтетическая мышь на вейланде врёт (ускорение
        // и вторые мониторы), а «значки расступаются» иначе никак не проверить числом.
        function dockAt(x: real): string {
            const d = dockVariants.instances.length ? dockVariants.instances[0].probe(x) : null
            return JSON.stringify(d)
        }
        // Перетаскивание значка без мыши: чей порядок вышел и не наехали ли ячейки друг на друга.
        function dockWheel(from: real, to: real, steps: int): string {
            return dockVariants.instances.length ? dockVariants.instances[0].wheelWalk(from, to, steps) : "null"
        }
        function dockDrag(n: int, x: real): string {
            return dockVariants.instances.length ? dockVariants.instances[0].dragProbe(n, x) : "null"
        }
        // То же, но значок остаётся в руке: между этими двумя вызовами можно снять картинку и
        // увидеть док ровно таким, каким его видит человек посреди перетаскивания.
        function dockHold(n: int, x: real): string {
            return dockVariants.instances.length ? dockVariants.instances[0].dragHold(n, x) : "null"
        }
        function dockWalk(n: int, from: real, to: real, steps: int): string {
            return dockVariants.instances.length ? dockVariants.instances[0].dragWalk(n, from, to, steps) : "null"
        }
        function dockRelease(): string {
            return dockVariants.instances.length ? dockVariants.instances[0].dragRelease() : "null"
        }
        function dockShot(path: string): string {
            return dockVariants.instances.length ? dockVariants.instances[0].shot(path) : "null"
        }
        // Что док видит: открытые окна, закреплённое и точка, из которой вырастает меню.
        // `qs -p island ipc call island dock` — этим и проверяется, что окно узнали.
        function dock(): string {
            return JSON.stringify({ windows: JD.windows.map(w => ({ app: w.app, min: w.minimized, on: w.active })),
                                    pinned: JD.dockItems.map(i => i.key), anchor: JD.dockAnchor,
                                    known: Object.keys(JD.dockMatch).length,
                                    hover: JD.dockHover,
                                    menu: [menuWin.x, menuWin.y, menuWin.width, menuWin.height],
                                    card: [menuWin.card.x, menuWin.card.y, menuWin.card.width, menuWin.card.height],
                                    dockRect: JD.dockRect, trayRect: JD.trayRect,
                                    dockWin: dockVariants.instances.length ? dockVariants.instances[0].geom() : null,
                                    trayWin: trayLoader.item ? trayLoader.item.geom() : null })
        }
        // Меню лотка без мыши: открыть меню значка под номером и сказать, что в нём получилось.
        // Правая кнопка на вейланде синтетически не воспроизводится, а «меню не открывается» —
        // именно то, что здесь уже один раз сломалось молча.
        // Увеличение в лотке без мыши — та же проверка, что и у дока.
        function trayAt(y: real): string {
            return JSON.stringify(trayLoader.item ? trayLoader.item.probeAt(y) : null)
        }
        function trayOpen(n: int): string {
            const items = SystemTray.items.values.filter(i => !!i && JD.trayShows(i))
            const it = items[Math.max(0, Math.min(items.length - 1, n))]
            if (!it) return JSON.stringify({ items: items.length })
            // Attach beside the nth icon using trayRect (screen-local), not hardcoded 60,400.
            // Use x/y even while autohidden — live only means the strip is currently shown.
            const tr = JD.trayRect || ({})
            const extras = (JD.trayCfg.layout !== false && !!JD.layoutShort) ? 1 : 0
            const cell = JD.trayIconSize + 14
            const idx = Math.max(0, Math.min(items.length - 1, n)) + extras
            const baseY = (tr.y !== undefined ? tr.y : Math.round((JD.screenHeight - (tr.h || 0)) / 2))
            const baseX = (tr.x !== undefined ? tr.x : (JD.trayPlace === "right" ? JD.screenWidth - 48 : 10))
            const baseW = tr.w !== undefined ? tr.w : 38
            const ay = baseY + 8 + idx * cell + cell / 2
            const ax = JD.trayPlace === "right" ? baseX : baseX + baseW + 8
            JD.openTrayMenu(it, Math.round(ax), Math.round(ay))
            return JSON.stringify({ items: items.length, id: it.id, title: it.title, hasMenu: it.hasMenu,
                                    at: [Math.round(ax), Math.round(ay)] })
        }
        // Что в открытом меню видно: имена пунктов, галочки и подменю.
        function trayRows(): string { return trayMenuWin.menu.report() }
        function traySub(n: int): string { return trayMenuWin.menu.poke(n) }
        function trayClose(): void { JD.closeTrayMenu() }
        // Карточка под правым краем полосы без мыши ("" закрывает, tray — скрытые значки, bt, net) и
        // что на полосе: сколько значков на виду и сколько ушло под шеврон.
        function barPage(page: string): string {
            barStatus.page = page
            return JSON.stringify({ page: barStatus.page, shown: barStatus.trayCount, hidden: barStatus.trayHiddenCount })
        }
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

    NotifToastWindow {}

    ChatWindow {}

    OsdWindow {}

    PanelWindow {
        id: barFence
        readonly property bool live: JD.island.enabled !== false
            && JD.islandStyle === "bar"
            && island.mode !== "hidden"
            && !JD.barFullscreen
        screen: Quickshell.screens.find(s => s.name === (JD.island.screen || Quickshell.env("JUSTDAY_ISLAND_SCREEN")))
                || Quickshell.screens.find(s => s.x === 0 && s.y === 0) || Quickshell.screens[0]
        visible: live
        anchors { top: true; left: true; right: true }
        exclusionMode: live ? ExclusionMode.Normal : ExclusionMode.Ignore
        exclusiveZone: live ? Math.round(JD.barHeight) : 0
        WlrLayershell.layer: WlrLayer.Bottom
        WlrLayershell.namespace: "justday-bar-fence"
        WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
        color: "transparent"
        implicitHeight: Math.max(1, Math.round(JD.barHeight))
        mask: Region {}
    }

    // ───────────── window ─────────────
    PanelWindow {
        id: win
        screen: Quickshell.screens.find(s => s.name === (JD.island.screen || Quickshell.env("JUSTDAY_ISLAND_SCREEN")))
                || Quickshell.screens.find(s => s.x === 0 && s.y === 0) || Quickshell.screens[0]
        // Окно во всю ширину и прижато к тому краю, где живёт остров: край задаёт и точку отсчёта,
        // и сторону роста — сверху карточка разворачивается вниз, снизу вверх, сама собой.
        anchors { left: true; right: true; top: JD.atTop; bottom: !JD.atTop }
        // Ноль, не «как получится»: иначе слой садится ниже края, и между полосой и монитором щель.
        // У сплошной полосы окно чуть вылезает за край экрана: эффект скругления окон
        // срезает угол поверхности, и чёрный угол монитора остаётся обоями.
        readonly property int barBleed: JD.islandStyle === "bar" ? 18 : 0
        margins.top: -barBleed
        margins.left: -barBleed
        margins.right: -barBleed
        exclusionMode: ExclusionMode.Ignore
        // Ноль явно: иначе слой высотой в карточку сам занимает верх экрана.
        exclusiveZone: 0
        visible: JD.island.enabled !== false
        WlrLayershell.layer: JD.island.above === false ? WlrLayer.Top : WlrLayer.Overlay
        WlrLayershell.namespace: "justday-island"
        readonly property bool big: ["expanded", "settings", "compose", "player", "tools"].includes(island.mode)
        // Мышь перехватывается на весь экран только там, где это нужно для закрытия щелчком мимо:
        // меню, настройки, поле ввода. Плеер и видео живут поверх окон, не отнимая ни панель, ни рабочий стол.
        readonly property bool modal: ["expanded", "settings", "compose", "tools"].includes(island.mode)
        Binding { target: JD; property: "screenWidth"; value: win.screen ? win.screen.width : 1920 }
        Binding { target: JD; property: "screenHeight"; value: win.screen ? win.screen.height : 1080 }
        // the text field takes the keyboard at once (it was opened by a shortcut); menus only on click
        // Панель инструментов берёт клавиатуру целиком, и эмодзи тоже. Раньше эмодзи «не забирали» её, чтобы
        // окно под панелью осталось в фокусе, как у Win+. на Windows, — но тогда ни стрелки, ни Enter, ни
        // ввод в поиск до панели не доходили (Shortcut без фокуса не срабатывает). Фокус окну, где печатали,
        // возвращает демон перед вставкой (Daemon._focus_back).
        // Страницы инструментов без ввода (микшер, планы, нагрузка, claude) не берут клавиатуру сами: окно
        // под ними оставалось без фокуса, хотя печатать в панели было нечего. Щелчок по панели даёт фокус.
        readonly property bool toolsTyping: ["emoji", "clip", "history", "qr"].includes(JD.toolsPage)
        WlrLayershell.keyboardFocus: island.mode === "compose" || (island.mode === "tools" && toolsTyping) || (island.mode === "player" && JD.playerPage === "library") ? WlrKeyboardFocus.Exclusive
                                   : island.mode === "settings" || island.mode === "tools" ? WlrKeyboardFocus.OnDemand : WlrKeyboardFocus.None
        // Р2-31: плеер, видео и expanded клавиатуру не берут. Раньше у них стоял OnDemand, и щелчок по
        // громкости в игре отдавал островку клавиатуру — игра переставала слышать клавиши. Поля ввода
        // есть только в настройках (OnDemand), в compose и в инструментах (Exclusive).
        // окно шире самого острова: видео растягивают почти во весь экран, а щелчки всё равно
        // проходят везде, кроме него самого — маска ниже отвечает за это
        // Сплошная полоса — это строка на всю ширину монитора, а не окно по ширине видео.
        implicitWidth: JD.islandStyle === "bar"
                       ? Math.max(win.screen ? win.screen.width : JD.screenWidth, 1000)
                       : Math.max(1000, Math.min(JD.screenWidth, JD.videoWidth + 80))
        implicitHeight: Math.min(JD.screenHeight, 880 + (JD.islandStyle === "island" ? JD.topMargin : 0))
        color: "transparent"

        // Вырез и островок прячутся сами. Полоса — только если это включено.
        // Зона наведения должна быть в маске, иначе курсор до неё не доходит.
        readonly property bool edgeReveal: JD.island.hover_reveal !== false
            && (JD.islandStyle === "notch" || JD.islandStyle === "island"
                || (JD.islandStyle === "bar" && JD.barAutohide))
        // Клики и броски проходят сквозь окно везде, кроме видимого островка.
        // Пока он спрятан, полоска наведения — только его ширина, не весь край:
        // иначе курсор над пустой полосой запрещает бросить значок на стол.
        // Сплошная полоса по-прежнему занимает всю ширину. Развёрнутое меню берёт весь фон.
        mask: Region {
            item: win.modal ? backdrop
                : (win.edgeReveal && island.mode === "hidden") ? revealPad
                : island
            Region { item: barStatus.page === "tray" ? trayPop : barStatus.page !== "" ? linkPop : null }
        }

        MouseArea {
            id: backdrop
            anchors.fill: parent
            enabled: win.modal
            onClicked: JD.closeAll()
        }

        // Одна и та же зона: спрятанный вырез — полоска у края, открытый — сам вырез.
        // Геометрия меняется под курсором, поэтому вход не теряется на первом наведении
        // и уход действительно гасит peeking. Кнопки не берём: нажатия идут островку.
        MouseArea {
            id: revealPad
            z: 3
            enabled: win.edgeReveal && !win.modal
            hoverEnabled: true
            acceptedButtons: Qt.NoButton
            preventStealing: false
            readonly property bool parked: island.mode === "hidden"
            // Пока полоска только что выросла под курсором, это не новое наведение.
            property bool suppressEnter: false
            // Сплошная полоса ловит весь край. Островок и вырез — только свою ширину,
            // по центру или у своего бока. Остальной верхний край остаётся рабочим столом.
            readonly property bool wideEdge: JD.islandStyle === "bar"
            readonly property real restW: Math.max(80, peekView.implicitWidth)
            x: !parked ? island.x
             : wideEdge ? 0
             : JD.side === "left" ? JD.sideMargin
             : JD.side === "right" ? parent.width - restW - JD.sideMargin
             : (parent.width - restW) / 2
            y: parked ? (JD.atTop ? win.barBleed : parent.height - win.barBleed - 10)
                      : (JD.atTop ? Math.min(win.barBleed, island.y) : island.y)
            width: parked ? (wideEdge ? parent.width : restW) : Math.max(1, island.width)
            height: parked ? 10
                           : Math.max(1, JD.atTop ? island.y + island.height - Math.min(win.barBleed, island.y) : island.height)
            onParkedChanged: if (parked) { suppressEnter = true; suppressTimer.restart() }
            Timer { id: suppressTimer; interval: 180; onTriggered: revealPad.suppressEnter = false }
            onContainsMouseChanged: {
                if (!revealPad.enabled) return
                if (containsMouse) {
                    if (suppressEnter) return
                    JD.islandHovered = true
                    JD.revealFromEdge()
                } else {
                    suppressEnter = false
                    JD.islandHovered = false
                    JD.kickIslandHide()
                }
            }
            onPositionChanged: {
                const p = mapToItem(null, mouseX, mouseY)
                JD.pointerX = p.x
                JD.pointerY = p.y
                if (!revealPad.enabled || !containsMouse || !parked || suppressEnter) return
                JD.revealFromEdge()
            }
            onEnabledChanged: {
                if (!enabled) return
                if (containsMouse && !suppressEnter) {
                    JD.islandHovered = true
                    JD.revealFromEdge()
                } else if (!containsMouse) {
                    JD.islandHovered = false
                    JD.kickIslandHide()
                }
            }
        }
        // Если сигнал ухода потерялся, зона всё равно скажет правду.
        Timer {
            interval: 200
            repeat: true
            running: win.edgeReveal && JD.peeking && !win.modal
            onTriggered: {
                if (JD.revealLock) return
                if (revealPad.containsMouse) { JD.holdIsland(); return }
                if (JD.islandHovered) JD.islandHovered = false
                else JD.scheduleIslandHide()
            }
        }

        Shortcut { sequence: "Escape"; enabled: win.big; onActivated: JD.closeAll() }
        Shortcut { sequence: "Escape"; enabled: island.mode === "video"; onActivated: videoView.close() }

        // Клавиши плеера — те, что ждёшь от плеера. Работают, когда по нему щёлкнули:
        // остров просит клавиатуру «по требованию» и не отбирает её у других окон.
        readonly property bool playing: ["player", "video"].includes(island.mode)
        readonly property bool onVideo: island.mode === "video"
        Shortcut { sequences: ["Space", "K"]; enabled: win.playing
                   onActivated: win.onVideo ? videoView.toggle() : JD.media("toggle") }
        Shortcut { sequence: "Right"; enabled: win.playing
                   onActivated: win.onVideo ? videoView.seekBy(5000) : JD.media("seek", JD.playerPos(Date.now()) + 10) }
        Shortcut { sequence: "Left"; enabled: win.playing
                   onActivated: win.onVideo ? videoView.seekBy(-5000) : JD.media("seek", Math.max(0, JD.playerPos(Date.now()) - 10)) }
        Shortcut { sequence: "Up"; enabled: win.playing
                   onActivated: win.onVideo ? JD.setVideoVolume(JD.videoVolume + 0.05) : JD.media("volume", Math.min(100, (JD.player ? JD.player.volume || 0 : 0) + 5)) }
        Shortcut { sequence: "Down"; enabled: win.playing
                   onActivated: win.onVideo ? JD.setVideoVolume(JD.videoVolume - 0.05) : JD.media("volume", Math.max(0, (JD.player ? JD.player.volume || 0 : 0) - 5)) }
        Shortcut { sequence: "M"; enabled: win.playing
                   onActivated: win.onVideo ? JD.setVideoVolume(JD.videoVolume > 0 ? 0 : 1)
                                            : JD.media("volume", (JD.player && JD.player.volume > 0) ? 0 : 70) }
        Shortcut { sequence: "N"; enabled: island.mode === "player"; onActivated: JD.media("next") }
        Shortcut { sequence: "P"; enabled: island.mode === "player"; onActivated: JD.media("prev") }
        Shortcut { sequence: "F"; enabled: win.onVideo
                   onActivated: JD.videoBig ? videoView.grow(videoView.smallWidth) : videoView.grow(JD.videoRoom) }

        // Одно раскрытие для полосы, выреза и островка.
        // x и y не анимируются: иначе левый край и ширина едут врозь.
        component DropAnim: NumberAnimation {
            duration: JD.slideMs
            easing.type: JD.slideEase
        }

        // ───────────── the island ─────────────
        Rectangle {
            id: island
            z: 1
            readonly property string mode: JD.mode
            readonly property Item content: ({
                expanded: expandedView, settings: settingsHolder, compose: composeView, approval: approvalView, card: cardView, listening: listeningView,
                notification: notificationView, alarm: alarmView, flash: flashView, answer: answerView, transcribing: thinkingView, thinking: thinkingView,
                peek: peekView, hidden: peekView, music: musicView, player: playerView, video: videoView,
                videopill: videoPillView, tools: toolsHolder })[mode]
            readonly property bool compact: ["listening", "flash", "transcribing", "thinking", "peek", "hidden", "music", "videopill"].includes(mode) && !JD.detailOpen

            // Полоса остаётся полосой на всю ширину. Карточка живёт отдельным слоем под ней.
            readonly property bool barHang: JD.islandStyle === "bar" && (mode === "settings" || mode === "expanded" || mode === "tools")
            readonly property bool menuBar: JD.islandStyle === "bar" && (mode === "peek" || mode === "hidden")
            readonly property bool barDock: menuBar || barHang
            width: barDock ? Math.max(1, parent.width - win.barBleed * 2)
                 : mode === "hidden" ? 0
                 : Math.max(120, content.implicitWidth)
            height: mode === "hidden" ? 0
                  : barDock ? JD.barHeight
                  : content.implicitHeight
            // Скругление считается от живой высоты каждый кадр: пока карточка растёт, она остаётся пилюлей
            property real pill: compact ? 1 : 0
            Behavior on pill { enabled: JD.animOn; DropAnim {} }
            // Вырез скруглён только снизу. Полоса прямая со всех сторон. Капсула как была.
            readonly property real soft: Math.min(height / 2, pill * height / 2 + (1 - pill) * (mode === "settings" ? 34 : 30))
            // Вырез: radius 0, иначе общий radius скругляет и верх, и между монитором и вырезом щель.
            readonly property bool squareTop: barDock || JD.islandStyle === "notch"
            radius: squareTop ? 0 : soft
            topLeftRadius: squareTop ? 0 : soft
            topRightRadius: squareTop ? 0 : soft
            bottomLeftRadius: barDock ? 0 : soft
            bottomRightRadius: barDock ? 0 : soft
            antialiasing: true
            x: barDock ? win.barBleed
             : JD.side === "left" ? JD.sideMargin
             : JD.side === "right" ? parent.width - width - JD.sideMargin
             : (parent.width - width) / 2
            // Вырез прижат к краю. Полоса сдвинута на barBleed: верх окна за экраном.
            // Островок опускается на свой отступ — его задают в «Верхняя панель».
            y: !JD.atTop ? parent.height - height
               : JD.islandStyle === "island" ? JD.topMargin
               : win.barBleed
            opacity: mode === "hidden" ? 0 : 1
            scale: 1
            color: JD.ink
            clip: true
            border.width: JD.islandStyle === "bar" || JD.islandStyle === "notch" ? 0 : 1
            border.color: Qt.rgba(1, 1, 1, win.big ? 0.10 : 0.06)

            Rectangle {
                visible: JD.islandStyle === "bar" && island.mode === "peek"
                anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
                height: 1
                color: Qt.rgba(1, 1, 1, 0.14)
            }
            MouseArea {
                anchors.fill: parent
                enabled: island.barHang
                z: -1
                onClicked: {}
            }

            // Высота и ширина — один DropAnim. x и y без анимации, чтобы не было проезда вбок и щели сверху.
            // У полосы высота меняется только когда она прячется от полноэкранного окна.
            // Иначе Behavior доигрывает до половины и оставляет панель настроек внутри полосы.
            readonly property bool barMove: JD.islandStyle === "bar" && (mode === "hidden" || JD.barFullscreen || JD.armedQuick)
            Behavior on width { enabled: JD.animOn && !JD.videoResizing && !island.barDock; DropAnim {} }
            Behavior on height {
                enabled: JD.animOn && !JD.videoResizing && (JD.islandStyle !== "bar" || island.barMove)
                NumberAnimation { duration: island.barMove ? 80 : JD.slideMs; easing.type: island.barMove ? Easing.OutCubic : JD.slideEase }
            }
            Behavior on opacity {
                enabled: JD.animOn
                NumberAnimation { duration: island.barMove ? 80 : JD.slideMs; easing.type: island.barMove ? Easing.OutCubic : JD.slideEase }
            }

            HoverHandler {
                enabled: !win.edgeReveal
                onHoveredChanged: {
                    if (win.edgeReveal) return
                    JD.islandHovered = hovered
                    if (!hovered) { JD.pointerX = -99999; JD.pointerY = -99999 }
                }
                // Где курсор — нужно существу: оно провожает его глазами. На вейланде чужого
                // указателя не видно вовсе, положение дают только над своим окном, — и этого
                // хватает: пока человек рядом с островком, глаза следят, а ушёл — гуляют сами.
                onPointChanged: {
                    JD.pointerX = point.scenePosition.x
                    JD.pointerY = point.scenePosition.y
                }
            }

            // бросьте на остров файл или ссылку — они заиграют прямо здесь
            DropArea {
                id: dropZone
                anchors.fill: parent
                z: 50
                // Поднесённый файл раскрывает остров сам: в тонкой капсуле «отпустите» не прочитать и не попасть.
                onContainsDragChanged: { JD.islandHovered = containsDrag; if (!containsDrag) JD.scheduleIslandHide() }
                onDropped: drop => {
                    let target = ""
                    if (drop.hasUrls && drop.urls.length) target = drop.urls[0].toString()
                    else if (drop.hasText) target = (drop.text || "").trim().split(/\s+/)[0]
                    if (target.startsWith("file://")) target = decodeURIComponent(target.slice(7))
                    if (!target) return
                    JD.videoDrop(target)
                    drop.accept(Qt.CopyAction)
                }
            }
            Rectangle {
                anchors.fill: parent
                z: 49
                visible: dropZone.containsDrag
                radius: island.radius
                color: Qt.rgba(JD.accentPink.r, JD.accentPink.g, JD.accentPink.b, 0.18)
                border.width: 2
                border.color: JD.accentPink
                Label1 {
                    anchors.centerIn: parent
                    text: JD.tr("Отпустите — включу здесь")
                    visible: island.height > 60
                }
            }

            TapHandler {
                // На полосе повторное нажатие по островку закрывает раскрытую карточку.
                // На капсуле карточка и есть островок, поэтому там нажатие по-прежнему не гасит её.
                enabled: (JD.islandStyle === "bar" && ["expanded", "settings", "tools"].includes(island.mode))
                         || !["expanded", "settings", "approval", "card", "compose", "player", "video", "notification", "alarm"].includes(island.mode)
                onTapped: {
                    if (statusHover.hovered) return
                    barStatus.page = ""
                    peekView.bump()
                    if (JD.islandStyle === "bar" && (island.mode === "expanded" || island.mode === "settings" || island.mode === "tools")) {
                        JD.closeAll()
                        return
                    }
                    if (island.mode === "music") { JD.playerOpen = true; return }
                    if (island.mode === "videopill") { JD.videoMini = false; return }   // кадр обратно на экран
                    if (island.mode === "answer") { JD.answerOpen = false; return }
                    JD.expanded = true
                }
            }
            TapHandler {
                // Двойное нажатие по островку — выход из любого вида, как Escape, но мышью:
                // у видео двойное нажатие уже «в окно», его не трогаем.
                enabled: island.mode !== "video" && island.mode !== "listening"
                onDoubleTapped: { JD.answerOpen = false; JD.closeAll() }
            }
            // Every view is laid out at its own natural size; the island springs to it and the view follows.
            Item {
                id: stage
                anchors.fill: parent
                clip: true
                layer.enabled: false
                PeekView { id: peekView; shown: island.mode === "peek" || island.barHang }
                MusicView { id: musicView; shown: island.mode === "music" }
                PlayerView { id: playerView; shown: island.mode === "player" }
                VideoView { id: videoView; shown: island.mode === "video" }
                VideoPillView { id: videoPillView; shown: island.mode === "videopill"; onCloseRequested: videoView.close() }
                ListeningView { id: listeningView; shown: island.mode === "listening" }
                ThinkingView { id: thinkingView; shown: island.mode === "thinking" || island.mode === "transcribing" }
                FlashView { id: flashView; shown: island.mode === "flash" }
                NotificationView { id: notificationView; shown: island.mode === "notification" }
                AlarmView { id: alarmView; shown: island.mode === "alarm" }
                AnswerView { id: answerView; shown: island.mode === "answer" }
                ApprovalView { id: approvalView; shown: island.mode === "approval" }
                CardView { id: cardView; shown: island.mode === "card" }
                ExpandedView {
                    id: expandedView
                    // На полосе карточка — постоянный родитель. Возвращать содержимое в полосу
                    // в конце анимации нельзя: крестик и верх панели остаются внутри неё.
                    shown: JD.islandStyle === "bar"
                           ? (dropCard.want === "expanded" || dropCard.held === "expanded")
                           : (island.mode === "expanded" || dropCard.held === "expanded")
                    parent: JD.islandStyle === "bar" ? dropCard : stage
                }
                ComposeView { id: composeView; shown: island.mode === "compose" }
                View {
                    id: settingsHolder
                    shown: JD.islandStyle === "bar"
                           ? (dropCard.want === "settings" || dropCard.held === "settings")
                           : (island.mode === "settings" || dropCard.held === "settings")
                    parent: JD.islandStyle === "bar" ? dropCard : stage
                    implicitWidth: 940
                    // На низком экране или при масштабе 125% 640 не влезает: карточка не выше экрана.
                    implicitHeight: Math.min(640, JD.screenHeight - 2 * (JD.topMargin + 20))
                    Loader {
                        anchors.fill: parent
                        active: settingsHolder.shown || settingsHolder.opacity > 0.01
                        sourceComponent: SettingsView {}
                    }
                }
                // Панель инструментов: эмодзи, буфер обмена, нагрузка. Грузится по открытию —
                // сетка на 1900 клеток не должна лежать в памяти, пока её не просили.
                View {
                    id: toolsHolder
                    shown: JD.islandStyle === "bar"
                           ? (dropCard.want === "tools" || dropCard.held === "tools")
                           : island.mode === "tools"
                    parent: JD.islandStyle === "bar" ? dropCard : stage
                    implicitWidth: 860
                    implicitHeight: 560
                    Loader {
                        anchors.fill: parent
                        active: toolsHolder.shown || toolsHolder.opacity > 0.01
                        sourceComponent: ToolsView {}
                    }
                }
            }
            // Справа налево: сеть, Bluetooth, язык. Нажатие сюда не раскрывает островок.
            Item {
                id: barStatus
                property string page: ""
                readonly property bool showLang: JD.barLang && JD.layoutShort !== ""
                readonly property bool showBt: JD.barBt
                readonly property bool showNet: JD.barNet
                // Весь список трея, а не отфильтрованный: Repeater над свежим массивом пересобирал бы все
                // значки при каждом событии (barTray.js). Лишние прячутся через visible.
                readonly property int trayMax: Math.max(2, Math.min(16, (JD.island.bar_tray_max || 8)))
                function trayShown(it) { return JD.trayShows(it) && it.status !== Status.Passive }
                function inBar(it) { return BarTray.inBar(SystemTray.items.values, it, trayShown, trayMax) }
                readonly property int trayHiddenCount: BarTray.overflow(SystemTray.items.values, trayShown, trayMax)
                readonly property int trayCount: SystemTray.items.values.filter(i => !!i && inBar(i)).length
                visible: island.barDock && (showLang || showBt || showNet || trayCount > 0 || trayHiddenCount > 0)
                z: 4
                anchors { right: parent.right; verticalCenter: parent.verticalCenter; rightMargin: 10 }
                width: statusRow.implicitWidth + 12
                height: parent.height
                HoverHandler { id: statusHover }
                Row {
                    id: statusRow
                    anchors.centerIn: parent
                    spacing: 4
                    // Пришёл новый значок — вырастает на месте, соседи отъезжают, а не прыгают.
                    add: Transition {
                        enabled: JD.animOn
                        NumberAnimation { property: "scale"; from: 0.4; to: 1; duration: JD.durBase; easing.type: Easing.OutBack }
                        NumberAnimation { property: "opacity"; from: 0; to: 1; duration: JD.durFast }
                    }
                    move: Transition {
                        enabled: JD.animOn
                        NumberAnimation { property: "x"; duration: JD.durBase; easing.type: Easing.OutCubic }
                    }
                    // Кошку сюда переносят с середины полосы и уносят обратно (CatCarry).
                    Item {
                        visible: JD.island.cat === true && JD.catPlace === "tray"
                        implicitWidth: trayCat.implicitWidth + 10
                        implicitHeight: JD.barTraySize + 10
                        DockCat {
                            id: trayCat
                            anchors.centerIn: parent
                            size: JD.barTraySize
                            cpu: JD.cpu
                            awake: true
                            sleepBelow: JD.dockCfg.cat_sleep_below || 0
                            opacity: JD.catFrom === trayCat ? 0.3 : 1
                            scale: trayCatTap.pressed ? JD.pressScaleSmall : trayCatHover.hovered ? 1.15 : 1
                            Behavior on scale { enabled: JD.animOn; NumberAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
                            HoverHandler { id: trayCatHover; cursorShape: Qt.PointingHandCursor
                                           onHoveredChanged: JD.catTipAt = hovered ? trayCat : (JD.catTipAt === trayCat ? null : JD.catTipAt) }
                            TapHandler { id: trayCatTap; onTapped: JD.openTools("load") }
                            CatCarry { cat: trayCat }
                        }
                    }
                    // Шеврон: скрытые, пассивные и не влезшие значки живут в карточке под ним.
                    Rectangle {
                        visible: barStatus.trayHiddenCount > 0
                        implicitWidth: 24; implicitHeight: 26; radius: 13
                        color: barStatus.page === "tray" || chevHit.containsMouse ? JD.fill2 : "transparent"
                        Icon {
                            anchors.centerIn: parent
                            name: "chevron-down"
                            implicitSize: 14
                            opacity: 0.9
                            rotation: barStatus.page === "tray" ? 180 : 0
                            Behavior on rotation { enabled: JD.animOn; NumberAnimation { duration: JD.durBase; easing.type: JD.easeOut } }
                        }
                        MouseArea {
                            id: chevHit
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: barStatus.page = barStatus.page === "tray" ? "" : "tray"
                        }
                    }
                    Repeater {
                        model: SystemTray.items
                        delegate: BarTrayIcon {
                            visible: barStatus.inBar(modelData)
                        }
                    }
                    Rectangle {
                        visible: barStatus.trayCount > 0 && (barStatus.showLang || barStatus.showBt || barStatus.showNet)
                        implicitWidth: 1
                        implicitHeight: 16
                        color: JD.fill2
                    }
                    Rectangle {
                        visible: barStatus.showLang
                        implicitWidth: langText.implicitWidth + 16
                        implicitHeight: 26
                        radius: 13
                        color: langHit.containsMouse ? JD.fill2 : "transparent"
                        Text {
                            id: langText
                            anchors.centerIn: parent
                            text: JD.layoutShort
                            color: JD.text1
                            font.family: JD.fontFamily
                            font.pixelSize: 13
                            font.weight: Font.Bold
                        }
                        MouseArea {
                            id: langHit
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: JD.layoutNext()
                        }
                    }
                    Rectangle {
                        visible: barStatus.showBt
                        implicitWidth: 28; implicitHeight: 26; radius: 13
                        color: barStatus.page === "bt" || btHit.containsMouse ? JD.fill2 : "transparent"
                        Icon { anchors.centerIn: parent; name: "bluetooth"; implicitSize: 16; opacity: JD.btOn ? 0.95 : 0.35 }
                        MouseArea {
                            id: btHit
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: barStatus.page = barStatus.page === "bt" ? "" : "bt"
                        }
                    }
                    Rectangle {
                        visible: barStatus.showNet
                        implicitWidth: JD.vpnOn ? 42 : 28
                        implicitHeight: 26
                        radius: 13
                        color: barStatus.page === "net" || netHit.containsMouse ? JD.fill2 : "transparent"
                        Row {
                            anchors.centerIn: parent
                            spacing: 3
                            Icon { name: JD.netOn ? "wifi" : "wifi-off"; implicitSize: 16; opacity: JD.netOn ? 0.95 : 0.4 }
                            Icon { visible: JD.vpnOn; name: "shield"; implicitSize: 12; opacity: 0.95 }
                        }
                        MouseArea {
                            id: netHit
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: barStatus.page = barStatus.page === "net" ? "" : "net"
                        }
                    }
                }
            }
        }

        // Кошка в руке и место, куда она ляжет. Над треем он подсвечивается; везде, кроме него,
        // отпущенная кошка возвращается к часам.
        Binding {
            target: JD; property: "catOverTray"; when: JD.catFrom !== null
            value: {
                const p = barStatus.mapFromItem(null, JD.catHand.x, JD.catHand.y)
                return p.x > -24 && p.x < barStatus.width + 24 && p.y > -24 && p.y < barStatus.height + 24
            }
        }
        Rectangle {
            visible: JD.catFrom !== null && JD.catOverTray
            z: 6
            readonly property point p: barStatus.mapToItem(parent, 0, 0)
            x: p.x - 4; y: p.y + 4
            width: barStatus.width + 8; height: barStatus.height - 8
            radius: height / 2
            color: Qt.rgba(1, 1, 1, 0.06)
            border.width: 1
            border.color: Qt.rgba(1, 1, 1, 0.22)
        }
        DockCat {
            id: catGhost
            visible: JD.catFrom !== null
            z: 7
            size: 22
            cpu: JD.cpu
            awake: true
            scale: 1.15
            readonly property point p: parent.mapFromItem(null, JD.catHand.x, JD.catHand.y)
            x: p.x - width / 2
            y: p.y - height / 2
        }

        // Наведи на кошку — увидишь проценты. Раньше число было только в карточке нагрузки, а
        // кошка сообщала одно «быстро бежит»: сколько именно и не память ли это — не узнать.
        Rectangle {
            id: catTip
            property Item at: null
            z: 7
            visible: opacity > 0.01
            opacity: at !== null && JD.catFrom === null ? 1 : 0
            Behavior on opacity { enabled: JD.animOn; NumberAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
            width: catTipText.implicitWidth + 22
            height: 28
            radius: 14
            color: JD.ink
            border.width: 1
            border.color: Qt.rgba(1, 1, 1, 0.08)
            // Ставится, когда подсказка появляется: полоса под рукой ещё 180 мс подрастает,
            // и место, посчитанное сразу, съехало бы на эти несколько точек.
            function place() {
                if (!at) return
                const p = at.mapToItem(parent, at.width / 2, 0)
                const edge = island.mapToItem(parent, 0, JD.atTop ? island.height : 0).y   // под полосой, а не на ней
                x = Math.max(8, Math.min(parent.width - width - 8, p.x - width / 2))
                y = JD.atTop ? edge + 8 : edge - height - 8
            }
            Timer { id: catTipDelay; interval: 350; onTriggered: { catTip.at = JD.catTipAt; catTip.place() } }
            Connections {
                target: JD
                function onCatTipAtChanged() {
                    if (JD.catTipAt) catTipDelay.restart()
                    else { catTipDelay.stop(); catTip.at = null }
                }
            }
            Text {
                id: catTipText
                anchors.centerIn: parent
                text: JD.tr("Процессор ") + Math.round(JD.cpu) + " %  ·  " + JD.tr("Память ") + Math.round(JD.mem) + " %"
                color: JD.text1
                font.family: JD.fontFamily
                font.pixelSize: 12
                font.weight: Font.DemiBold
                font.features: { "tnum": 1 }
            }
        }

        // Скрытые значки трея: то, что убрано из полосы, но не выброшено.
        Rectangle {
            id: trayPop
            visible: barStatus.page === "tray"
            z: 6
            width: Math.min(280, trayFlow.implicitWidth + 24)
            height: trayFlow.implicitHeight + 24
            radius: 18
            color: JD.ink
            border.width: 1
            border.color: Qt.rgba(1, 1, 1, 0.08)
            x: {
                const p = barStatus.mapToItem(trayPop.parent, 0, 0)
                return Math.max(8, Math.min(parent.width - width - 8, p.x + barStatus.width - width))
            }
            y: {
                const p = barStatus.mapToItem(trayPop.parent, 0, 0)
                return p.y + barStatus.height + 8
            }
            Flow {
                id: trayFlow
                x: 12
                y: 12
                width: 256
                spacing: 4
                Repeater {
                    model: SystemTray.items
                    delegate: BarTrayIcon {
                        visible: !barStatus.inBar(modelData)
                        onUsed: barStatus.page = ""
                    }
                }
            }
        }

        // Короткая карточка сети или Bluetooth под правым краем полосы.
        Rectangle {
            id: linkPop
            visible: barStatus.page === "bt" || barStatus.page === "net"
            z: 6
            width: 280
            height: linkCol.implicitHeight + 28
            radius: 18
            color: JD.ink
            border.width: 1
            border.color: Qt.rgba(1, 1, 1, 0.08)
            x: {
                const p = barStatus.mapToItem(linkPop.parent, 0, 0)
                return Math.max(8, Math.min(parent.width - width - 8, p.x + barStatus.width - width))
            }
            y: {
                const p = barStatus.mapToItem(linkPop.parent, 0, 0)
                return p.y + barStatus.height + 8
            }
            Column {
                id: linkCol
                x: 16
                y: 14
                width: parent.width - 32
                spacing: 8
                Text {
                    text: barStatus.page === "bt" ? "Bluetooth" : JD.tr("Сеть")
                    color: JD.text1
                    font.family: JD.fontFamily
                    font.pixelSize: 15
                    font.weight: Font.Bold
                }
                Text {
                    width: parent.width
                    wrapMode: Text.WordWrap
                    color: JD.text2
                    font.family: JD.fontFamily
                    font.pixelSize: 13
                    text: barStatus.page === "bt"
                          ? (JD.btOn ? JD.tr("Включён") : JD.tr("Выключен"))
                          : (JD.netOn
                             ? (JD.netKind === "wifi" ? "Wi-Fi" : JD.tr("Кабель")) + (JD.netName ? " · " + JD.netName : "")
                             : JD.tr("Нет соединения"))
                }
                Text {
                    visible: barStatus.page === "net"
                    width: parent.width
                    wrapMode: Text.WordWrap
                    color: JD.vpnOn ? JD.accentGreen : JD.text3
                    font.family: JD.fontFamily
                    font.pixelSize: 13
                    text: JD.vpnOn ? "VPN · " + JD.vpnName : JD.tr("VPN не подключён")
                }
                Rectangle {
                    width: parent.width
                    implicitHeight: 32
                    radius: 10
                    color: setHit.containsMouse ? JD.fill2 : JD.fill1
                    Text {
                        anchors.centerIn: parent
                        text: JD.tr("Открыть настройки KDE")
                        color: JD.accentBlue
                        font.family: JD.fontFamily
                        font.pixelSize: 13
                        font.weight: Font.DemiBold
                    }
                    MouseArea {
                        id: setHit
                        anchors.fill: parent
                        hoverEnabled: true
                        cursorShape: Qt.PointingHandCursor
                        onClicked: {
                            JD.systemSettings(barStatus.page === "bt" ? "kcm_bluetooth" : "kcm_networkmanagement")
                            barStatus.page = ""
                        }
                    }
                }
            }
        }

        // Карточка сплошной полосы раскрывается вниз из-под часов. Высота — тот же DropAnim.
        Rectangle {
            id: dropCard
            objectName: "dropCard"
            property string want: JD.islandStyle === "bar" && island.mode === "settings" ? "settings"
                                 : JD.islandStyle === "bar" && island.mode === "expanded" ? "expanded"
                                 : JD.islandStyle === "bar" && island.mode === "tools" ? "tools"
                                 : ""
            property string held: ""
            onWantChanged: if (want !== "") held = want
            z: 2
            // Нельзя гасить visible: пока элемент скрыт, DropAnim на высоте перескакивает в конец.
            visible: JD.islandStyle === "bar"
            color: JD.ink
            // Стык с полосой прямой. Скругление только снизу, иначе у квадратной полосы ступенька.
            radius: 0
            topLeftRadius: 0
            topRightRadius: 0
            bottomLeftRadius: 32
            bottomRightRadius: 32
            antialiasing: true
            clip: true
            x: Math.round((parent.width - width) / 2)
            // На 3 точки под полосу: антиалиас верхнего края не рисует шов.
            y: JD.atTop ? win.barBleed + JD.barHeight - 3
                        : parent.height - win.barBleed - JD.barHeight + 3 - height
            readonly property real growTo: {
                if (!island.barHang) return 0
                const item = (want === "settings" || held === "settings") ? settingsHolder
                           : (want === "tools" || held === "tools") ? toolsHolder
                           : (want === "expanded" || held === "expanded") ? expandedView : null
                return Math.max(1, item ? item.implicitHeight : 1)
            }
            readonly property real wideTo: {
                const item = (want === "settings" || held === "settings") ? settingsHolder
                           : (want === "tools" || held === "tools") ? toolsHolder
                           : (want === "expanded" || held === "expanded") ? expandedView : null
                return Math.max(120, item ? item.implicitWidth : 120)
            }
            // Пишем в grow/wide, не в height: у height Qt обходит Behavior, и карточка вспыхивает целиком.
            // Смена настроек и виджетов на той же карточке — тот же DropAnim, не скачок.
            property real grow: 0
            property real wide: 120
            height: grow
            width: wide
            Behavior on grow { enabled: JD.animOn; DropAnim {} }
            Behavior on wide { enabled: JD.animOn; DropAnim {} }
            onGrowToChanged: grow = growTo
            onWideToChanged: wide = wideTo
            onGrowChanged: if (want === "" && grow < 1) held = ""
            MouseArea {
                anchors.fill: parent
                z: -1
                onClicked: {}
                // Двойное нажатие по пустому месту карточки — выход, как Escape: на полосе карточка
                // не внутри острова, и его обработчик двойного нажатия сюда не дотягивался.
                onDoubleClicked: { JD.answerOpen = false; JD.closeAll() }
            }
        }

        // No MultiEffect shadow — enabling it at ease end caused the hitch you see.
        // Soft plate under island is enough without a post-animation GPU effect.
        Rectangle {
            anchors.fill: island
            anchors.margins: -2
            z: -1
            radius: island.radius + 2
            color: Qt.rgba(0, 0, 0, 0.35)
            scale: island.scale
            opacity: island.opacity * 0.5
            visible: island.mode !== "hidden" && !island.barDock
        }
    }

    // Папка на рабочем столе слушает только панель Plasma, не exclusive zone слоя.
    // Тонкая прозрачная панель той же высоты сдвигает значки. Прячется полоса — панель снимается.
    Item {
        id: barStrut
        // Нет полосы — нет панели. Иначе значки рабочего стола остаются под пустой полосой.
        readonly property bool live: false
        readonly property int h: Math.round(JD.barHeight)
        readonly property int sx: win.screen ? win.screen.x : 0
        readonly property int sy: win.screen ? win.screen.y : 0
        property double ticket: 0
        function schedule() { ticket = Date.now(); strutTimer.restart() }
        // Стиль ушёл с полосы — панель Plasma удаляется сразу, не прячется.
        // Таймер «on» от прошлой полосы при этом гасится, иначе он создаёт панель заново.
        function pushOff() {
            strutTimer.stop()
            ticket = Date.now()
            Quickshell.execDetached(["python3", Quickshell.shellDir + "/bar_strut.py",
                                     "off", String(h), String(sx), String(sy), String(ticket)])
        }
        // Только смена стиля со сплошной полосы. Островок и вырез панель не создают.
        function drop() {
            strutTimer.stop()
            ticket = Date.now()
            Quickshell.execDetached(["python3", Quickshell.shellDir + "/bar_strut.py",
                                     "drop", String(h), String(sx), String(sy), String(ticket)])
        }
        function push() {
            Quickshell.execDetached(["python3", Quickshell.shellDir + "/bar_strut.py",
                                     (JD.islandStyle === "bar" && live) ? "on" : "off",
                                     String(h), String(sx), String(sy), String(ticket)])
        }
        Timer { id: strutTimer; interval: 60; onTriggered: barStrut.push() }
        onLiveChanged: schedule()
        onHChanged: if (JD.islandStyle === "bar") schedule()
        onSxChanged: schedule()
        onSyChanged: schedule()
        Connections {
            target: JD
            function onIslandStyleChanged() {
                if (JD.islandStyle !== "bar") barStrut.drop()
                else barStrut.schedule()
            }
        }
        Component.onCompleted: {
            if (JD.islandStyle !== "bar") pushOff()
            else schedule()
        }
    }

    DockWindows { id: dockVariants; primaryScreen: win.screen }

    TrayWindows { id: trayLoader; primaryScreen: win.screen }

    GenieWindow { screen: win.screen }

    TrayMenuWindow { id: trayMenuWin; screen: win.screen }

    AppMenuWindow { id: menuWin; screen: win.screen }

}
