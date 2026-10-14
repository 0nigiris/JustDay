// Вынесено из shell.qml (Р-80).
import QtQuick
import Quickshell
import Quickshell.Wayland

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
    // Экран главного окна островка: «основной» для дока и лотка — тот, где островок.
    property var primaryScreen: null
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
            screen: trayLoader.primaryScreen
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
            screen: trayLoader.primaryScreen
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
            screen: trayLoader.primaryScreen
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
