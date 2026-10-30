// Вынесено из shell.qml (Р-80).
import QtQuick
import QtQuick.Controls
import Quickshell
import Quickshell.Wayland

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
    // Для IPC-зонда (menuState): что за карточка и какое тело в ней сейчас.
    readonly property alias card: menuCard
    readonly property string bodyKind: menuBody.sourceComponent === spotlightBody ? "spotlight" : "menu"
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

    // Две дырки на плашку и меню дока (ползунок громкости над значком): больше двух одновременно не бывает.
    Item {
        id: popHole0
        visible: false
        readonly property var r: JD.dockPopRects.length > 0 ? JD.dockPopRects[0] : null
        x: r ? r.x : 0; y: r ? r.y : 0; width: r ? r.w : 0; height: r ? r.h : 0
    }
    Item {
        id: popHole1
        visible: false
        readonly property var r: JD.dockPopRects.length > 1 ? JD.dockPopRects[1] : null
        x: r ? r.x : 0; y: r ? r.y : 0; width: r ? r.w : 0; height: r ? r.h : 0
    }

    mask: Region {
        item: menuBackdrop
        Region { item: dockHole; intersection: Intersection.Subtract }
        Region { item: trayHole; intersection: Intersection.Subtract }
        Region { item: popHole0; intersection: Intersection.Subtract }
        Region { item: popHole1; intersection: Intersection.Subtract }
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
