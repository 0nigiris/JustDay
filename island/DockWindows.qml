// Вынесено из shell.qml (Р-80).
import QtQuick
import Quickshell
import Quickshell.Wayland

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
    // Экран главного окна островка: «основной» для дока и лотка — тот, где островок.
    property var primaryScreen: null
    model: {
        if (!JD.dockOn) return []
        if ((JD.dockCfg.screens || "primary") !== "all") return dockVariants.primaryScreen ? [dockVariants.primaryScreen] : []
        return Quickshell.screens
    }
    delegate: Item {
        id: dockHost
        required property var modelData

        readonly property bool primary: !modelData || !dockVariants.primaryScreen || modelData === dockVariants.primaryScreen
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

            // Плашка с ползунком громкости и контекстное меню торчат над картой дока. Меню «Пуск» закрывает экран
            // слоем с дырками, и без дырки под них они были картинкой: ползунок виден, а нажать нельзя.
            Binding {
                target: JD
                when: dockHost.primary
                property: "dockPopRects"
                value: {
                    const out = []
                    for (const it of [dock.tipItem, dock.ctxItem]) {
                        if (!it || !it.visible || it.opacity < 0.05 || it.width < 1) continue
                        void (it.x + it.y + dock.x + dock.y)   // mapToItem не следит за положением: подписываемся на него сами
                        const p = it.mapToItem(null, 0, 0)
                        out.push({ x: p.x, y: p.y, w: it.width, h: it.height })
                    }
                    return out
                }
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
