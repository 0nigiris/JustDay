// JustDay Dynamic Island — Quickshell (Qt Quick) layer-shell overlay.
// Talks to the daemon over $XDG_RUNTIME_DIR/justday.sock: `subscribe` for live status, one-shot commands back.
// Run: qs -p <repo>/island        (service: justday-island.service)
import QtQuick
import QtQuick.Controls
import QtQuick.Layouts
import QtQuick.Shapes
import QtQuick.Effects
import Quickshell
import Quickshell.Io
import Quickshell.Wayland
import Quickshell.Widgets
import Quickshell.Services.Mpris
import Quickshell.Services.Pipewire
import Quickshell.Services.SystemTray
import Quickshell.Services.Notifications
import QtMultimedia

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

    // ───────────── notification toast (Telegram-style corner on a chosen monitor) ─────────────
    // Independent of the island pill: Settings → Виджеты → monitor + corner. Default: secondary,
    // top-right. The island mode "notification" is suppressed while this window shows the toast.
    PanelWindow {
        id: notifWin
        property bool show: !!JD.notification && JD.island.show_notifications !== false
        visible: show
        screen: JD.resolveNotifScreen()
        readonly property string nplace: JD.notifPlace
        readonly property bool natTop: !nplace.startsWith("bottom")
        readonly property string nside: nplace.split("-")[1] || "center"
        anchors {
            left: true
            right: true
            top: natTop
            bottom: !natTop
        }
        exclusionMode: ExclusionMode.Ignore
        WlrLayershell.layer: WlrLayer.Overlay
        WlrLayershell.namespace: "justday-notification"
        WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
        color: "transparent"
        implicitHeight: Math.min(screen ? screen.height : 800, 280)
        mask: Region { item: notifIsland }

        Rectangle {
            id: notifIsland
            anchors.top: notifWin.natTop ? parent.top : undefined
            anchors.bottom: notifWin.natTop ? undefined : parent.bottom
            anchors.topMargin: notifWin.natTop ? JD.topMargin : 0
            anchors.bottomMargin: notifWin.natTop ? 0 : JD.topMargin
            x: notifWin.nside === "left" ? JD.sideMargin
             : notifWin.nside === "right" ? parent.width - width - JD.sideMargin
             : (parent.width - width) / 2
            width: Math.max(120, notifToast.implicitWidth)
            height: notifToast.implicitHeight
            radius: Math.min(height / 2, 30)
            color: JD.ink
            border.width: 1
            border.color: Qt.rgba(1, 1, 1, 0.06)
            clip: true
            NotificationView {
                id: notifToast
                shown: notifWin.show
            }
        }
    }


    // ───────────── system OSD (volume / layout / brightness) — Noctalia-like, not app toasts ─────────────
    // Own monitor + corner (island.osd_screen / osd_position). Telegram toasts stay on notification_*.
    PanelWindow {
        id: osdWin
        property bool show: JD.osdShow && JD.island.show_osd !== false
        visible: show
        screen: JD.resolveOsdScreen()
        readonly property string oplace: JD.osdPlace
        readonly property bool oatTop: !oplace.startsWith("bottom")
        readonly property string oside: oplace.split("-")[1] || "center"
        anchors {
            left: true
            right: true
            top: oatTop
            bottom: !oatTop
        }
        exclusionMode: ExclusionMode.Ignore
        WlrLayershell.layer: WlrLayer.Overlay
        WlrLayershell.namespace: "justday-osd"
        WlrLayershell.keyboardFocus: WlrKeyboardFocus.None
        color: "transparent"
        implicitHeight: Math.min(screen ? screen.height : 800, 160)
        mask: Region { item: osdCard }

        Rectangle {
            id: osdCard
            anchors.top: osdWin.oatTop ? parent.top : undefined
            anchors.bottom: osdWin.oatTop ? undefined : parent.bottom
            anchors.topMargin: osdWin.oatTop ? JD.topMargin + (JD.islandStyle === "bar" && JD.atTop ? JD.barHeight + 10 : 0) : 0
            anchors.bottomMargin: osdWin.oatTop ? 0 : JD.topMargin
            x: osdWin.oside === "left" ? JD.sideMargin
             : osdWin.oside === "right" ? parent.width - width - JD.sideMargin
             : (parent.width - width) / 2
            width: Math.max(168, osdInner.implicitWidth + 28)
            height: osdInner.implicitHeight + 20
            radius: Math.min(height / 2, 22)
            color: JD.ink
            border.width: 1
            border.color: Qt.rgba(1, 1, 1, 0.08)
            opacity: osdWin.show ? 1 : 0
            Behavior on opacity { NumberAnimation { duration: JD.dur(140); easing.type: Easing.OutCubic } }

            Column {
                id: osdInner
                anchors.centerIn: parent
                spacing: 8
                width: Math.max(140, layoutRow.implicitWidth, barRow.visible ? 180 : 0)

                Row {
                    id: layoutRow
                    spacing: 10
                    anchors.horizontalCenter: parent.horizontalCenter
                    Icon {
                        name: JD.osdIcon || (JD.osdKind === "layout" ? "keyboard"
                                          : JD.osdKind === "brightness" ? "sun"
                                          : (JD.osdMuted || JD.osdValue <= 0.001) ? "volume-x" : "volume-1")
                        implicitSize: 22
                        tint: JD.text1
                        anchors.verticalCenter: parent.verticalCenter
                    }
                    Text {
                        text: JD.osdLabel || (JD.osdKind === "layout" ? JD.layoutShort : Math.round(JD.osdValue * 100) + "%")
                        color: JD.text1
                        font.family: JD.fontFamily
                        font.pixelSize: JD.osdKind === "layout" ? 18 : 14
                        font.weight: Font.DemiBold
                        anchors.verticalCenter: parent.verticalCenter
                    }
                }
                Row {
                    id: barRow
                    visible: JD.osdKind === "volume" || JD.osdKind === "brightness"
                    spacing: 0
                    width: 180
                    height: 6
                    anchors.horizontalCenter: parent.horizontalCenter
                    Rectangle {
                        width: parent.width
                        height: parent.height
                        radius: 3
                        color: Qt.rgba(1, 1, 1, 0.12)
                        Rectangle {
                            width: parent.width * (JD.osdMuted ? 0 : JD.osdValue)
                            height: parent.height
                            radius: 3
                            color: JD.osdKind === "brightness" ? JD.accentOrange : JD.accentBlue
                            Behavior on width { NumberAnimation { duration: JD.dur(120); easing.type: Easing.OutCubic } }
                        }
                    }
                }
            }
        }
    }

    // Volume OSD: Pipewire default sink (hardware keys / mixer). Debounced; skips first snapshot.
    Item {
        id: osdVolWatch
        readonly property var sink: Pipewire.defaultAudioSink
        PwObjectTracker { objects: osdVolWatch.sink ? [osdVolWatch.sink] : [] }
        property real _lastVol: -1
        property bool _muted: false
        readonly property real sinkVol: sink && sink.audio ? Number(sink.audio.volume) || 0 : 0
        readonly property bool sinkMuted: !!(sink && sink.audio && sink.audio.muted)
        onSinkVolChanged: osdVolDebounce.restart()
        onSinkMutedChanged: osdVolDebounce.restart()
        onSinkChanged: Qt.callLater(osdVolWatch.push)
        function push() {
            if (!sink || !sink.audio) return
            const muted = sinkMuted
            const vol = muted ? 0 : Math.max(0, Math.min(1, sinkVol))
            if (!JD._osdPrimed) {
                JD._osdPrimed = true
                _lastVol = vol
                _muted = muted
                return
            }
            if (Math.abs(vol - _lastVol) < 0.004 && muted === _muted) return
            _lastVol = vol
            _muted = muted
            const pct = Math.round(vol * 100)
            const icon = muted || vol <= 0.001 ? "volume-x" : (vol < 0.5 ? "volume-1" : "volume-2")
            JD.showOsd("volume", vol, (muted ? JD.tr("Без звука") : (pct + "%")), icon, muted)
        }
        Timer { id: osdVolDebounce; interval: 60; onTriggered: osdVolWatch.push() }
        Component.onCompleted: Qt.callLater(osdVolWatch.push)
    }


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
        // Эмодзи и буфер не забирают клавиатуру: окно под ними остаётся в фокусе.
        // Enter и Esc ловит сам островок, пока панель открыта.
        readonly property bool floatTools: island.mode === "tools" && JD.toolsPage === "emoji"
        WlrLayershell.keyboardFocus: island.mode === "compose" || (island.mode === "tools" && !floatTools) ? WlrKeyboardFocus.Exclusive
                                   : big || island.mode === "video" ? WlrKeyboardFocus.OnDemand : WlrKeyboardFocus.None
        function confirmTool() {
            const item = JD.toolsItems[JD.toolsPick] || JD.toolsItems[0]
            if (!item) return
            if (JD.toolsPage === "emoji") JD.useEmoji(item.c)
            else JD.useClip(item.id)
        }
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
            Region { item: barStatus.page !== "" ? linkPop : null }
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
                const p = mapToItem(win, mouseX, mouseY)
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

        Shortcut { sequence: "Escape"; enabled: win.floatTools; onActivated: JD.closeTools() }
        Shortcut { sequence: "Return"; enabled: win.floatTools; onActivated: win.confirmTool() }
        Shortcut { sequence: "Enter"; enabled: win.floatTools; onActivated: win.confirmTool() }
        Shortcut { sequence: "Escape"; enabled: win.big && !win.floatTools; onActivated: JD.closeAll() }
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
                clip: true
                layer.enabled: false
                PeekView { id: peekView; shown: island.mode === "peek" || island.barHang }
                MusicView { id: musicView; shown: island.mode === "music" }
                PlayerView { id: playerView; shown: island.mode === "player" }
                VideoView { id: videoView; shown: island.mode === "video" }
                VideoPillView { id: videoPillView; shown: island.mode === "videopill" }
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
                    implicitHeight: 640
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
                readonly property var trayItems: SystemTray.items.values.filter(i => !!i && JD.trayShows(i))
                visible: island.barDock && (showLang || showBt || showNet || trayItems.length > 0)
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
                        NumberAnimation { property: "scale"; from: 0.4; to: 1; duration: 220; easing.type: Easing.OutBack }
                        NumberAnimation { property: "opacity"; from: 0; to: 1; duration: 160 }
                    }
                    move: Transition {
                        enabled: JD.animOn
                        NumberAnimation { property: "x"; duration: 200; easing.type: Easing.OutCubic }
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
                            scale: trayCatTap.pressed ? 0.88 : trayCatHover.hovered ? 1.15 : 1
                            Behavior on scale { enabled: JD.animOn; NumberAnimation { duration: 120; easing.type: Easing.OutCubic } }
                            HoverHandler { id: trayCatHover; cursorShape: Qt.PointingHandCursor
                                           onHoveredChanged: JD.catTipAt = hovered ? trayCat : (JD.catTipAt === trayCat ? null : JD.catTipAt) }
                            TapHandler { id: trayCatTap; onTapped: JD.openTools("load") }
                            CatCarry { cat: trayCat }
                        }
                    }
                    Repeater {
                        model: barStatus.trayItems
                        delegate: Item {
                            id: barTray
                            required property var modelData
                            implicitWidth: JD.barTraySize + 10
                            implicitHeight: JD.barTraySize + 10
                            // Те же движения, что у лотка (TrayView): рамка под рукой, значок
                            // подрастает, при нажатии проседает до 0.88. Раньше на полосе значки
                            // не отвечали ничем, и было непонятно, попал ли курсор.
                            Rectangle {
                                anchors.centerIn: parent
                                width: barTrayIcon.width * barTrayIcon.scale + 8
                                height: width
                                radius: Math.round(height * 0.3)
                                color: "transparent"
                                border.width: 1
                                border.color: Qt.rgba(1, 1, 1, barTrayHit.pressed ? 0.34 : 0.22)
                                opacity: barTrayHit.containsMouse && JD.trayCfg.hover_frame !== false ? 1 : 0
                                Behavior on opacity { enabled: JD.animOn; NumberAnimation { duration: 120 } }
                            }
                            Image {
                                id: barTrayIcon
                                anchors.centerIn: parent
                                width: JD.barTraySize
                                height: JD.barTraySize
                                sourceSize: Qt.size(JD.barTraySize * 2, JD.barTraySize * 2)
                                source: barTray.modelData.icon || ""
                                fillMode: Image.PreserveAspectFit
                                // без asynchronous: image://icon в фоновом потоке роняет KIconLoader (Icon.qml)
                                scale: barTrayHit.pressed ? 0.88 : barTrayHit.containsMouse ? 1.15 : 1
                                Behavior on scale { enabled: JD.animOn; NumberAnimation { duration: 120; easing.type: Easing.OutCubic } }
                            }
                            MouseArea {
                                id: barTrayHit
                                anchors.fill: parent
                                acceptedButtons: Qt.LeftButton | Qt.RightButton | Qt.MiddleButton
                                hoverEnabled: true
                                cursorShape: Qt.PointingHandCursor
                                onClicked: mouse => {
                                    const it = barTray.modelData
                                    if (mouse.button === Qt.MiddleButton) { it.secondaryActivate(); return }
                                    if (mouse.button === Qt.RightButton || (it.onlyMenu && it.hasMenu)) {
                                        if (JD.trayMenu === it) { JD.closeTrayMenu(); return }
                                        const p = barTray.mapToItem(null, barTray.width, barTray.height + 8)
                                        JD.trayMenuFromBar = true
                                        JD.openTrayMenu(it, p.x, p.y)
                                        return
                                    }
                                    JD.closeTrayMenu()
                                    it.activate()
                                    JD.trayWake(it)
                                }
                                onWheel: wheel => barTray.modelData.scroll(wheel.angleDelta.y, false)
                            }
                        }
                    }
                    Rectangle {
                        visible: barStatus.trayItems.length > 0 && (barStatus.showLang || barStatus.showBt || barStatus.showNet)
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
            Behavior on opacity { enabled: JD.animOn; NumberAnimation { duration: 140 } }
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

        // Короткая карточка сети или Bluetooth под правым краем полосы.
        Rectangle {
            id: linkPop
            visible: barStatus.page !== ""
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
                            Quickshell.execDetached(["systemsettings", barStatus.page === "bt" ? "kcm_bluetooth" : "kcm_networkmanagement"])
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

    // Кошку на сплошной полосе переносят рукой, как значки в доке: от часов к трею и обратно.
    // Сама кошка остаётся на месте полупрозрачной, рядом с рукой едет её копия (catGhost), а
    // куда она ляжет — решает отпускание, и выбор запоминается в island.cat_place.
    component CatCarry: DragHandler {
        property Item cat
        target: null
        enabled: JD.islandStyle === "bar"
        cursorShape: active ? Qt.ClosedHandCursor : Qt.PointingHandCursor
        onActiveChanged: {
            if (active) { JD.catTipAt = null; JD.catFrom = cat }
            else JD.catDrop()
        }
        onCentroidChanged: if (active) JD.catHand = centroid.scenePosition
    }

    component PeekView: View {
        property alias cat: clockCat
        id: pv
        readonly property color fg: JD.text1
        readonly property color fg2: JD.text2
        readonly property color hair: JD.fill2
        // Что играет — общим выбором из JD, а не жёстко вписанным Spotify: у всех, кто слушает
        // не его, полоска раньше пустовала. Показываем только играющее: трек на паузе в
        // свёрнутой полоске — это не «что сейчас», а мусор, который там и останется.
        readonly property var spot: (JD.playerInPeek && JD.musicPlaying) ? JD.musicPlayer : null
        readonly property string spotArt: {
            const u = pv.spot && pv.spot.trackArtUrl ? String(pv.spot.trackArtUrl) : ""
            if (u.indexOf("file://") === 0) return decodeURIComponent(u.slice(7))
            return u
        }
        readonly property string event: JD.workers > 0 ? JD.tr("Клод работает") + (JD.workers > 1 ? " ×" + JD.workers : "")
                                        : JD.runningJob ? JD.runningJob.title + " · " + JD.jobTime(JD.runningJob)
                                        : JD.dstate === "offline" ? JD.assistantName + JD.tr(" не запущен")
                                        : JD.nextEvent ? Qt.formatTime(new Date(JD.nextEvent.start), "HH:mm") + " · " + JD.nextEvent.title
                                        : JD.update ? JD.tr("Доступно обновление")
                                        : (JD.island.show_events !== false && JD.history.length && JD.history[0].a) ? JD.history[0].a : ""
        implicitWidth: peekRow.implicitWidth + 32
        implicitHeight: JD.islandStyle === "bar" ? JD.barHeight : 44
        property real squeeze: 1
        property real hoverScale: JD.islandStyle === "bar" && (midHover.hovered || island.mode === "expanded" || island.mode === "settings" || island.mode === "tools") ? 1.08 : 1
        Behavior on hoverScale { NumberAnimation { duration: 180; easing.type: Easing.OutCubic } }
        // Вниз и вверх одинаково. Повторный клик начинает цикл заново, а не ставит его в очередь.
        function bump() { pulse.restart() }
        SequentialAnimation {
            id: pulse
            NumberAnimation { target: pv; property: "squeeze"; to: 0.985; duration: 80; easing.type: Easing.InOutCubic }
            NumberAnimation { target: pv; property: "squeeze"; to: 1; duration: 80; easing.type: Easing.InOutCubic }
        }
        SystemClock { id: clock; precision: SystemClock.Minutes }
        RowLayout {
            id: peekRow
            anchors.centerIn: parent
            spacing: 12
            scale: pv.hoverScale * pv.squeeze
            transformOrigin: Item.Center
            HoverHandler { id: midHover; enabled: JD.islandStyle === "bar" }
            Ring {
                visible: !JD.buddyOn
                size: 18
                tint: JD.workers > 0 ? JD.accentPurple : JD.dstate === "offline" ? JD.accentRed : JD.accentCyan
                spinning: JD.workers > 0
            }
            // Существо вместо кольца: кольцо сообщает состояние цветом и вращением, и это надо
            // знать заранее. Существо сообщает тем же, чем сообщают живые, — взглядом и позой, и
            // объяснять это не нужно никому.
            //
            // Выбран скин — показываем нарисованного зверя, нет — своего, нарисованного кодом.
            // Оба живут по одной таблице состояний и носят одни и те же глаза.
            Buddy {
                visible: JD.buddyOn && !JD.mascotSkin
                size: 22
                mood: JD.buddyMood
                voice: JD.level
                lookX: JD.pointerX
                lookY: JD.pointerY
            }
            Mascot {
                visible: JD.buddyOn && !!JD.mascotSkin
                skin: JD.mascotSkin
                size: Math.round(28 * JD.mascotZoom)
                mood: JD.buddyMood
                voice: JD.level
                lookX: JD.pointerX
                lookY: JD.pointerY
            }
            DockCat {
                id: clockCat
                // На полосе кошку можно унести к значкам трея; у островка и выреза трея нет.
                visible: JD.island.cat === true && !(JD.islandStyle === "bar" && JD.catPlace === "tray")
                size: 22
                cpu: JD.cpu
                awake: true
                sleepBelow: JD.dockCfg.cat_sleep_below || 0
                opacity: JD.catFrom === clockCat ? 0.3 : 1
                HoverHandler { onHoveredChanged: JD.catTipAt = hovered ? clockCat : (JD.catTipAt === clockCat ? null : JD.catTipAt) }
                CatCarry { cat: clockCat }
            }
            Text { text: Qt.formatTime(clock.date, "HH:mm"); color: pv.fg; font.family: JD.fontFamily; font.pixelSize: 16; font.weight: Font.Bold; font.features: { "tnum": 1 } }
            Label2 { text: clock.date.toLocaleDateString(Qt.locale(JD.lang === "ru" ? "ru_RU" : "en_US"), "ddd, d MMM"); color: pv.fg2 }
            // Только Spotify. Чужие плееры (браузер, YouTube) на полосу не выводятся.
            Rectangle { visible: !!pv.spot; implicitWidth: 1; implicitHeight: 18; color: pv.hair }
            Art {
                visible: !!pv.spot
                size: 22
                src: pv.spotArt
                tint: JD.accentPink
            }
            Label2 {
                visible: !!pv.spot
                text: pv.spot ? JD.cleanTitle(pv.spot.trackTitle) : ""
                maximumLineCount: 1
                wrapMode: Text.NoWrap
                Layout.maximumWidth: 180
                color: pv.fg
            }
            EqBars { visible: !!pv.spot; tint: JD.accentPink; playing: true }
            Rectangle { visible: !!pv.event; implicitWidth: 1; implicitHeight: 18; color: pv.hair }
            Label2 { visible: !!pv.event; text: pv.event.replace(/\s+/g, " "); maximumLineCount: 1; wrapMode: Text.NoWrap; Layout.maximumWidth: 260; color: JD.workers > 0 ? JD.accentPurple : pv.fg2 }
            // a running timer, the way the phone shows one: the number, not a logo
            Rectangle { visible: !!JD.runningTimer; implicitWidth: 1; implicitHeight: 18; color: pv.hair }
            RowLayout {
                visible: !!JD.runningTimer
                spacing: 5
                Icon { name: "timer"; implicitSize: 15; tint: JD.accentOrange }
                Text {
                    text: JD.reminderLeft(JD.runningTimer)
                    color: JD.accentOrange; font.family: JD.fontFamily; font.pixelSize: 14
                    font.weight: Font.DemiBold; font.features: { "tnum": 1 }
                }
            }
            // Молчит по просьбе. Об этом нужно говорить вслух — вернее, показывать: иначе «он мне
            // не отвечает» выглядит поломкой, хотя ассистент просто выполняет «молчи».
            Rectangle { visible: JD.muted; implicitWidth: 1; implicitHeight: 18; color: pv.hair }
            Rectangle {
                visible: JD.muted
                implicitWidth: mutedRow.implicitWidth + 16
                implicitHeight: 22
                radius: 11
                color: muteHover.hovered ? JD.fill2 : JD.fill1
                RowLayout {
                    id: mutedRow
                    anchors.centerIn: parent
                    spacing: 5
                    Icon { name: "audio-volume-muted"; implicitSize: 13; tint: JD.accentOrange }
                    Label2 { text: JD.tr("Молчит"); color: JD.accentOrange; font.weight: Font.DemiBold }
                }
                HoverHandler { id: muteHover; cursorShape: Qt.PointingHandCursor }
                // Нажатие прямо здесь возвращает голос: пометка — она же и кнопка.
                TapHandler { gesturePolicy: TapHandler.ReleaseWithinBounds; onTapped: JD.setMuted(false) }
            }
            Rectangle { visible: !!JD.weather && JD.island.show_weather !== false; implicitWidth: 1; implicitHeight: 18; color: pv.hair }
            RowLayout {
                visible: !!JD.weather && JD.island.show_weather !== false
                spacing: 6
                Image { source: JD.weather ? Quickshell.shellDir + "/icons/" + JD.weather.icon + ".svg" : ""; sourceSize: Qt.size(36, 36); Layout.preferredWidth: 18; Layout.preferredHeight: 18 }
                Text { text: JD.weather ? (JD.weather.temp > 0 ? "+" : "") + JD.weather.temp + "°" : ""; color: pv.fg; font.family: JD.fontFamily; font.pixelSize: 14; font.weight: Font.DemiBold }
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
        // Ступень ноль — кружок и ничего больше: идёт работа, и этого достаточно, чтобы знать.
        implicitWidth: JD.workStep === 0 ? (JD.brainStrong ? 136 : 92)
                                         : Math.min(640, Math.max(240, tm.width + 118))
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
                visible: JD.workStep === 1
            }
            // На сильной модели — отметка. Про лёгкую говорить нечего: она работает всегда, и
            // сообщать об этом значило бы шуметь ровно в том месте, которое мы бережём.
            Rectangle {
                visible: JD.brainStrong
                implicitHeight: 18
                implicitWidth: strongLabel.implicitWidth + 14
                radius: 9
                color: Qt.rgba(JD.accentPurple.r, JD.accentPurple.g, JD.accentPurple.b, 0.22)
                Label2 {
                    id: strongLabel
                    anchors.centerIn: parent
                    text: JD.brainModel
                    color: JD.accentPurple
                    font.pixelSize: 10
                    font.weight: Font.DemiBold
                }
            }
            Label2 { text: tv.elapsed >= 3 ? tv.elapsed + JD.tr(" с") : ""; font.features: { "tnum": 1 } }
            IconButton {
                // Одна кнопка на все три ступени: значок → строка → всё → снова значок. Три
                // отдельные кнопки заняли бы ровно то место, которое мы бережём.
                visible: true
                size: 24
                icon: JD.workStep === 2 ? "go-up" : "go-down"
                onClicked: JD.workMore()
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

    // a small round button that takes the click for itself (the rest of the notification opens the app)
    component RoundKey: Rectangle {
        id: rk
        property string icon: ""
        signal clicked()
        implicitWidth: 28
        implicitHeight: 28
        radius: 14
        color: rkArea.containsMouse ? JD.fill2 : JD.fill1
        scale: rkArea.pressed ? 0.9 : 1
        Behavior on scale { NumberAnimation { duration: 120 } }
        Icon { anchors.centerIn: parent; name: rk.icon; implicitSize: 14 }
        MouseArea { id: rkArea; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: rk.clicked() }
    }

    // a desktop notification: ⌄ unfolds the whole text, ✕ lets it go, a tap anywhere else opens the app
    component NotificationView: View {
        id: nv
        readonly property var n: JD.notification || ({})
        readonly property bool open: JD.notifExpanded
        implicitWidth: open ? 600 : Math.min(580, Math.max(380, nRow.implicitWidth + 36))
        implicitHeight: nCol.implicitHeight + 26
        MouseArea {
            anchors.fill: parent
            z: 0
            cursorShape: Qt.PointingHandCursor
            acceptedButtons: Qt.LeftButton
            onClicked: JD.openNotification(JD.notification)
        }
        ColumnLayout {
            id: nCol
            anchors { left: parent.left; right: parent.right; top: parent.top; topMargin: 13; leftMargin: 16; rightMargin: 12 }
            spacing: 10
            RowLayout {
                id: nRow
                spacing: 12
                Rectangle {
                    implicitWidth: 38; implicitHeight: 38; radius: 11
                    color: JD.fill1
                    Layout.alignment: Qt.AlignTop
                    Icon { anchors.centerIn: parent; name: nv.n.icon || (nv.n.app || "").toLowerCase(); fallback: "preferences-desktop-notification-bell"; implicitSize: 26 }
                }
                ColumnLayout {
                    spacing: 1
                    Layout.fillWidth: true
                    RowLayout {
                        spacing: 6
                        Label2 { text: nv.n.app || ""; color: JD.text3; font.pixelSize: 11 }
                        Label2 { text: JD.tr("· сейчас"); color: JD.text3; font.pixelSize: 11 }
                    }
                    Label1 { text: nv.n.summary || ""; TextSwap on text {} Layout.fillWidth: true; Layout.maximumWidth: 440 }
                    Label2 {
                        visible: !!nv.n.body && !nv.open
                        text: (nv.n.body || "").replace(/\s+/g, " ")
                        TextSwap on text {}
                        wrapMode: Text.Wrap; maximumLineCount: 2
                        Layout.fillWidth: true; Layout.maximumWidth: 440
                    }
                }
                RoundKey {
                    visible: !!nv.n.body
                    Layout.alignment: Qt.AlignTop
                    icon: nv.open ? "go-up" : "go-down"
                    onClicked: JD.notifExpanded = !JD.notifExpanded
                }
                RoundKey { Layout.alignment: Qt.AlignTop; icon: "window-close"; onClicked: JD.dismissNotification() }
            }
            Label2 {
                visible: !nv.open
                text: JD.tr("Нажмите, чтобы открыть ") + (nv.n.app || JD.tr("приложение"))
                color: JD.text3; font.pixelSize: 11
                Layout.alignment: Qt.AlignHCenter
            }
            // unfolded: the whole message, like a long-press preview on a phone
            Rectangle {
                visible: nv.open
                Layout.fillWidth: true
                Layout.rightMargin: 4
                implicitHeight: Math.min(320, fullBody.implicitHeight + 24)
                radius: 14
                color: JD.fill1
                Flickable {
                    anchors { fill: parent; margins: 12 }
                    contentHeight: fullBody.implicitHeight
                    clip: true
                    boundsBehavior: Flickable.StopAtBounds
                    MouseArea {  // the Flickable keeps clicks on the text for itself: pass them on
                        width: parent.width
                        height: fullBody.implicitHeight
                        cursorShape: Qt.PointingHandCursor
                        onClicked: JD.openNotification(JD.notification)
                    }
                    Text {
                        id: fullBody
                        width: parent.width
                        text: nv.n.body || ""
                        wrapMode: Text.Wrap
                        color: JD.text1
                        font.family: JD.fontFamily
                        font.pixelSize: 14
                        lineHeight: 1.18
                        textFormat: Text.PlainText
                    }
                }
            }
            Label2 {
                visible: nv.open
                text: JD.tr("Нажмите, чтобы открыть ") + (nv.n.app || JD.tr("приложение"))
                color: JD.text3; font.pixelSize: 11
                Layout.alignment: Qt.AlignHCenter
            }
        }
    }

    // A timer or an alarm going off. One thing to read (what and when), one thing to press (Выключить):
    // Live Activities › Offering interactivity — "prefer limiting it to a single element".
    component AlarmView: View {
        id: av
        readonly property var a: JD.alarm || ({})
        readonly property bool isAlarm: av.a.kind === "alarm"
        readonly property color tint: JD.accentOrange
        implicitWidth: Math.min(620, Math.max(430, alarmRow.implicitWidth + 40))
        implicitHeight: 96
        RowLayout {
            id: alarmRow
            anchors { fill: parent; leftMargin: 18; rightMargin: 14; topMargin: 16; bottomMargin: 16 }
            spacing: 14
            Item {
                implicitWidth: 52; implicitHeight: 52
                Rectangle {   // a ring that breathes while it rings; the label says the same thing in words
                    anchors.centerIn: parent
                    width: 52; height: 52; radius: 26
                    color: Qt.rgba(av.tint.r, av.tint.g, av.tint.b, 0.22)
                    SequentialAnimation on scale {
                        running: JD.animOn && island.mode === "alarm"
                        loops: Animation.Infinite
                        NumberAnimation { to: 1.12; duration: 520; easing.type: Easing.OutCubic }
                        NumberAnimation { to: 1.0; duration: 520; easing.type: Easing.InCubic }
                    }
                }
                Icon { anchors.centerIn: parent; name: av.isAlarm ? "bell-ring" : "timer"; implicitSize: 24; tint: av.tint }
            }
            ColumnLayout {
                spacing: 2
                Layout.fillWidth: true
                SectionLabel { text: (av.isAlarm ? JD.tr("БУДИЛЬНИК") : JD.tr("ТАЙМЕР")); color: av.tint }
                Label1 {
                    text: av.a.label || (av.isAlarm ? av.a.time || "" : JD.tr("Время вышло"))
                    font.pixelSize: 20; font.weight: Font.DemiBold
                    Layout.fillWidth: true
                }
                Label2 { visible: !!av.a.label && !!av.a.time; text: av.a.time || ""; font.pixelSize: 12 }
            }
            PillButton {
                visible: av.isAlarm
                label: JD.tr("+5 минут")
                onClicked: { JD.send({ cmd: "reminder_set", kind: "alarm", seconds: 300, label: av.a.label || "" }); JD.dismissAlarm(av.a.id) }
            }
            PillButton {
                label: JD.tr("Выключить")
                tint: av.tint
                labelColor: "black"
                onClicked: JD.dismissAlarm(av.a.id)
            }
        }
    }

    // ───────────── music & video ─────────────
    // album cover (a file or a YouTube thumbnail link), cropped to a rounded square
    component Art: ClippingRectangle {
        id: art
        property string src: ""
        property color tint: JD.text1     // the track's colour, for the placeholder
        property real size: 26
        implicitWidth: size
        implicitHeight: size
        radius: Math.min(Math.round(size * 0.24), 16)
        color: JD.fill2
        // no cover yet (a local file, a station): a record-sleeve gradient, not a grey file icon
        Rectangle {
            anchors.fill: parent
            visible: artImg.status !== Image.Ready
            gradient: Gradient {
                GradientStop { position: 0; color: Qt.rgba(art.tint.r, art.tint.g, art.tint.b, 0.30) }
                GradientStop { position: 1; color: Qt.rgba(art.tint.r, art.tint.g, art.tint.b, 0.10) }
            }
            Icon { anchors.centerIn: parent; name: "music"; implicitSize: art.size * 0.46; opacity: 0.75 }
        }
        Image {
            id: artImg
            anchors.fill: parent
            // MPRIS отдаёт обложку готовым адресом «file:///…». Здесь ему приклеивали второй
            // file://, картинка не грузилась, и у чужого плеера вместо обложки всегда была нота.
            source: !art.src ? "" : /^(https?|file|data|image):/.test(art.src) ? art.src : "file://" + art.src
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
        property bool live: false       // report every step (volume), not only the release (seeking)
        property int thickness: 5       // the volume track is thinner: it is not the progress of anything
        signal seek(real frac)
        implicitHeight: 16
        Rectangle {
            anchors.verticalCenter: parent.verticalCenter
            width: parent.width
            height: sbHover.hovered || sb.dragValue >= 0 ? sb.thickness + 2 : sb.thickness
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
            onPositionChanged: m => { if (pressed) { sb.dragValue = at(m.x); if (sb.live) sb.seek(sb.dragValue) } }
            onReleased: { sb.seek(sb.dragValue); sb.dragValue = -1 }
        }
    }

    // the live activity: cover · title · bars (a click opens the player)
    component MusicView: View {
        id: mv
        readonly property var p: JD.player || ({})
        property color tint: JD.artTint(p.color)
        Behavior on tint { ColorAnimation { duration: 450; easing.type: Easing.OutCubic } }
        readonly property bool loading: !!p.loading
        // Он думает прямо сейчас, а островок занят музыкой: сказать об этом строкой на ней же.
        readonly property bool busy: JD.dstate === "thinking" || JD.dstate === "speaking"
        readonly property string label: loading ? JD.tr("Загружаю") + " «" + (p.loading.title || "") + "»" : (p.title || "")
        implicitWidth: mrow.implicitWidth + 26
        implicitHeight: 40
        RowLayout {
            id: mrow
            anchors { left: parent.left; verticalCenter: parent.verticalCenter; leftMargin: 8 }
            spacing: 10
            Item {
                implicitWidth: 26; implicitHeight: 26
                Art { anchors.fill: parent; size: 26; tint: mv.tint; src: mv.loading ? "" : (mv.p.thumb || ""); visible: !mv.loading }
                Ring { anchors.centerIn: parent; size: 20; visible: mv.loading; spinning: true; tint: JD.accentPink }
            }
            Label1 { text: mv.label; TextSwap on text {} Layout.maximumWidth: 200 }
            Label2 {
                visible: mv.loading && (mv.p.loading.progress || 0) > 0
                text: Math.round((mv.p.loading ? mv.p.loading.progress : 0) * 100) + "%"
                font.features: { "tnum": 1 }
            }
            EqBars { visible: !mv.loading; tint: mv.tint; playing: !mv.p.paused }
            // the music is not the only thing the island knows: the time, a running timer, what Claude is
            // doing or what comes next, the weather — the same line the island shows without music
            Rectangle { implicitWidth: 1; implicitHeight: 18; color: JD.fill2 }
            Text {
                text: Qt.formatTime(mvClock.date, "HH:mm")
                color: JD.text1; font.family: JD.fontFamily; font.pixelSize: 14; font.weight: Font.Bold; font.features: { "tnum": 1 }
            }
            RowLayout {
                visible: !!JD.runningTimer
                spacing: 4
                Icon { name: "timer"; implicitSize: 14; tint: JD.accentOrange }
                Text {
                    text: JD.reminderLeft(JD.runningTimer)
                    color: JD.accentOrange; font.family: JD.fontFamily; font.pixelSize: 13
                    font.weight: Font.DemiBold; font.features: { "tnum": 1 }
                }
            }
            // Пока играет музыка, работа живёт здесь, а не вместо обложки: кружок и короткая
            // строка о том, что он сейчас делает. Так видно и то и другое сразу.
            Ring {
                visible: mv.busy
                size: 14
                Layout.preferredWidth: 14; Layout.preferredHeight: 14
            }
            Label2 {
                readonly property string event: mv.busy ? (JD.activity || JD.tr("Думаю…"))
                                                : JD.workers > 0 ? JD.tr("Клод работает") + (JD.workers > 1 ? " ×" + JD.workers : "")
                                                : JD.runningJob ? JD.runningJob.title + " · " + JD.jobTime(JD.runningJob)
                                                : JD.nextEvent ? Qt.formatTime(new Date(JD.nextEvent.start), "HH:mm") + " · " + JD.nextEvent.title : ""
                visible: !!event
                text: event.replace(/\s+/g, " "); maximumLineCount: 1; wrapMode: Text.NoWrap
                elide: Text.ElideRight
                Layout.maximumWidth: 170
                color: mv.busy ? JD.accentBlue : JD.workers > 0 ? JD.accentPurple : JD.text2
            }
            RowLayout {
                visible: !!JD.weather && JD.island.show_weather !== false
                spacing: 5
                Image { source: JD.weather ? Quickshell.shellDir + "/icons/" + JD.weather.icon + ".svg" : ""; sourceSize: Qt.size(32, 32); Layout.preferredWidth: 16; Layout.preferredHeight: 16 }
                Text { text: JD.weather ? (JD.weather.temp > 0 ? "+" : "") + JD.weather.temp + "°" : ""; color: JD.text1; font.family: JD.fontFamily; font.pixelSize: 13; font.weight: Font.DemiBold }
            }
        }
        SystemClock { id: mvClock; precision: SystemClock.Minutes }
    }

    // a round toggle for shuffle / repeat: lit in the cover's colour when on
    component ModeButton: Rectangle {
        id: mb
        property string icon: ""
        property bool on: false
        property color tint: JD.accentPink
        property string badge: ""
        signal clicked()
        implicitWidth: 36
        implicitHeight: 36
        radius: 18
        color: on ? Qt.rgba(tint.r, tint.g, tint.b, 0.28) : (mbHover.hovered ? JD.fill2 : "transparent")
        scale: mbTap.pressed ? 0.9 : 1
        Behavior on color { ColorAnimation { duration: 160 } }
        Behavior on scale { NumberAnimation { duration: 120 } }
        Icon { anchors.centerIn: parent; name: mb.icon; implicitSize: 18; opacity: mb.on ? 1 : 0.55 }
        Rectangle {
            visible: !!mb.badge
            anchors { right: parent.right; top: parent.top; rightMargin: 3; topMargin: 3 }
            width: 13; height: 13; radius: 6.5
            color: mb.tint
            Text { anchors.centerIn: parent; text: mb.badge; color: "black"; font.family: JD.fontFamily; font.pixelSize: 9; font.weight: Font.Bold }
        }
        HoverHandler { id: mbHover; cursorShape: Qt.PointingHandCursor }
        TapHandler { id: mbTap; gesturePolicy: TapHandler.ReleaseWithinBounds; onTapped: mb.clicked() }
    }

    // the big player: cover, title, progress, shuffle · prev · play · next · repeat, the queue
    component PlayerView: View {
        id: pl
        readonly property var p: JD.player || ({})
        property color tint: JD.artTint(p.color)
        Behavior on tint { ColorAnimation { duration: 450; easing.type: Easing.OutCubic } }
        property real now: Date.now()
        property bool queueOpen: false
        property int volumeWas: 0      // where the mute button came from
        Timer { interval: 250; repeat: true; running: pl.visible && !pl.p.paused; onTriggered: pl.now = Date.now() }
        readonly property real pos: { pl.now; return JD.playerPos(Date.now()) }
        readonly property var upcoming: (p.queue || []).filter(q => q.i >= (p.index || 0))
        implicitWidth: 540
        implicitHeight: plCol.implicitHeight + 36
        onShownChanged: if (!shown) queueOpen = false
        function optimistic(change) { JD.player = Object.assign({}, JD.player, change); JD.playerAt = Date.now() }
        // the cover's colour glows through from the top
        Rectangle {
            anchors.fill: parent
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
            // the cover, large: a tap on the small one opens it, a tap on it puts it back
            Item {
                Layout.fillWidth: true
                // plCol's width, not its own: a hidden item in a layout has none, and would never grow back
                Layout.preferredHeight: JD.artOpen ? plCol.width : 0
                visible: Layout.preferredHeight > 1
                clip: true
                Behavior on Layout.preferredHeight { NumberAnimation { duration: JD.dur(JD.slideMs); easing.type: Easing.OutCubic } }
                Art {
                    width: plCol.width; height: plCol.width
                    size: plCol.width
                    tint: pl.tint; src: pl.p.thumb || ""
                    opacity: JD.artOpen ? 1 : 0
                    scale: JD.artOpen ? 1 : 0.92
                    Behavior on opacity { NumberAnimation { duration: JD.dur(240) } }
                    Behavior on scale { NumberAnimation { duration: JD.dur(JD.slideMs); easing.type: Easing.OutCubic } }
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
                IconButton { icon: "view-grid"; size: 26; Layout.alignment: Qt.AlignTop
                             onClicked: { JD.playerOpen = false; JD.expanded = true } }
                IconButton { icon: "go-up"; size: 26; Layout.alignment: Qt.AlignTop; onClicked: JD.playerOpen = false }
            }
            SeekBar {
                Layout.fillWidth: true
                Layout.topMargin: 4
                tint: pl.tint
                value: pl.p.duration > 0 ? pl.pos / pl.p.duration : 0
                onSeek: frac => { const to = frac * (pl.p.duration || 0); JD.media("seek", to); pl.optimistic({ pos: to }) }
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
                Rectangle {
                    implicitWidth: 56; implicitHeight: 56; radius: 28
                    color: ppHover.hovered ? Qt.lighter(pl.tint, 1.15) : pl.tint
                    scale: ppTap.pressed ? 0.92 : 1
                    Behavior on scale { NumberAnimation { duration: 120 } }
                    PlayGlyph { anchors.centerIn: parent; paused: !!pl.p.paused; size: 20; tint: "black" }
                    HoverHandler { id: ppHover; cursorShape: Qt.PointingHandCursor }
                    TapHandler { id: ppTap; onTapped: { JD.media("toggle"); pl.optimistic({ pos: pl.pos, paused: !pl.p.paused }) } }
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
                SeekBar {
                    Layout.fillWidth: true
                    live: true
                    thickness: 3
                    tint: Qt.rgba(pl.tint.r, pl.tint.g, pl.tint.b, 0.75)
                    value: (pl.p.volume || 0) / 100
                    onSeek: frac => { const v = Math.round(frac * 100); JD.media("volume", v); pl.optimistic({ volume: v }) }
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
                IconButton { icon: "document-open-folder"; size: 30; onClicked: { Quickshell.execDetached(["dolphin", "--select", pl.p.file]); JD.closeAll() } }
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

    // свёрнутый кадр: ролик играет дальше, а экран свободен — как пилюля музыки
    component VideoPillView: View {
        id: vp2
        readonly property var v: JD.video || ({})
        implicitWidth: vpRow.implicitWidth + 26
        implicitHeight: 40
        RowLayout {
            id: vpRow
            anchors { left: parent.left; verticalCenter: parent.verticalCenter; leftMargin: 10 }
            spacing: 10
            Rectangle {
                implicitWidth: 26; implicitHeight: 26; radius: 7
                color: Qt.rgba(JD.accentPink.r, JD.accentPink.g, JD.accentPink.b, 0.22)
                Icon { anchors.centerIn: parent; name: "video-x-generic"; implicitSize: 15 }
            }
            Label1 { text: vp2.v.title || JD.tr("Видео"); Layout.maximumWidth: 220 }
            Label2 {
                text: JD.fmtTime(JD.videoPos) + " / " + JD.fmtTime(JD.videoDur)
                font.features: { "tnum": 1 }
                visible: JD.videoDur > 0
            }
            IconButton { icon: JD.videoPlaying ? "media-playback-pause" : "media-playback-start"; size: 26
                         onClicked: JD.videoCommand("toggle") }
            IconButton { icon: "view-fullscreen"; size: 26; onClicked: JD.videoMini = false }
            IconButton { icon: "window-close"; size: 26; onClicked: videoView.close() }
        }
    }

    // a video inside the island (downloaded first; played by Qt right here)
    component VideoView: View {
        id: vv
        readonly property var v: JD.video || ({})
        readonly property bool ready: !!v.file
        property bool ended: false
        readonly property bool busyLine: ["listening", "thinking", "speaking", "transcribing"].includes(JD.dstate) || JD.answerOpen
        readonly property bool hearing: JD.dstate === "listening"
        property real smallWidth: 640      // куда вернуться из «во весь экран»
        implicitWidth: JD.videoWidth
        implicitHeight: Math.round(implicitWidth * 9 / 16)
        function grow(w) { JD.setVideoWidth(w); JD.saveVideoWidth() }

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
        function seekBy(ms) {
            player.position = Math.max(0, Math.min(player.duration || 0, player.position + ms))
            vv.ended = false
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
            playbackRate: JD.videoRate
            audioOutput: AudioOutput {
                // своя громкость кадра (колесо над видео), приглушённая, пока ассистент слушает или говорит
                volume: JD.videoVolume * (["listening", "speaking", "approval"].includes(JD.dstate) ? 0.25 : 1.0)
                muted: Quickshell.env("JUSTDAY_ISLAND_MUTE") === "1"  // the headless test stand stays silent
            }
            onSourceChanged: { vv.ended = false; if (source.toString() !== "") play() }
            // ролик, который вернули из окна или продолжили, начинается с той же секунды
            onMediaStatusChanged: {
                if (mediaStatus === MediaPlayer.LoadedMedia && (vv.v.start || 0) > 1 && position < 1000)
                    position = vv.v.start * 1000
                if (mediaStatus === MediaPlayer.EndOfMedia) {
                    if (JD.videoLoop) { position = 0; play() }
                    else { vv.ended = true; endTimer.restart() }
                }
            }
            onPlaybackStateChanged: {
                JD.videoPlaying = playbackState === MediaPlayer.PlayingState
                JD.send({ cmd: "video_state", playing: playbackState === MediaPlayer.PlayingState, pos: position / 1000 })
            }
            onPositionChanged: { JD.videoPos = position / 1000; JD.videoDur = duration / 1000 }
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
                                Behavior on width { NumberAnimation { duration: 200; easing.type: Easing.OutCubic } } }
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
                    IconButton {
                        icon: JD.videoBig ? "view-restore" : "view-fullscreen"; size: 28
                        onClicked: { if (JD.videoBig) vv.grow(vv.smallWidth)
                                     else { vv.smallWidth = JD.videoWidth; vv.grow(JD.videoRoom) } }
                    }
                    IconButton { icon: "window-new"; size: 28; visible: vv.ready; onClicked: vv.popout(false) }
                    IconButton { icon: "go-up"; size: 28; visible: vv.ready; onClicked: JD.videoMini = true }
                    IconButton { icon: "internet-web-browser"; size: 28; visible: !!vv.v.url && vv.v.url.startsWith("http")
                                 onClicked: { Quickshell.execDetached(["xdg-open", vv.v.url + (player.position > 3000 ? "&t=" + Math.floor(player.position / 1000) + "s" : "")]); vv.close() } }
                    IconButton { icon: "window-close"; size: 28; onClicked: vv.close() }
                }
            }

            // низ: перемотка, время, прогресс, громкость, скорость, повтор — то, что ждёшь от плеера
            Rectangle {
                id: vctl
                visible: vv.ready
                anchors { left: parent.left; right: parent.right; bottom: parent.bottom }
                height: 96
                opacity: vv.chrome && !vv.busyLine ? 1 : 0
                Behavior on opacity { NumberAnimation { duration: 200 } }
                gradient: Gradient {
                    GradientStop { position: 0; color: "transparent" }
                    GradientStop { position: 0.35; color: Qt.rgba(0, 0, 0, 0.55) }
                    GradientStop { position: 1; color: Qt.rgba(0, 0, 0, 0.92) }
                }
                readonly property bool roomy: vv.width > 560     // на узком кадре остаётся главное
                ColumnLayout {
                    anchors { left: parent.left; right: parent.right; bottom: parent.bottom
                              leftMargin: 20; rightMargin: 24; bottomMargin: 10 }
                    spacing: 2
                    SeekBar {
                        Layout.fillWidth: true
                        tint: JD.accentPink
                        value: player.duration > 0 ? player.position / player.duration : 0
                        onSeek: frac => { player.position = frac * player.duration; vv.ended = false }
                    }
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8
                        IconButton { icon: "rotate-ccw"; size: 28; onClicked: vv.seekBy(-10000) }
                        IconButton { icon: player.playbackState === MediaPlayer.PlayingState ? "media-playback-pause" : "media-playback-start"
                                     size: 34; onClicked: vv.toggle() }
                        IconButton { icon: "refresh-cw"; size: 28; onClicked: vv.seekBy(10000) }
                        Label2 {
                            text: JD.fmtTime(player.position / 1000) + " / " + JD.fmtTime(player.duration / 1000)
                            color: JD.text1; font.pixelSize: 11; font.features: { "tnum": 1 }
                            Layout.leftMargin: 4
                        }
                        Item { Layout.fillWidth: true }
                        // громкость этого ролика: она запоминается и не трогает ни музыку, ни систему
                        Icon {
                            name: JD.videoVolume === 0 ? "audio-volume-muted" : "audio-volume-high"
                            implicitSize: 15; tint: JD.text2
                            HoverHandler { cursorShape: Qt.PointingHandCursor }
                            TapHandler { onTapped: { JD.setVideoVolume(JD.videoVolume > 0 ? 0 : 1); JD.saveVideoVolume() } }
                        }
                        SeekBar {
                            visible: vctl.roomy
                            Layout.preferredWidth: 76
                            live: true
                            thickness: 3
                            tint: Qt.rgba(1, 1, 1, 0.8)
                            value: JD.videoVolume
                            onSeek: frac => JD.setVideoVolume(frac)
                        }
                        // скорость: 0.5 … 2, по кругу
                        Rectangle {
                            visible: vctl.roomy
                            implicitWidth: rateLabel.implicitWidth + 20; implicitHeight: 28; radius: 14
                            color: JD.videoRate === 1 ? (rateHover.hovered ? Qt.rgba(1, 1, 1, 0.22) : Qt.rgba(1, 1, 1, 0.14))
                                                      : Qt.rgba(JD.accentPink.r, JD.accentPink.g, JD.accentPink.b, 0.32)
                            Label1 {
                                id: rateLabel
                                anchors.centerIn: parent
                                font.pixelSize: 12
                                font.weight: Font.DemiBold
                                text: (JD.videoRate % 1 === 0 ? JD.videoRate.toFixed(0) : String(JD.videoRate)) + "×"
                                color: JD.videoRate === 1 ? JD.text1 : JD.accentPink
                            }
                            HoverHandler { id: rateHover; cursorShape: Qt.PointingHandCursor }
                            TapHandler {
                                gesturePolicy: TapHandler.ReleaseWithinBounds
                                onTapped: {
                                    const steps = [0.5, 0.75, 1, 1.25, 1.5, 2]
                                    JD.videoRate = steps[(steps.indexOf(JD.videoRate) + 1) % steps.length]
                                }
                            }
                        }
                        ModeButton {
                            icon: "media-repeat-single"; on: JD.videoLoop; tint: JD.accentPink
                            implicitWidth: 30; implicitHeight: 30
                            onClicked: JD.videoLoop = !JD.videoLoop
                        }
                    }
                }
            }

            // колесо — громкость, Ctrl+колесо — размер кадра
            WheelHandler {
                acceptedModifiers: Qt.NoModifier
                onWheel: e => JD.setVideoVolume(JD.videoVolume + (e.angleDelta.y > 0 ? 0.05 : -0.05))
            }
            WheelHandler {
                acceptedModifiers: Qt.ControlModifier
                onWheel: e => { JD.setVideoWidth(JD.videoWidth + (e.angleDelta.y > 0 ? 80 : -80)); JD.saveVideoWidth() }
            }

            // сколько сейчас громкость / какой размер — пока его меняют
            Rectangle {
                anchors { horizontalCenter: parent.horizontalCenter; top: parent.top; topMargin: 96 }
                width: sizeLabel.implicitWidth + 24; height: 28; radius: 14
                color: Qt.rgba(0, 0, 0, 0.7)
                opacity: volumeHint.running || JD.videoResizing ? 1 : 0
                visible: opacity > 0.01
                Behavior on opacity { NumberAnimation { duration: 180 } }
                Label2 {
                    id: sizeLabel
                    anchors.centerIn: parent
                    color: JD.text1
                    font.features: { "tnum": 1 }
                    text: JD.videoResizing ? Math.round(JD.videoWidth) + " × " + Math.round(JD.videoWidth * 9 / 16)
                                           : JD.tr("Громкость") + " " + Math.round(JD.videoVolume * 100) + "%"
                }
            }
            Timer { id: volumeHint; interval: 1100 }
            Connections { target: JD; function onVideoVolumeChanged() { volumeHint.restart() } }

            // уголок: тянуть — менять размер кадра. Размер запоминается, когда его отпускают
            Item {
                anchors { right: parent.right; bottom: parent.bottom }
                width: 30; height: 30
                opacity: vv.chrome || JD.videoResizing ? 0.85 : 0
                visible: opacity > 0.01
                Behavior on opacity { NumberAnimation { duration: 200 } }
                Repeater {   // три косые чёрточки у самого угла, как у любого окна, которое можно тянуть
                    model: 3
                    Rectangle {
                        required property int index
                        readonly property real away: 6 + index * 5      // как далеко от угла
                        width: 7 + index * 6; height: 2; radius: 1
                        color: JD.text1
                        rotation: -45
                        x: 30 - away - width / 2
                        y: 30 - away - height / 2
                    }
                }
                MouseArea {
                    anchors.fill: parent
                    cursorShape: Qt.SizeFDiagCursor
                    property real fromX: 0
                    property real fromWidth: 0
                    onPressed: m => {
                        // от точки экрана, а не от своей: уголок уезжает вместе с краем кадра
                        fromX = mapToGlobal(m.x, m.y).x
                        fromWidth = JD.videoWidth
                        JD.videoResizing = true
                    }
                    // остров растёт в обе стороны от центра: край уходит на половину прибавки
                    onPositionChanged: m => { if (pressed) JD.setVideoWidth(fromWidth + 2 * (mapToGlobal(m.x, m.y).x - fromX)) }
                    onReleased: { JD.videoResizing = false; JD.saveVideoWidth() }
                    onCanceled: { JD.videoResizing = false; JD.saveVideoWidth() }
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
                    Ring { visible: !vv.hearing; size: 16; tint: JD.accentOrange }
                    Waveform { visible: vv.hearing; Layout.preferredWidth: 42; Layout.preferredHeight: 20 }
                    Label1 {
                        text: JD.answerOpen ? JD.answer
                            : vv.hearing ? (JD.activity || JD.tr("Слушаю…"))
                            : (JD.activity || JD.tr("Думаю…"))
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
                Label2 {
                    text: JD.dstate === "speaking" ? JD.tr("говорит")
                        : JD.dstate === "listening" ? JD.tr("слушает продолжение") : ""
                }
                Waveform {
                    visible: JD.dstate === "listening"
                    Layout.preferredWidth: 40; Layout.preferredHeight: 20
                }
                // Выделено что-то — кнопка забирает выделенное и остаётся на месте: человек
                // продолжает читать. Не выделено — забирает весь ответ и уходит, как раньше.
                IconButton {
                    icon: "edit-copy"; size: 26
                    onClicked: {
                        answerText.take()
                        if (!answerText.picked) JD.answerOpen = false
                    }
                }
            }
            Flickable {
                id: answerScroll
                Layout.fillWidth: true
                Layout.fillHeight: true
                contentHeight: answerText.implicitHeight
                clip: true
                // Тянуть мышью здесь значит выделять, а не листать: иначе Flickable перехватывает
                // движение на полпути, и выделение обрывается ровно там, где человек разогнался.
                // Листать остаётся колесо — им тут и листают.
                interactive: false
                WheelHandler {
                    onWheel: event => {
                        const room = Math.max(0, answerScroll.contentHeight - answerScroll.height)
                        answerScroll.contentY = Math.max(0, Math.min(room,
                            answerScroll.contentY - event.angleDelta.y))
                        event.accepted = true
                    }
                }
                SelectableText {
                    id: answerText
                    width: parent.width
                    text: JD.answer
                    TextSwap on text {}
                }

                // Кнопка у самого выделения, а не только в заголовке. Выделяют в середине длинного
                // ответа, и путь «выдели — доведи курсор до угла карточки — нажми» длиннее самого
                // выделения. Так это сделано везде, где текст выделяют мышью, и по той же причине.
                Rectangle {
                    id: pickCopy
                    parent: answerScroll
                    visible: answerText.picked
                    width: pickRow.implicitWidth + 20
                    height: 28
                    radius: 14
                    z: 3
                    color: Qt.rgba(0, 0, 0, 0.92)
                    border.width: 1
                    border.color: Qt.rgba(1, 1, 1, 0.16)
                    x: Math.max(0, Math.min(answerScroll.width - width, answerText.pickRect.x - 10))
                    y: Math.max(0, answerText.pickRect.y - answerScroll.contentY - height - 6)
                    Row {
                        id: pickRow
                        anchors.centerIn: parent
                        spacing: 7
                        Icon { anchors.verticalCenter: parent.verticalCenter; name: "edit-copy"; implicitSize: 14 }
                        Label1 { anchors.verticalCenter: parent.verticalCenter; text: JD.tr("Скопировать"); font.pixelSize: 12 }
                    }
                    HoverHandler { cursorShape: Qt.PointingHandCursor }
                    TapHandler {
                        gesturePolicy: TapHandler.ReleaseWithinBounds
                        onTapped: answerText.take()
                    }
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
        property int openLetter: 0           // номер раскрытого письма в списке почты, 0 — все свёрнуты
        onCChanged: openLetter = 0
        // Цвет кружка от всего адреса, а не от первой буквы: у «Google», «Gmail» и «GitHub» он был
        // один и тот же, и список выглядел набором повторов.
        function hue(s) {
            let h = 7
            for (let i = 0; i < (s || "").length; i++) h = (h * 31 + s.charCodeAt(i)) % 360
            return h / 360
        }
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
                                          && (cv.c.options || []).every(o => !!o.icon || !!o.thumb)
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
                            // Вариант с картинкой — выбор песни: узнать обложку быстрее,
                            // чем прочитать название, особенно когда названия похожи.
                            Rectangle {
                                visible: !!modelData.thumb
                                Layout.fillWidth: true
                                Layout.preferredHeight: width * 9 / 16
                                radius: 10
                                clip: true
                                color: JD.fill2
                                Image {
                                    anchors.fill: parent
                                    source: modelData.thumb || ""
                                    fillMode: Image.PreserveAspectCrop
                                    asynchronous: true
                                    cache: true
                                }
                            }
                            Icon { visible: !modelData.thumb; name: modelData.icon; implicitSize: 26; Layout.alignment: Qt.AlignHCenter }
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
                // Нажатие раскрывает письмо прямо в списке. Раньше оно просило «прочитай письмо
                // номер N» — Джарвис начинал читать вслух, а глазами посмотреть было нечего.
                Rectangle {
                    id: letterRow
                    required property var modelData
                    readonly property bool open: cv.openLetter === modelData.n
                    Layout.fillWidth: true
                    implicitHeight: letterCol.implicitHeight + 18
                    radius: 12
                    clip: true
                    color: rowHover.hovered && !open ? JD.fill2 : JD.fill1
                    Behavior on color { ColorAnimation { duration: 120 } }
                    Behavior on implicitHeight { NumberAnimation { duration: JD.dur(200); easing.type: Easing.OutCubic } }
                    ColumnLayout {
                        id: letterCol
                        anchors { left: parent.left; right: parent.right; top: parent.top; topMargin: 9; leftMargin: 12; rightMargin: 12 }
                        spacing: 8
                        RowLayout {
                            Layout.fillWidth: true
                            spacing: 10
                            Rectangle {
                                implicitWidth: 26; implicitHeight: 26; radius: 13
                                color: Qt.hsla(cv.hue(letterRow.modelData.address || letterRow.modelData.from), 0.5, 0.45, 1)
                                Text { font.family: JD.fontFamily; anchors.centerIn: parent; text: (letterRow.modelData.from || "?").charAt(0).toUpperCase(); color: "white"; font.pixelSize: 12; font.weight: Font.Bold }
                            }
                            // Пустая тема не занимает строку: иначе имя отправителя прилипало к
                            // верху, а кружок стоял по центру — ряд выглядел съехавшим.
                            ColumnLayout {
                                spacing: 1
                                Layout.fillWidth: true
                                Label1 { text: letterRow.modelData.from; font.pixelSize: 12; Layout.fillWidth: true }
                                Label2 {
                                    visible: !!letterRow.modelData.subject
                                    text: letterRow.modelData.subject || ""
                                    Layout.fillWidth: true
                                    wrapMode: letterRow.open ? Text.Wrap : Text.NoWrap
                                    maximumLineCount: letterRow.open ? 3 : 1
                                }
                            }
                            Icon {
                                name: "chevron-down"; implicitSize: 14; tint: JD.text3
                                rotation: letterRow.open ? 180 : 0
                                Behavior on rotation { NumberAnimation { duration: JD.dur(200); easing.type: Easing.OutCubic } }
                            }
                        }
                        Label2 {
                            visible: letterRow.open
                            text: letterRow.modelData.preview || JD.tr("Текста в письме нет.")
                            color: JD.text1
                            wrapMode: Text.Wrap
                            maximumLineCount: 9
                            lineHeight: 1.15
                            Layout.fillWidth: true
                            Layout.leftMargin: 36
                        }
                        RowLayout {
                            visible: letterRow.open
                            Layout.leftMargin: 36
                            Layout.bottomMargin: 2
                            spacing: 8
                            PillButton { label: JD.tr("Прочитать вслух"); onClicked: JD.send({ cmd: "type", text: JD.tr("прочитай письмо номер ") + letterRow.modelData.n }) }
                            PillButton { label: JD.tr("Открыть в браузере"); onClicked: JD.send({ cmd: "type", text: JD.tr("открой письмо номер ") + letterRow.modelData.n + JD.tr(" в браузере") }) }
                        }
                    }
                    HoverHandler { id: rowHover; cursorShape: Qt.PointingHandCursor }
                    TapHandler { onTapped: cv.openLetter = letterRow.open ? 0 : letterRow.modelData.n }
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
            { cmd: "/resume", title: JD.videoLast && JD.videoLast.in_window ? JD.tr("Вернуть видео в островок") : JD.tr("Продолжить ролик"),
              icon: "circle-play", run: () => { if (JD.videoLast && JD.videoLast.in_window) JD.videoPopin(); else JD.videoResume() } },
            { cmd: "/music", title: JD.tr("Сделать музыку"), icon: "audio-x-generic", fill: JD.tr("Сделай трек: ") },
            { cmd: "/install", title: JD.tr("Установить программу"), icon: "system-software-install", fill: JD.tr("Установи ") },
            { cmd: "/screen", title: JD.tr("Что на экране?"), icon: "view-preview", fill: JD.tr("Посмотри на экран и ") },
            { cmd: "/mic", title: JD.micOn ? JD.tr("Выключить микрофон (только текст)") : JD.tr("Включить микрофон"), icon: "audio-input-microphone",
              run: () => JD.run(["config", "set", "audio.microphone", String(!JD.micOn)]) },
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
    // a control-center toggle: a round icon that lights up, the name and its state
    component Tile: Rectangle {
        id: tile
        property string icon: ""
        property string title: ""
        property string onText: JD.tr("Вкл")
        property string offText: JD.tr("Выкл")
        property bool on: false
        property color tint: JD.accentBlue
        signal toggled()
        Layout.fillWidth: true
        Layout.preferredWidth: 1
        implicitHeight: 62
        radius: 18
        color: tileHover.hovered ? JD.fill2 : JD.fill1
        scale: tileTap.pressed ? 0.96 : 1
        Behavior on color { ColorAnimation { duration: 160 } }
        Behavior on scale { NumberAnimation { duration: 120 } }
        RowLayout {
            anchors { fill: parent; leftMargin: 11; rightMargin: 10 }
            spacing: 10
            Rectangle {
                implicitWidth: 38; implicitHeight: 38; radius: 19
                color: tile.on ? tile.tint : JD.fill2
                Behavior on color { ColorAnimation { duration: 200 } }
                Icon { anchors.centerIn: parent; name: tile.icon; implicitSize: 18 }
            }
            ColumnLayout {
                spacing: 0
                Layout.fillWidth: true
                Label1 { text: tile.title; font.pixelSize: 12; Layout.fillWidth: true }
                Label2 { text: tile.on ? tile.onText : tile.offText; font.pixelSize: 11; color: tile.on ? JD.text2 : JD.text3; Layout.fillWidth: true }
            }
        }
        HoverHandler { id: tileHover; cursorShape: Qt.PointingHandCursor }
        TapHandler { id: tileTap; onTapped: tile.toggled() }
    }

    component Chip: Rectangle {
        id: chip
        property string icon: ""
        property string label: ""
        property color tint: JD.fill1
        signal clicked()
        implicitWidth: chipRow.implicitWidth + 24
        implicitHeight: 34
        radius: 17
        color: chipHover.hovered ? Qt.lighter(tint === JD.fill1 ? "#262628" : tint, 1.2) : tint
        scale: chipTap.pressed ? 0.95 : 1
        Behavior on scale { NumberAnimation { duration: 120 } }
        Behavior on color { ColorAnimation { duration: 120 } }
        RowLayout {
            id: chipRow
            anchors.centerIn: parent
            spacing: 7
            Icon { visible: !!chip.icon; name: chip.icon; implicitSize: 15 }
            Label1 { text: chip.label; font.pixelSize: 12; font.weight: Font.Medium }
        }
        HoverHandler { id: chipHover; cursorShape: Qt.PointingHandCursor }
        TapHandler { id: chipTap; onTapped: chip.clicked() }
    }

    // one row of the sound card: icon (a tap mutes) · name · a track to drag or click · the level
    component VolumeRow: Item {
        id: vr
        property real value: 0          // 0…1
        property string icon: "audio-volume-high"
        property string label: ""
        property color tint: JD.accentBlue
        property real dragValue: -1
        signal moved(real v)
        signal muteToggled()
        readonly property real shown: dragValue >= 0 ? dragValue : Math.max(0, Math.min(1, value))
        Layout.fillWidth: true
        implicitHeight: 30
        RowLayout {
            anchors.fill: parent
            spacing: 10
            Rectangle {
                implicitWidth: 30; implicitHeight: 30; radius: 15
                color: vrMute.containsMouse ? JD.fill2 : "transparent"
                Icon { anchors.centerIn: parent; name: vr.shown === 0 ? "audio-volume-muted" : vr.icon; implicitSize: 16; tint: vr.tint }
                MouseArea { id: vrMute; anchors.fill: parent; hoverEnabled: true; cursorShape: Qt.PointingHandCursor; onClicked: vr.muteToggled() }
            }
            Label1 { text: vr.label; font.pixelSize: 13; font.weight: Font.Medium; Layout.preferredWidth: 86 }
            Item {
                id: vrTrack
                Layout.fillWidth: true
                implicitHeight: 30
                readonly property bool active: vrHover.hovered || vr.dragValue >= 0
                Rectangle {
                    id: rail
                    anchors.verticalCenter: parent.verticalCenter
                    width: parent.width
                    height: vrTrack.active ? 8 : 6
                    radius: height / 2
                    color: JD.fill2
                    Behavior on height { NumberAnimation { duration: 120 } }
                    Rectangle {
                        width: rail.width * vr.shown
                        height: parent.height
                        radius: parent.radius
                        color: vr.tint
                        Behavior on width { enabled: vr.dragValue < 0; NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
                    }
                }
                // the knob: where the level is, and something to take hold of
                Rectangle {
                    width: vrTrack.active ? 18 : 14; height: width; radius: width / 2
                    x: Math.max(0, Math.min(vrTrack.width - width, vrTrack.width * vr.shown - width / 2))
                    anchors.verticalCenter: parent.verticalCenter
                    color: "#f5f5f7"
                    Behavior on width { NumberAnimation { duration: 120 } }
                    Behavior on x { enabled: vr.dragValue < 0; NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
                }
                HoverHandler { id: vrHover; cursorShape: Qt.PointingHandCursor }
                MouseArea {
                    anchors.fill: parent
                    function at(x) { return Math.max(0, Math.min(1, x / width)) }
                    onPressed: m => { vr.dragValue = at(m.x); vr.moved(vr.dragValue) }
                    onPositionChanged: m => { if (pressed) { vr.dragValue = at(m.x); vr.moved(vr.dragValue) } }
                    onReleased: { vr.moved(vr.dragValue); vr.dragValue = -1 }
                }
            }
            Label2 {
                text: Math.round(vr.shown * 100) + "%"
                color: JD.text2; font.pixelSize: 12; font.features: { "tnum": 1 }
                horizontalAlignment: Text.AlignRight; Layout.preferredWidth: 38
            }
        }
    }

    component SectionLabel: Text {
        font.family: JD.fontFamily
        font.pixelSize: 11
        font.weight: Font.DemiBold
        font.letterSpacing: 0.6
        color: JD.text3
    }

    // ───────────── the control center (a click on the island) ─────────────
    component ExpandedView: View {
        id: ev
        property string pendingProvider: ""
        property int voiceWas: 0   // the level the mute button came from, for the way back
        property int musicWas: 0
        readonly property var player: JD.playerInExpanded ? JD.musicPlayer : null
        readonly property var sink: Pipewire.defaultAudioSink
        PwObjectTracker { objects: ev.sink ? [ev.sink] : [] }
        implicitWidth: 740
        implicitHeight: Math.min(col.implicitHeight + 40, 800)
        SystemClock { id: evClock; precision: SystemClock.Minutes }

        function setting(key, value) { JD.run(["config", "set", key, String(value)]) }
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

        ColumnLayout {
            id: col
            x: 20
            y: 20
            width: evFlick.width - 40
            spacing: 14

            // ── header: who, what it is doing · time, date, weather · settings
            RowLayout {
                spacing: 14
                Ring { size: 36 }
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
                            : ({ idle: JD.micOn ? JD.tr("Готов · скажите имя или ") + (JD.hotkeys.talk || "Meta+J") : JD.tr("Готов · ") + (JD.hotkeys.type || "Meta+K"),
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
                IconButton {
                    icon: JD.muted ? "audio-volume-muted" : "audio-volume-high"
                    size: 32
                    onClicked: JD.setMuted(!JD.muted)
                }
                IconButton { icon: "gauge"; size: 32; onClicked: JD.openTools("emoji") }
                IconButton { icon: "configure"; size: 32; onClicked: JD.openSettings("general") }
                IconButton { icon: "window-close"; size: 32; onClicked: JD.expanded = false }
            }

            // update available
            Rectangle {
                visible: !!JD.update
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
                Layout.fillWidth: true
                implicitHeight: 46
                radius: 23
                color: askHover.hovered ? JD.fill2 : JD.fill1
                Behavior on color { ColorAnimation { duration: 120 } }
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
                spacing: 12
                Rectangle {
                    id: np
                    readonly property bool own: JD.musicOn
                    readonly property bool any: own || !!ev.player
                    readonly property var p: JD.player || ({})
                    property color tint: own ? JD.artTint(p.color) : JD.accentPink
                    Behavior on tint { ColorAnimation { duration: 450; easing.type: Easing.OutCubic } }
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
                                    Behavior on height { NumberAnimation { duration: 120 } }
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
                                gradient: Gradient {
                                    GradientStop { position: 0; color: "#fc3c44" }
                                    GradientStop { position: 1; color: "#bf5af2" }
                                }
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
                                   onClicked: { JD.expanded = false; JD.send({ cmd: "media_play", query: "~/Music/JustDay/YouTube", mode: "replace", shuffle: true }) } }
                        }
                    }
                }
                GridLayout {
                    Layout.fillWidth: true
                    Layout.preferredWidth: 1
                    columns: 2
                    rowSpacing: 12
                    columnSpacing: 12
                    Tile { icon: "audio-input-microphone"; title: JD.tr("Микрофон"); onText: JD.tr("голос и текст"); offText: JD.tr("только текст")
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
                }
            }

            // ── sound: the assistant, the music, the whole computer. Three knobs in one card, each one only
            //    moves what it names — turning the assistant down leaves every other app where it was.
            Rectangle {
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
                visible: !!JD.nextEvent
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
                        Behavior on color { ColorAnimation { duration: 180 } }
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
                spacing: 10
                Label2 { text: JD.tr("Модель сменится после перезапуска (текущий разговор начнётся заново)"); Layout.fillWidth: true }
                PillButton { label: JD.tr("Перезапустить"); tint: JD.accentBlue; onClicked: { JD.run(["restart"]); ev.pendingProvider = "" } }
            }

            // ── notifications | recent
            RowLayout {
                visible: (JD.notifications.length > 0 && JD.island.show_notifications !== false) || JD.history.length > 0
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
                    visible: JD.history.length > 0
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
        }
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
                    width: parent.width
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
                    flickSpeed: 0
                }
                readonly property bool shown: trayReveal.shown

                Item {
                    id: trayEdge
                    width: trayReveal.revealZone
                    height: parent.height
                    x: trayWin.atRight ? parent.width - width : 0
                    HoverHandler {
                        onPointChanged: if (trayReveal.needHide) trayReveal.onEdgePoint(point, trayEdge.width)
                        onHoveredChanged: if (hovered && trayReveal.needHide) trayReveal.onEdgeEntered()
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
                    Behavior on x { enabled: JD.animOn; NumberAnimation { duration: trayReveal.slideMs; easing.type: Easing.OutCubic } }
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
        BackgroundEffect.blurRegion: Region {
            x: Math.round(trayMenu.blurRect.x)
            y: Math.round(trayMenu.blurRect.y)
            width: trayMenuWin.blurLive && JD.blurOn ? Math.round(trayMenu.blurRect.w) : 0
            height: trayMenuWin.blurLive && JD.blurOn ? Math.round(trayMenu.blurRect.h) : 0
            radius: 14
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
                alive = true
                menuFadeOut.stop()
                blurLive = false
                menuBlurArm.restart()
            } else {
                menuFadeOut.restart()
                menuBlurArm.stop()
                blurLive = false
            }
        }
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
        // заменит: «поверх» глаз читает по тени, а не по цвету. Рисуется по пустому прямоугольнику
        // той же формы — саму карточку через эффект не пропустишь, она живая и принимает нажатия.
        Rectangle {
            id: menuShadowShape
            visible: false
            layer.enabled: true
            x: menuCard.x
            y: menuCard.y
            width: menuCard.width
            height: menuCard.height
            radius: menuCard.radius
            color: "#000000"
        }
        MultiEffect {
            source: menuShadowShape
            x: menuShadowShape.x
            y: menuShadowShape.y + 8
            width: menuShadowShape.width
            height: menuShadowShape.height
            blurEnabled: true
            blur: 1.0
            blurMax: 48
            opacity: (JD.menuOpen ? 0.5 : 0) * menuCard.opacity
            Behavior on opacity { enabled: JD.animOn; NumberAnimation { duration: 160 } }
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
                                     : Math.min(menuWin.width - 24, menuWin.cardW)
            height: JD.menuSearchMode
                    ? Math.min(menuWin.height - 48, Math.max(86, Math.min(760, wantH)))
                    : Math.min(menuWin.height - 24, menuWin.cardH)
            Behavior on height {
                enabled: JD.animOn && JD.menuSearchMode
                SpringAnimation { spring: 5; damping: 0.62; epsilon: 0.5 }
            }
            // От значка: меню стоит над ним, но не левее края экрана и не правее его.
            // Spotlight — по центру сверху, как macOS Spotlight, а не из дока.
            x: JD.menuSearchMode
                 ? (menuWin.width - width) / 2
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
                 : menuWin.fromDock
                 ? (menuWin.atTop ? fromEdge : menuWin.height - height - fromEdge)
                 : (menuWin.atTop ? 12 : menuWin.height - height - 12)
            radius: JD.menuSearchMode ? 24 : 22
            // Меню читают, а не рассматривают: карточка почти непрозрачная, и размытие под ней —
            // только чтобы её край не выглядел вырезанным из картона. Стекло на 74% выглядело
            // красиво ровно до первых светлых обоев, после которых половина кнопок пропадала.
            color: JD.blurOn ? JD.menuSurface : Qt.rgba(0.04, 0.04, 0.05, 0.99)
            border.width: 1
            border.color: Qt.rgba(1, 1, 1, 0.14)
            clip: true

            // Растёт от своего угла, а не из середины экрана: глаз уже там, где нажали.
            transformOrigin: JD.menuSearchMode ? Item.Top
                : menuWin.atTop
                ? (menuWin.side === "left" ? Item.TopLeft : menuWin.side === "right" ? Item.TopRight : Item.Top)
                : (menuWin.side === "left" ? Item.BottomLeft : menuWin.side === "right" ? Item.BottomRight : Item.Bottom)
            opacity: JD.menuOpen ? 1 : 0
            scale: JD.menuOpen ? 1 : 0.94
            Behavior on opacity { enabled: JD.animOn; NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
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
                visible: !JD.menuSearchMode
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
                    Behavior on opacity { enabled: JD.animOn; NumberAnimation { duration: 140 } }
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
                active: menuWin.alive
                sourceComponent: JD.menuSearchMode ? spotlightBody : menuBodyFull
            }
            Component { id: menuBodyFull; MenuView {} }
            Component { id: spotlightBody; SpotlightView {} }
        }
    }

}
