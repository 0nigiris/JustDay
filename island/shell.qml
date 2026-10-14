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
                                    body: menuBody.sourceComponent === spotlightBody ? "spotlight" : "menu",
                                    card: [menuCard.x, menuCard.y, menuCard.width, menuCard.height, menuCard.opacity.toFixed(2)] })
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
                                    card: [menuCard.x, menuCard.y, menuCard.width, menuCard.height],
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
        function trayRows(): string { return trayMenu.report() }
        function traySub(n: int): string { return trayMenu.poke(n) }
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
                // Пока остров держит клавиатуру целиком, клавиши не доходят до окон под ним — об этом надо
                // сказать глазами, иначе «пропали клавиши» выглядит как поломка.
                // Посередине верхнего края, тихим серым: оранжевая капсула справа сверху садилась на крестик
                // инструментов и стрелку плеера («иконка клавы выглядит хуёво»). Верхняя полоса в 16 px
                // свободна у всех трёх видов, которые держат клавиатуру (инструменты, compose, медиатека).
                Icon {
                    id: kbGrab
                    readonly property bool held: win.WlrLayershell.keyboardFocus === WlrKeyboardFocus.Exclusive
                    parent: JD.islandStyle === "bar" && island.mode === "tools" ? dropCard : stage
                    anchors { top: parent.top; horizontalCenter: parent.horizontalCenter; topMargin: 3 }
                    name: "keyboard"; implicitSize: 11; tint: JD.text3
                    z: 50
                    opacity: held ? 1 : 0
                    visible: opacity > 0
                    Behavior on opacity { enabled: JD.animOn; NumberAnimation { duration: JD.durFast } }
                }
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

    // ───────────── dock ─────────────
    //
    // THREE layers (KWin maximize/border magnet follows PanelWindow geometry):
    //   1) paint — full-screen, ExclusionMode.Ignore, exclusiveZone 0. Holds DockView so
    //      hover/magnify/tips are not clipped. Never advertises a strut / magnet. NO blur.
    //   2) fence — thin PanelWindow matching the visible card outline only. Exclusive /
    //      magnet when reserve is on; Ignore otherwise. Click-through (empty mask).
    //   3) blur — card-sized PanelWindow only. BackgroundEffect must NOT sit on paint.
    // One primary screen reports dockRect / dockAnchor to JD (menus punch a hole there).
    Variants {
        id: dockVariants
        model: {
            if (!JD.dockOn) return []
            if ((JD.dockCfg.screens || "primary") !== "all") return win.screen ? [win.screen] : []
            return Quickshell.screens
        }
        delegate: Item {
            id: dockHost
            required property var modelData

            readonly property bool primary: !modelData || !win.screen || modelData === win.screen
            readonly property bool atTop: JD.dockPlace === "top"
            readonly property real edgeMargin: 8

            function probe(x) { return dockWin.probe(x) }
            function dragProbe(n, x) { return dockWin.dragProbe(n, x) }
            function dragHold(n, x) { return dockWin.dragHold(n, x) }
            function dragWalk(n, a, b, k) { return dockWin.dragWalk(n, a, b, k) }
            function dragRelease() { return dockWin.dragRelease() }
            function shot(path) { return dockWin.shot(path) }
            function wheelWalk(a, b, n) { return dockWin.wheelWalk(a, b, n) }
            function geom() { return dockWin.geom() }

            // ── paint layer: full-screen, no magnet ──
            PanelWindow {
                id: dockWin
                screen: modelData
                anchors { top: true; bottom: true; left: true; right: true }
                exclusionMode: ExclusionMode.Ignore
                exclusiveZone: 0
                WlrLayershell.layer: WlrLayer.Top
                WlrLayershell.namespace: "justday-dock"
                WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
                color: "transparent"

                readonly property real stripPx: dock.cardHeight + dockHost.edgeMargin
                // Overlap (window bites the island) or true-fullscreen → hide; edge still summons.
                readonly property bool overlapRaw: JD.dockCoveredOn(modelData, stripPx, dockHost.atTop, dock.x, dock.width)
                readonly property bool reserveLive: JD.dockCfg.reserve === true && !dockReveal.needHide

                EdgeReveal {
                    id: dockReveal
                    autohide: JD.dockCfg.autohide === true
                    overlapRaw: dockWin.overlapRaw
                    // Stay up while pointer is on dock / tip / ctx / launcher menu.
                    keepVisible: JD.menuOpen || dock.dockUiActive
                    edge: dockHost.atTop ? "top" : "bottom"
                    edgeOnly: true
                    hideDelay: 1400
                    revealZone: Math.max(2, Math.min(200, JD.dockCfg.reveal_zone === undefined ? 28 : JD.dockCfg.reveal_zone))
                    flickSpeed: Math.max(0, JD.dockCfg.reveal_flick === undefined ? 900 : JD.dockCfg.reveal_flick)
                }
                readonly property bool shown: dockReveal.shown

                // Clicks pass everywhere except the card, tip, ctx menu, and the edge summon strip.
                mask: Region {
                    item: dockWin.shown ? dock : edge
                    Region { item: dockWin.shown ? dock.hotItem : null }
                    Region { item: dockWin.shown && dock.tipShown ? dock.tipItem : null }
                    Region { item: dock.ctxEntry ? dockCtxZone : null }
                }

                Item {
                    id: edge
                    // Только под самим доком (с запасом): раньше любой участок нижнего края звал его.
                    x: Math.max(0, dock.x - 40)
                    width: Math.min(parent.width - x, dock.width + 80)
                    height: dockReveal.revealZone
                    y: dockHost.atTop ? 0 : parent.height - height
                    HoverHandler {
                        id: edgeWatch
                        onPointChanged: if (dockReveal.needHide) dockReveal.onEdgePoint(point, edge.height)
                    }
                    DropArea {
                        anchors.fill: parent
                        onEntered: if (dockReveal.needHide) dockReveal.onEdgeEntered()
                    }
                }
                Item {
                    id: dockCtxZone
                    width: dock.width
                    height: dock.height + 220
                    x: dock.x
                    TapHandler {
                        acceptedButtons: Qt.LeftButton | Qt.RightButton
                        gesturePolicy: TapHandler.ReleaseWithinBounds
                        onTapped: dock.closeCtx()
                    }
                    y: dockHost.atTop ? dock.y : dock.y - 220
                }
                HoverHandler {
                    id: dockBodyHover
                    onHoveredChanged: dockReveal.onBodyHover(hovered)
                }
                // Та же правда ещё и связкой. Событие onHoveredChanged можно не получить —
                // курсор ушёл в чужое окно, поверхность пересоздалась, маска поменялась, — и
                // тогда полоса считает, что рука всё ещё на ней, и не прячется до перезапуска.
                Binding { target: dockReveal; property: "bodyHovered"; value: dockBodyHover.hovered }

                Binding {
                    target: JD
                    property: "dockHover"
                    value: [Math.round(dock.pointerScene), dock.engaged ? 1 : 0, dock.focused ? dock.focused.t : "",
                            Math.round(dock.laneLength), Math.round(dock.restLength)]
                }
                Binding {
                    target: JD
                    when: dockHost.primary
                    property: "dockAnchor"
                    value: ({ x: dock.x + dock.launcherCenter,
                              gap: dock.cardHeight + dockHost.edgeMargin,
                              top: dockHost.atTop, shown: dockWin.shown })
                }
                Binding {
                    target: JD
                    when: dockHost.primary
                    property: "dockRect"
                    value: ({ x: dock.x, w: dock.width, h: dock.cardHeight,
                              y: dockHost.atTop ? dockHost.edgeMargin
                                               : JD.screenHeight - dock.cardHeight - dockHost.edgeMargin,
                              live: dockWin.shown })
                }

                function probe(x) { return dock.probe(x) }
                function dragProbe(n, x) { return dock.dragProbe(n, x) }
                function dragHold(n, x) { return dock.dragHold(n, x) }
                function dragWalk(n, a, b, k) { return dock.dragWalk(n, a, b, k) }
                function dragRelease() { return dock.dragRelease() }
                function shot(path) { return dock.shot(path) }
                function wheelWalk(a, b, n) { return dock.wheelWalk(a, b, n) }
                function geom() {
                    return ({ paint: { w: Math.round(width), h: Math.round(height) },
                              fence: { w: Math.round(dockFence.width), h: Math.round(dockFence.height),
                                       iw: Math.round(dockFence.implicitWidth),
                                       ih: Math.round(dockFence.implicitHeight),
                                       ml: Math.round(dockFence.margins.left),
                                       excl: dockFence.exclusiveZone,
                                       mode: dockWin.reserveLive ? "normal" : "ignore" },
                              card: Math.round(dock.cardHeight), rest: Math.round(dock.restLength),
                              head: Math.round(dock.headroom), dx: Math.round(dock.x), dy: Math.round(dock.y),
                              dw: Math.round(dock.width), dh: Math.round(dock.height) })
                }

                DockView {
                    id: dock
                    awake: dockWin.shown
                    edgeRoom: dockHost.edgeMargin
                    // Full-screen paint: centre is screen midpoint.
                    anchorCentre: parent.width / 2
                    x: Math.max(0, Math.round((parent.width - width) / 2))
                    // DockView = card + headroom. Card sits on the screen edge inside it
                    // (top: card at y=0 of view; bottom: card at bottom of view).
                    y: {
                        const rest = dockHost.atTop
                            ? dockHost.edgeMargin
                            : parent.height - height - dockHost.edgeMargin
                        // Уезжать надо на всю высоту вида, а не на высоту карточки: над карточкой
                        // живёт запас под увеличение, и значок под курсором в него поднимается.
                        // Если вести рукой вверх медленно, док прятался на высоту карточки — и
                        // поднятый значок вместе с подписью продолжал выглядывать из-за края.
                        const away = dockHost.atTop ? -(height + 20) : height + 20
                        return rest + (dockWin.shown ? 0 : away)
                    }
                    opacity: 1
                    Behavior on y { enabled: JD.animOn
                                    NumberAnimation { duration: dockReveal.slideMs; easing.type: Easing.OutCubic } }
                }
            }

            // ── fence layer: visible card outline only — magnet / exclusive ──
            PanelWindow {
                id: dockFence
                screen: modelData
                // One edge only — never left+right (would be a full-width bottom fence on 4K/8K).
                anchors {
                    top: dockHost.atTop
                    bottom: !dockHost.atTop
                }
                exclusionMode: dockWin.reserveLive ? ExclusionMode.Normal : ExclusionMode.Ignore
                exclusiveZone: dockWin.reserveLive ? Math.round(dockWin.stripPx) : 0
                WlrLayershell.layer: WlrLayer.Bottom
                WlrLayershell.namespace: "justday-dock-fence"
                WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
                color: "transparent"
                // Calm card outline (+ edge margin baked into stripPx height). Not magExtra/headroom.
                implicitWidth: Math.max(160, Math.round(dock.restLength))
                implicitHeight: Math.round(dockWin.stripPx)
                margins.left: Math.max(0, Math.round(((screen ? screen.width : JD.screenWidth) - implicitWidth) / 2))
                // Click-through — paint layer owns input.
                mask: Region {}
                // Invisible; only exists so KWin magnet / exclusive match the real card, not paint headroom.
                visible: JD.dockOn
            }

            // ── размытие: только полоса под карточкой, никогда не полноэкранный слой ──
            // Если повесить BackgroundEffect на полноэкранное окно рисования, KWin размоет
            // всю поверхность. Поэтому это отдельная узкая полоса, и её размер НЕ едет за пружиной:
            // именно изменение размера layer-shell каждый кадр дёргало док.
            // blurRegion уже внутри полосы повторяет живую карточку.
            PanelWindow {
                id: dockBlur
                screen: modelData
                anchors {
                    top: dockHost.atTop
                    bottom: !dockHost.atTop
                }
                exclusionMode: ExclusionMode.Ignore
                exclusiveZone: 0
                WlrLayershell.layer: WlrLayer.Bottom
                WlrLayershell.namespace: "justday-dock-blur"
                WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
                color: "transparent"
                readonly property real screenW: screen ? screen.width : JD.screenWidth
                readonly property real screenH: screen ? screen.height : JD.screenHeight
                readonly property real cardX: dock.x + dock.blurItem.x
                readonly property real cardY: dock.y + dock.blurItem.y
                readonly property real cardW: Math.max(1, dock.blurItem.width)
                readonly property real cardH: Math.max(1, dock.blurItem.height)
                readonly property real capW: Math.min(Math.max(160, screenW - 32), Math.max(160, Math.round(dock.restLength + dock.magExtra * 2 + 48)))
                readonly property real bandH: Math.max(1, Math.round(dock.cardHeight + dockHost.edgeMargin))
                readonly property real winLeft: Math.max(0, Math.round((screenW - capW) / 2))
                readonly property real winTop: dockHost.atTop ? 0 : Math.max(0, screenH - bandH)
                readonly property bool onScreen: cardX + cardW > 1 && cardX < screenW - 1 && cardY + cardH > 1 && cardY < screenH - 1
                visible: JD.dockOn && JD.blurOn && dockWin.shown && onScreen
                implicitWidth: capW
                implicitHeight: bandH
                margins.left: winLeft
                margins.top: 0
                margins.bottom: 0
                mask: Region {}
                BackgroundEffect.blurRegion: Region {
                    x: Math.round(dockBlur.cardX - dockBlur.winLeft)
                    y: Math.round(dockBlur.cardY - dockBlur.winTop)
                    width: Math.round(dockBlur.cardW)
                    height: Math.round(dockBlur.cardH)
                    radius: Math.round(dock.blurItem.radius)
                }
            }
        }
    }

    // ───────────── tray ─────────────
    //
    // Same THREE-layer split as the dock (KWin magnet follows PanelWindow geometry):
    //   1) paint — full-screen, ExclusionMode.Ignore, exclusiveZone 0. Holds TrayView so
    //      hover/magnify/hints/menus are not clipped. Never advertises a strut / magnet. NO blur.
    //   2) fence — thin PanelWindow matching the visible strip outline only. Exclusive /
    //      magnet when reserve is on; Ignore otherwise. Click-through (empty mask).
    //   3) blur — strip-sized PanelWindow only. BackgroundEffect must NOT sit on paint.
    Loader {
        id: trayLoader
        active: JD.trayOn && JD.trayDesktop
        sourceComponent: Item {
            id: trayHost
            function probeAt(at) { return trayWin.probeAt(at) }
            function geom() { return trayWin.geom() }

            readonly property bool atRight: JD.trayPlace === "right"
            readonly property string align: JD.trayCfg.align || "center"
            readonly property real edgeMargin: 10

            // Align strip along the edge (center / start / end), shared by paint + fence.
            function stripTop(stripH, screenH) {
                const topPad = JD.atTop ? JD.topMargin + 60 : 20
                if (align === "start") return topPad
                if (align === "end") return Math.max(0, Math.round(screenH - stripH - 20))
                return Math.max(0, Math.round((screenH - stripH) / 2))
            }

            // ── paint layer: full-screen, no magnet ──
            PanelWindow {
                id: trayWin
                function probeAt(at) { return tray.probe(at) }
                function geom() {
                    return ({ paint: { w: Math.round(width), h: Math.round(height) },
                              fence: { w: Math.round(trayFence.width), h: Math.round(trayFence.height),
                                       iw: Math.round(trayFence.implicitWidth),
                                       ih: Math.round(trayFence.implicitHeight),
                                       mt: Math.round(trayFence.margins.top),
                                       excl: trayFence.exclusiveZone,
                                       mode: trayWin.reserveLive ? "normal" : "ignore" },
                              tw: Math.round(tray.width), th: Math.round(tray.height),
                              tx: Math.round(tray.x), ty: Math.round(tray.y),
                              restW: Math.round(tray.restWidth), restL: Math.round(tray.restLength) })
                }
                screen: win.screen
                readonly property bool atRight: trayHost.atRight
                readonly property string align: trayHost.align
                visible: !tray.empty
                anchors { top: true; bottom: true; left: true; right: true }
                readonly property bool reserveLive: JD.trayCfg.reserve === true && !JD.trayAutohide && !tray.empty
                exclusionMode: ExclusionMode.Ignore
                exclusiveZone: 0
                WlrLayershell.layer: WlrLayer.Top
                WlrLayershell.namespace: "justday-tray"
                WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
                color: "transparent"

                EdgeReveal {
                    id: trayReveal
                    autohide: JD.trayAutohide
                    overlapRaw: false
                    // Stay up while the tray menu is open (same idea as dock keepVisible).
                    keepVisible: !!JD.trayMenu
                    edge: trayWin.atRight ? "right" : "left"
                    // Full-screen paint: only the edge strip summons — body hover must not
                    // reveal from anywhere on the screen (mask already limits input).
                    edgeOnly: true
                    hideDelay: 1800
                    revealZone: Math.max(2, Math.min(200, JD.trayCfg.reveal_zone === undefined ? 28 : JD.trayCfg.reveal_zone))
                    flickSpeed: Math.max(0, JD.trayCfg.reveal_flick === undefined ? 900 : JD.trayCfg.reveal_flick)
                }
                readonly property bool shown: trayReveal.shown

                Item {
                    id: trayEdge
                    width: trayReveal.revealZone
                    height: parent.height
                    x: trayWin.atRight ? parent.width - width : 0
                    HoverHandler {
                        onPointChanged: if (trayReveal.needHide) trayReveal.onEdgePoint(point, trayEdge.width)
                    }
                }
                HoverHandler {
                    id: trayBodyHover
                    onHoveredChanged: trayReveal.onBodyHover(hovered)
                }
                Binding { target: trayReveal; property: "bodyHovered"; value: trayBodyHover.hovered }

                // Clicks pass everywhere except the strip and the edge summon strip.
                mask: Region { item: trayWin.shown ? tray : trayEdge }

                // Rest footprint for trayRect / fence align (blur lives on trayBlur window).
                readonly property real trayRestX: trayWin.atRight
                    ? Math.round(width - tray.restWidth - trayHost.edgeMargin)
                    : trayHost.edgeMargin
                readonly property real trayRestY: {
                    const sh = height
                    return trayHost.stripTop(tray.restLength, sh)
                }

                Binding {
                    target: JD
                    property: "trayRect"
                    value: ({ x: trayWin.trayRestX,
                              y: trayWin.trayRestY,
                              w: tray.restWidth, h: tray.restLength,
                              live: trayWin.shown && !tray.empty })
                }

                TrayView {
                    id: tray
                    // Full-screen paint: scene Y is screen-local; middle of the live strip.
                    anchorMiddle: y + height / 2
                    x: {
                        const rest = trayWin.atRight
                            ? parent.width - width - trayHost.edgeMargin
                            : trayHost.edgeMargin
                        const away = trayWin.atRight ? width + 16 : -width - 16
                        return rest + (trayWin.shown ? 0 : away)
                    }
                    opacity: 1
                    Behavior on x { enabled: JD.animOn; NumberAnimation { duration: trayReveal.slideMs; easing.type: JD.easeOut } }
                    // Pin to restLength, then offset so magnify grows symmetrically.
                    // Do NOT Behavior-animate y: that lagged physics and made the strip jitter.
                    y: {
                        const sh = parent.height
                        const align = trayWin.align
                        const topPad = JD.atTop ? JD.topMargin + 60 : 20
                        const restH = tray.restLength
                        let base
                        if (align === "start") base = topPad
                        else if (align === "end") base = Math.max(0, Math.round(sh - restH - 20))
                        else base = Math.max(0, Math.round((sh - restH) / 2))
                        return base - Math.round((height - restH) / 2)
                    }
                }
            }

            // ── fence layer: visible strip outline only — magnet / exclusive ──
            PanelWindow {
                id: trayFence
                screen: win.screen
                visible: JD.trayOn && !tray.empty
                // One edge only — never top+bottom (would be a full-height left fence on 4K/8K).
                anchors {
                    left: !trayHost.atRight
                    right: trayHost.atRight
                }
                exclusionMode: trayWin.reserveLive ? ExclusionMode.Normal : ExclusionMode.Ignore
                exclusiveZone: trayWin.reserveLive ? Math.round(tray.restWidth + trayHost.edgeMargin) : 0
                WlrLayershell.layer: WlrLayer.Bottom
                WlrLayershell.namespace: "justday-tray-fence"
                WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
                color: "transparent"
                // Calm strip outline (+ edge margin). Not sideExtra/magExtra headroom.
                implicitWidth: Math.round(tray.restWidth + trayHost.edgeMargin)
                implicitHeight: Math.round(tray.restLength)
                margins.top: {
                    const sh = screen ? screen.height : JD.screenHeight
                    return trayHost.stripTop(implicitHeight, sh)
                }
                // Click-through — paint layer owns input.
                mask: Region {}
            }

            // ── blur layer: strip ONLY (never on full-screen paint) ──
            // Размер окна — это огибающая увеличения, а не живая пружина. Когда поверхность
            // layer-shell меняли каждый кадр, матовое пятно то обгоняло карточку, то отставало.
            // blurRegion — тот же прямоугольник, что и полоса, вместе с уездом при скрытии.
            PanelWindow {
                id: trayBlur
                screen: win.screen
                readonly property real screenW: screen ? screen.width : JD.screenWidth
                readonly property real screenH: screen ? screen.height : JD.screenHeight
                readonly property real stripX: tray.x + tray.blurItem.x
                readonly property real stripY: tray.y + tray.blurItem.y
                readonly property real stripW: Math.max(1, tray.blurItem.width)
                readonly property real stripH: Math.max(1, tray.blurItem.height)
                readonly property real capH: Math.min(screenH - 32, Math.max(tray.restLength, Math.round(tray.restLength + tray.magExtra * 2 + 8)))
                readonly property real winW: Math.max(1, Math.round(tray.restWidth + trayHost.edgeMargin + 4))
                readonly property real restTop: trayHost.stripTop(tray.restLength, screenH)
                readonly property real winTop: Math.max(0, Math.min(Math.max(0, screenH - capH), Math.round(restTop - (capH - tray.restLength) / 2)))
                readonly property real winLeft: trayHost.atRight ? screenW - winW : 0
                readonly property bool onScreen: stripX + stripW > 1 && stripX < screenW - 1 && stripY + stripH > 1 && stripY < screenH - 1
                visible: JD.trayOn && JD.blurOn && !tray.empty && trayWin.shown && onScreen
                anchors {
                    left: !trayHost.atRight
                    right: trayHost.atRight
                }
                exclusionMode: ExclusionMode.Ignore
                exclusiveZone: 0
                WlrLayershell.layer: WlrLayer.Bottom
                WlrLayershell.namespace: "justday-tray-blur"
                WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
                color: "transparent"
                implicitWidth: winW
                implicitHeight: Math.max(1, Math.round(capH))
                margins.top: winTop
                margins.left: 0
                margins.right: 0
                mask: Region {}
                BackgroundEffect.blurRegion: Region {
                    x: Math.round(trayBlur.stripX - trayBlur.winLeft)
                    y: Math.round(trayBlur.stripY - trayBlur.winTop)
                    width: Math.round(trayBlur.stripW)
                    height: Math.round(trayBlur.stripH)
                    radius: Math.round(tray.blurItem.radius)
                }
            }
        }
    }

    // ───────────── genie minimize overlay ─────────────
    // Scales a card from the window rect toward the dock icon, then the real window is
    // minimized underneath. Avoids depending on KWin iconGeometry (empty without Plasma panel).
    PanelWindow {
        id: genieWin
        visible: !!JD.genie
        screen: win.screen
        anchors { top: true; bottom: true; left: true; right: true }
        exclusionMode: ExclusionMode.Ignore
        exclusiveZone: 0
        WlrLayershell.layer: WlrLayer.Overlay
        WlrLayershell.namespace: "justday-genie"
        WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
        color: "transparent"
        mask: Region {}   // click-through

        property real t: 0
        onVisibleChanged: {
            if (visible) {
                t = 0
                genieAnim.restart()
            } else {
                t = 0
            }
        }
        NumberAnimation {
            id: genieAnim
            target: genieWin
            property: "t"
            from: 0; to: 1
            duration: JD.animOn ? 320 : 1
            easing.type: Easing.InCubic
            onFinished: JD.genie = null
        }

        readonly property var g: JD.genie
        readonly property real sx: g ? g.from.x + (g.to.x - g.from.x) * t : 0
        readonly property real sy: g ? g.from.y + (g.to.y - g.from.y) * t : 0
        readonly property real sw: g ? g.from.w + (g.to.w - g.from.w) * t : 0
        readonly property real sh: g ? g.from.h + (g.to.h - g.from.h) * t : 0

        Rectangle {
            visible: !!genieWin.g
            x: genieWin.sx - (win.screen ? win.screen.x : 0)
            y: genieWin.sy - (win.screen ? win.screen.y : 0)
            width: Math.max(8, genieWin.sw)
            height: Math.max(8, genieWin.sh)
            radius: Math.min(18, Math.min(width, height) * 0.18)
            color: Qt.rgba(0.08, 0.08, 0.1, 0.92 * (1 - genieWin.t * 0.35))
            border.width: 1
            border.color: Qt.rgba(1, 1, 1, 0.14 * (1 - genieWin.t))
            opacity: 1 - Math.pow(genieWin.t, 2.2)
            Icon {
                anchors.centerIn: parent
                theme: true
                name: genieWin.g ? (genieWin.g.icon || "") : ""
                implicitSize: Math.max(16, Math.min(parent.width, parent.height) * 0.42)
                opacity: 0.95
            }
        }
    }

    // ───────────── меню значка лотка ─────────────
    //
    // Своё окно во весь экран, а не часть полосы: меню обязано закрываться щелчком мимо, а «мимо» —
    // это весь остальной экран. Пункты приходят от самой программы (DBusMenu), рисуем их мы:
    // системное меню Quickshell показывает только в режиме QApplication, и раньше правая кнопка в
    // лотке молчала именно поэтому.
    PanelWindow {
        id: trayMenuWin
        readonly property bool open: !!JD.trayMenu
        visible: open
        screen: win.screen
        anchors { top: true; bottom: true; left: true; right: true }
        exclusionMode: ExclusionMode.Ignore
        exclusiveZone: 0
        WlrLayershell.layer: WlrLayer.Overlay
        WlrLayershell.namespace: "justday-traymenu"
        // Меню забирает клавиатуру, пока открыто: Escape должен его закрывать, как закрывает любое
        // меню, а без фокуса до нас не доходит ни одна клавиша.
        WlrLayershell.keyboardFocus: open ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None
        color: "transparent"

        MouseArea {
            id: trayMenuBackdrop
            anchors.fill: parent
            acceptedButtons: Qt.LeftButton | Qt.RightButton
            onClicked: JD.closeTrayMenu()
        }
        Shortcut { sequence: "Escape"; enabled: trayMenuWin.open; onActivated: JD.closeTrayMenu() }

        // Дырка по полосе лотка — та же, что у меню приложений. Без неё полоса под перекрытием
        // становится картинкой: значки видно, а единственное, что делает щелчок по ним, — закрывает
        // меню. А человек, открыв меню не того значка, щёлкает именно по соседнему.
        Item {
            id: trayMenuHole
            visible: false
            readonly property var r: JD.trayRect
            x: r && r.live ? r.x : 0
            y: r && r.live ? r.y : 0
            width: r && r.live ? r.w : 0
            height: r && r.live ? r.h : 0
        }
        mask: Region {
            item: trayMenuWin.open ? trayMenuBackdrop : null
            Region { item: trayMenuHole; intersection: Intersection.Subtract }
        }

        // Frosted glass under the menu card, same chrome as dock/tray (armed after open settle).
        property bool blurLive: false
        onOpenChanged: {
            if (open) {
                blurLive = false
                trayMenuBlurArm.restart()
            } else {
                trayMenuBlurArm.stop()
                blurLive = false
            }
        }
        Timer {
            id: trayMenuBlurArm
            interval: JD.dur(140) + 16
            onTriggered: trayMenuWin.blurLive = trayMenuWin.open
        }
        // По региону на каждую раскрытую карточку, а не один общий прямоугольник: подменю сдвинуто вбок
        // и вниз, и рамка вокруг всех карточек размывала пустой экран вокруг меню («блюр вылетел из экрана»).
        BackgroundEffect.blurRegion: Region {
            Region {
                x: Math.round(trayMenu.sheet0.cardX); y: Math.round(trayMenu.sheet0.cardY)
                width: trayMenuWin.blurLive && JD.blurOn && trayMenu.sheet0.visible ? Math.round(trayMenu.sheet0.cardW) : 0
                height: trayMenuWin.blurLive && JD.blurOn && trayMenu.sheet0.visible ? Math.round(trayMenu.sheet0.cardH) : 0
                radius: 14
            }
            Region {
                x: Math.round(trayMenu.sheet1.cardX); y: Math.round(trayMenu.sheet1.cardY)
                width: trayMenuWin.blurLive && JD.blurOn && trayMenu.sheet1.visible ? Math.round(trayMenu.sheet1.cardW) : 0
                height: trayMenuWin.blurLive && JD.blurOn && trayMenu.sheet1.visible ? Math.round(trayMenu.sheet1.cardH) : 0
                radius: 14
            }
            Region {
                x: Math.round(trayMenu.sheet2.cardX); y: Math.round(trayMenu.sheet2.cardY)
                width: trayMenuWin.blurLive && JD.blurOn && trayMenu.sheet2.visible ? Math.round(trayMenu.sheet2.cardW) : 0
                height: trayMenuWin.blurLive && JD.blurOn && trayMenu.sheet2.visible ? Math.round(trayMenu.sheet2.cardH) : 0
                radius: 14
            }
        }
        TrayMenu {
            id: trayMenu
            anchors.fill: parent
            handle: JD.trayMenu ? JD.trayMenu.menu : null
            atX: JD.trayMenuX
            atY: JD.trayMenuY
            toLeft: JD.trayMenuFromBar || JD.trayPlace === "right"
            onDismissed: JD.closeTrayMenu()
        }
    }

    // ───────────── меню приложений ─────────────
    //
    // Своё окно, а не страница острова. Меню открывается от своего угла экрана, живёт по своим
    // размерам и может быть открыто, пока остров показывает таймер или играет музыку. Общего у них —
    // цвета, значки, клавиши и демон.
    //
    // Слой перекрывает всё, но зону ищет обычную: exclusiveZone 0 при Normal значит «сам ничего не
    // отнимаю, но чужие полосы уважаю». Поэтому меню ложится в свободную часть экрана и не налезает
    // на панель KDE, пока та ещё на месте.
    PanelWindow {
        id: menuWin
        readonly property bool want: JD.menuOpen
        property bool alive: false
        // Окно гаснет не мгновенно: иначе исчезновение выглядит обрывом, а не закрытием.
        // Blur only when fully open (no rebuild during open/close slide).
        property bool blurLive: false
        visible: alive
        screen: win.screen
        anchors { top: true; bottom: true; left: true; right: true }
        exclusionMode: ExclusionMode.Normal
        exclusiveZone: 0
        WlrLayershell.layer: WlrLayer.Overlay
        WlrLayershell.namespace: "justday-menu"
        WlrLayershell.keyboardFocus: alive ? WlrKeyboardFocus.Exclusive : WlrKeyboardFocus.None
        color: "transparent"
        BackgroundEffect.blurRegion: Region {
            x: Math.round(menuCard.x)
            y: Math.round(menuCard.y)
            width: menuWin.blurLive && JD.blurOn ? Math.round(menuCard.width) : 0
            height: menuWin.blurLive && JD.blurOn ? Math.round(menuCard.height) : 0
            radius: Math.round(menuCard.radius)
        }
        onWantChanged: {
            if (want) {
                // Сначала окно, потом содержимое. Окно на весь экран с исключительной клавиатурой —
                // это и есть «курсор появился»: пока Loader собирал сетку в том же кадре, курсор ждал
                // её, и в полноэкранной игре Пуск казался зависшим. Теперь пустое окно рисуется первым,
                // а меню собирается кадром позже (запасной таймер — если кадр так и не придёт).
                // Порядок важен: пока contentOn остался от прошлого открытия, `alive = true` сразу
                // включил бы Loader.
                contentOn = false
                alive = true
                menuContentArm.restart()
                menuFadeOut.stop()
                blurLive = false
                menuBlurArm.restart()
            } else {
                menuContentArm.stop()
                menuFadeOut.restart()
                menuBlurArm.stop()
                blurLive = false
            }
        }
        property bool contentOn: false
        Connections {
            target: menuCard.Window.window
            enabled: menuWin.alive && !menuWin.contentOn
            function onFrameSwapped() { menuWin.contentOn = menuWin.want }
        }
        Timer { id: menuContentArm; interval: 100; onTriggered: menuWin.contentOn = menuWin.want }
        Timer { id: menuFadeOut; interval: JD.dur(JD.slideMs); onTriggered: menuWin.alive = false }
        Timer { id: menuBlurArm; interval: JD.dur(JD.slideMs) + 16; onTriggered: menuWin.blurLive = menuWin.want }

        // «dock» — меню вырастает из значка в доке и садится в него же. Иначе — свой угол экрана.
        // Нет дока — нет и значка: тогда меню ведёт себя как «снизу слева», а не исчезает.
        readonly property var anchor: JD.dockAnchor
        readonly property bool fromDock: (JD.island.menu_position || "dock") === "dock" && JD.dockOn && !!anchor
        readonly property string place: {
            const want = JD.island.menu_position || "dock"
            if (want !== "dock") return want
            return fromDock && anchor.top ? "top-left" : "bottom-left"
        }
        readonly property bool atTop: place.startsWith("top")
        readonly property string side: place.split("-")[1] || "left"

        // Перекрытие во весь экран — чтобы закрываться щелчком мимо. Но с дырками по доку и полосе
        // лотка: без них они под меню становятся картинкой — значки видно, а нажать нельзя, и
        // единственное, что делает щелчок по ним, это закрывает меню.
        MouseArea { id: menuBackdrop; anchors.fill: parent; onClicked: JD.closeMenu() }
        Shortcut { sequence: "Escape"; enabled: JD.menuOpen; onActivated: JD.closeMenu() }

        Item {
            id: dockHole
            visible: false
            readonly property var r: JD.dockRect
            x: r && r.live ? r.x : 0
            y: r && r.live ? r.y : 0
            width: r && r.live ? r.w : 0
            height: r && r.live ? r.h : 0
        }
        Item {
            id: trayHole
            visible: false
            readonly property var r: JD.trayRect
            x: r && r.live ? r.x : 0
            y: r && r.live ? r.y : 0
            width: r && r.live ? r.w : 0
            height: r && r.live ? r.h : 0
        }

        mask: Region {
            item: menuBackdrop
            Region { item: dockHole; intersection: Intersection.Subtract }
            Region { item: trayHole; intersection: Intersection.Subtract }
        }

        // Тень. Без неё карточка лежит на обоях, а не над ними, и никакая раскраска этого не
        // заменит: «поверх» глаз читает по тени, а не по цвету. Это готовая размытая картинка,
        // растянутая по размеру карточки (девять частей: углы не тянутся, середина тянется). Раньше тень
        // была `MultiEffect` с размытием по источнику, у которого высота идёт `SpringAnimation`:
        // текстура пересоздавалась и размывалась каждый кадр, на 165 Гц (Р-43). Картинка размером
        // не интересуется. Внутренняя «карточка» в ней отступает на 48 точек от края, поэтому и рамка шире на 48.
        BorderImage {
            source: Quickshell.shellDir + "/shadow.png"
            border { left: 64; top: 64; right: 64; bottom: 64 }
            x: menuCard.x - 48
            y: menuCard.y - 48 + 8
            width: menuCard.width + 96
            height: menuCard.height + 96
            opacity: (JD.menuOpen ? 0.5 : 0) * menuCard.opacity
            Behavior on opacity { enabled: JD.animOn; NumberAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
        }

        // Размер меню задаёт человек, углом карточки. Раньше его задавало содержимое — и лента
        // разделов уезжала после каждого нажатия: «Избранные» и «Все программы» дают карточки
        // разной высоты, а стоит она у нижнего края, и значит верх её каждый раз в новом месте.
        // Ради точного размера приходилось возить курсор через пол-экрана, и это плохая сделка.
        property real cardW: 760
        property real cardH: 620
        // Мерить по окну можно, только когда окно уже настоящего размера. Закрытое меню живёт в
        // окне сто на сто — layer shell схлопывает невидимое, — и «не больше окна» превращалось в
        // «не больше семидесяти шести»: карточка садилась на нижний предел. А если в этот миг её
        // размер сохранить, урезанным он и останется навсегда.
        function fitCard() {
            const roomW = (width > 200 ? width : JD.screenWidth) - 24
            const roomH = (height > 200 ? height : JD.screenHeight) - 24
            if (JD.menuSearchMode) {
                // Spotlight: поверхность ровно под поиск. Ширина постоянная, высота — по тому,
                // сколько нашлось: пустой поиск это одна строка ввода, а не пустое окно в пол-экрана.
                cardW = Math.max(520, Math.min(roomW, 720))
                const want = menuBody.item ? menuBody.item.implicitHeight : 86
                cardH = Math.max(86, Math.min(roomH, Math.min(760, want)))
            } else {
                cardW = Math.max(520, Math.min(roomW, JD.menuWidth))
                cardH = Math.max(360, Math.min(roomH, JD.menuHeight))
            }
        }
        // Пересчитывать надо и когда окно узнало свой размер. При запуске его ширина ещё ноль,
        // и «не больше экрана» превращается в «не больше минус двадцати четырёх»: карточка
        // защёлкивалась на наименьшем допустимом размере и такой и оставалась. Та же ошибка, что
        // была с отнятой зоной дока, и ловится она тем же — пересчётом на изменение размера окна.
        Component.onCompleted: fitCard()
        onWidthChanged: fitCard()
        onHeightChanged: fitCard()
        // Launchpad занимает всё, что не занято доком и полосой лотка: их они же и вырезают из
        // перекрытия для щелчков, и накрывать их картинкой нельзя — под карточкой они пропали бы из
        // виду, хотя нажимались бы. Каждая вырезка отодвигает карточку от того края, к которому
        // прижата.
        readonly property rect padRect: {
            let l = 12, t = 12, r = width - 12, b = height - 12
            for (const h of [dockHole, trayHole]) {
                if (h.width <= 0 || h.height <= 0) continue
                const gaps = [h.x, width - h.x - h.width, h.y, height - h.y - h.height]   // слева, справа, сверху, снизу
                const nearest = gaps.indexOf(Math.min(...gaps))
                if (nearest === 0) l = Math.max(l, h.x + h.width + 8)
                else if (nearest === 1) r = Math.min(r, h.x - 8)
                else if (nearest === 2) t = Math.max(t, h.y + h.height + 8)
                else b = Math.min(b, h.y - 8)
            }
            return Qt.rect(l, t, Math.max(0, r - l), Math.max(0, b - t))
        }

        Connections {
            target: JD
            function onMenuWidthChanged() { menuWin.fitCard() }
            function onMenuHeightChanged() { menuWin.fitCard() }
            function onMenuSearchModeChanged() { menuWin.fitCard() }
        }

        Rectangle {
            id: menuCard
            // Экран может быть и маленьким: меню обязано на нём поместиться целиком.
            // Spotlight меряет себя сам: его высота — это строка поиска плюс то, сколько нашлось.
            // Верх прибит, едет низ, и карточка не превращается в пустое окно на пол-экрана, когда
            // искать ещё нечего.
            readonly property real wantH: menuBody.item ? menuBody.item.implicitHeight : 86
            width: JD.menuSearchMode ? Math.min(menuWin.width - 48, 720)
                                     : JD.menuLaunchpad ? menuWin.padRect.width
                                     : Math.min(menuWin.width - 24, menuWin.cardW)
            height: JD.menuSearchMode
                    ? Math.min(menuWin.height - 48, Math.max(86, Math.min(760, wantH)))
                    : JD.menuLaunchpad ? menuWin.padRect.height
                    : Math.min(menuWin.height - 24, menuWin.cardH)
            Behavior on height {
                enabled: JD.animOn && JD.menuSearchMode
                SpringAnimation { spring: 5; damping: 0.62; epsilon: 0.5 }
            }
            // От значка: меню стоит над ним, но не левее края экрана и не правее его.
            // Spotlight — по центру сверху, как macOS Spotlight, а не из дока.
            x: JD.menuSearchMode
                 ? (menuWin.width - width) / 2
                 : JD.menuLaunchpad ? menuWin.padRect.x
                 : menuWin.fromDock
                 ? Math.max(12, Math.min(menuWin.width - width - 12, menuWin.anchor.x - 64))
                 : menuWin.side === "left" ? 12
                 : menuWin.side === "right" ? menuWin.width - width - 12
                 : (menuWin.width - width) / 2
            // Док, который отнимает место, уже сдвинул край этого окна — считать его высоту второй
            // раз значит отодвинуть меню от значка на его же толщину. Прячущийся док места не
            // отнимает, и тогда отступ нужен полный.
            // exclusiveZone=0 when reserve off OR dock hidden (overlap/autohide) → need full gap.
            readonly property real fromEdge: menuWin.fromDock && (JD.dockCfg.reserve !== true
                                             || JD.dockCfg.autohide === true
                                             || !(menuWin.anchor && menuWin.anchor.shown))
                                             ? menuWin.anchor.gap + 10 : 12
            y: JD.menuSearchMode
                 ? Math.min(96, Math.max(24, Math.round(menuWin.height * 0.08)))
                 : JD.menuLaunchpad ? menuWin.padRect.y
                 : menuWin.fromDock
                 ? (menuWin.atTop ? fromEdge : menuWin.height - height - fromEdge)
                 : (menuWin.atTop ? 12 : menuWin.height - height - 12)
            radius: JD.menuSearchMode ? 24 : JD.menuLaunchpad ? 30 : 22
            // Меню читают, а не рассматривают: карточка почти непрозрачная, и размытие под ней —
            // только чтобы её край не выглядел вырезанным из картона. Стекло на 74% выглядело
            // красиво ровно до первых светлых обоев, после которых половина кнопок пропадала.
            color: JD.blurOn ? JD.menuSurface : Qt.rgba(0.04, 0.04, 0.05, 0.99)
            border.width: 1
            border.color: Qt.rgba(1, 1, 1, 0.14)
            clip: true

            // Растёт от своего угла, а не из середины экрана: глаз уже там, где нажали.
            transformOrigin: JD.menuSearchMode ? Item.Top
                : JD.menuLaunchpad ? Item.Center
                : menuWin.atTop
                ? (menuWin.side === "left" ? Item.TopLeft : menuWin.side === "right" ? Item.TopRight : Item.Top)
                : (menuWin.side === "left" ? Item.BottomLeft : menuWin.side === "right" ? Item.BottomRight : Item.Bottom)
            opacity: JD.menuOpen ? 1 : 0
            scale: JD.menuOpen ? 1 : 0.94
            Behavior on opacity { enabled: JD.animOn; NumberAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
            Behavior on scale { enabled: JD.animOn; NumberAnimation { duration: JD.slideMs; easing.type: JD.slideEase } }

            // Щелчок по самой карточке её не закрывает — только мимо.
            MouseArea { id: menuCardBody; anchors.fill: parent; hoverEnabled: true }

            // ───────────── уголок ─────────────
            //
            // Тянут за тот угол, который свободен: карточка прижата к своему краю и к своему
            // значку, и растёт она от них. Тянуть за прижатый угол значило бы двигать саму
            // карточку, а она стоит там, откуда её открыли, и стоять обязана.
            Item {
                id: menuGrip
                visible: !JD.menuSearchMode && !JD.menuLaunchpad
                readonly property bool atLeft: menuWin.side === "right"
                readonly property bool atTop: !menuWin.atTop
                width: 26
                height: 26
                x: atLeft ? 0 : parent.width - width
                y: atTop ? 0 : parent.height - height

                Canvas {
                    anchors.fill: parent
                    anchors.margins: 5
                    opacity: gripHover.hovered ? 0.8 : menuCardBody.containsMouse ? 0.45 : 0.28
                    Behavior on opacity { enabled: JD.animOn; NumberAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
                    onPaint: {
                        const ctx = getContext("2d")
                        ctx.reset()
                        ctx.strokeStyle = "#ffffff"
                        ctx.lineWidth = 1.5
                        ctx.lineCap = "round"
                        const w = width, h = height
                        for (let i = 0; i < 2; i++) {
                            const d = 4 + i * 5
                            ctx.beginPath()
                            ctx.moveTo(menuGrip.atLeft ? d : w - d, menuGrip.atTop ? 0 : h)
                            ctx.lineTo(menuGrip.atLeft ? 0 : w, menuGrip.atTop ? d : h - d)
                            ctx.stroke()
                        }
                    }
                }

                HoverHandler {
                    id: gripHover
                    cursorShape: menuGrip.atLeft === menuGrip.atTop ? Qt.SizeFDiagCursor : Qt.SizeBDiagCursor
                }
                DragHandler {
                    target: null
                    property real fromW: 0
                    property real fromH: 0
                    property real fromX: 0
                    property real fromY: 0
                    onActiveChanged: {
                        if (active) {
                            fromW = menuWin.cardW
                            fromH = menuWin.cardH
                            fromX = centroid.scenePosition.x
                            fromY = centroid.scenePosition.y
                        } else {
                            JD.saveMenuSize(menuWin.cardW, menuWin.cardH)
                        }
                    }
                    onCentroidChanged: {
                        if (!active) return
                        const dx = centroid.scenePosition.x - fromX
                        const dy = centroid.scenePosition.y - fromY
                        menuWin.cardW = Math.max(520, Math.min(menuWin.width - 24,
                                                 fromW + (menuGrip.atLeft ? -dx : dx)))
                        menuWin.cardH = Math.max(360, Math.min(menuWin.height - 24,
                                                 fromH + (menuGrip.atTop ? -dy : dy)))
                    }
                }
            }

            // Живёт, только пока открыто: закрыли — освободили и сетку, и значки.
            Loader {
                id: menuBody
                anchors.fill: parent
                active: menuWin.alive && menuWin.contentOn
                sourceComponent: JD.menuSearchMode ? spotlightBody : menuBodyFull
            }
            Component { id: menuBodyFull; MenuView {} }
            Component { id: spotlightBody; SpotlightView {} }
        }
    }

}
