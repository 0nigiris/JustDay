// Трей: чужие значки — те, что программы кладут в системный лоток, — отдельной полосой у бокового края.
//
// Отдельной, а не в островке, по той же причине, по которой док отдельно от меню: лоток не наш. Его
// содержимое решают чужие программы, оно меняется само, и значки в нём нарисованы не в нашем стиле.
// Класть это внутрь островка значит пускать чужой набор значков в единственное место, где стиль
// выдержан до конца. Полоса же — просто полоса: она уважает то, что в ней лежит.
//
// Левая кнопка — то, что программа считает главным действием (activate). Правая — её собственное
// меню: пункты берутся у программы по DBusMenu, а рисуем их мы (TrayMenu). Системное меню
// Quickshell умеет показывать только в режиме QApplication, а мы работаем без QtWidgets — и раньше
// правая кнопка просто молчала.
import QtQuick
import QtQuick.Window
import QtQuick.Effects
import Qt5Compat.GraphicalEffects
import Quickshell
import Quickshell.Widgets
import Quickshell.Services.SystemTray

Item {
    id: tv

    readonly property real icon: JD.trayIconSize
    readonly property real pad: 8
    readonly property real cell: icon + 14
    readonly property bool atRight: JD.trayPlace === "right"

    // Icon wash: default original (no effect). auto only lightens truly black glyphs.
    // Forced light/clear/tinted/mono still available in settings.
    readonly property string iconStyle: {
        const w = String(JD.trayCfg.icon_style || "original").trim().toLowerCase()
        return ["original", "auto", "light", "clear", "tinted", "mono"].indexOf(w) >= 0 ? w : "original"
    }
    readonly property color iconTint: {
        const t = String(JD.trayCfg.icon_tint || "").trim()
        return t ? t : "#7AC8FF"
    }
    function trayLooksDark(item) {
        const s = [item.id, item.title, item.tooltipTitle, item.tooltipDescription].map(x => String(x || "")).join(" ").toLowerCase()
        // Only known solid-black glyphs. Do NOT force-wash Discord / Waywallen /
        // status icons — ColorOverlay on already-light SNI pixmaps leaves white
        // corner dots and a fuzzy halo around the silhouette.
        return /spotify|spotify-client|com\.spotify/.test(s)
    }
    // Branded / coloured tray glyphs — never ColorOverlay (even in forced light/clear).
    function trayKeepColor(item) {
        const s = [item.id, item.title, item.tooltipTitle, item.tooltipDescription, item.icon].map(x => String(x || "")).join(" ").toLowerCase()
        return /discord|waywallen|steam|telegram|chrome|firefox|chromium|slack|signal|element|vesktop/.test(s)
    }
    // probedKind: 0 keep colour, 2 near-black only (gray midtones left alone — MultiEffect washed them)
    function trayMode(item, probedKind) {
        const st = tv.iconStyle
        if (st === "original") return "none"
        if (tv.trayKeepColor(item)) return "none"
        if (st === "light" || st === "clear" || st === "tinted" || st === "mono") return st
        // auto: Soft ColorOverlay only for truly black icons (Spotify etc.)
        const kind = probedKind === undefined || probedKind === null ? 0 : probedKind
        if (kind >= 2 || tv.trayLooksDark(item)) return "soft"
        return "none"
    }
    function washColor(mode) {
        if (mode === "soft" || mode === "light") return "#F2F4F7"
        if (mode === "clear") return "#F7F8FA"
        if (mode === "tinted") return tv.iconTint
        if (mode === "mono") return "#C8CCD2"
        return "#F2F4F7"
    }
    // StatusNotifier icon URLs:
    //  - pixmap dump: "…/foo.png?path=/tmp/sni-xxx" → rewrite to file://path/foo.png
    //  - theme name:  "image://icon/name?path=/app/share/icons" → leave as-is;
    //    IconImage's icon provider searches that path (rewriting breaks Waywallen).
    function trayIconSource(icon) {
        const s = String(icon || "")
        if (!s) return ""
        // Discord MacTahoe/WhiteSur theme SVGs squash Clyde's eyes → stock PNG.
        // Keep real SNI pixmap dumps (muted/speaking status) untouched.
        const low = s.toLowerCase()
        if (/discord/.test(low)) {
            const isPixmap = (s.startsWith("file:") && /\.(png|jpg|jpeg|webp|gif|ico)/i.test(s))
                          || (s.startsWith("/") && /\.(png|jpg|jpeg|webp|gif|ico)$/i.test(s))
                          || (s.indexOf("?path=") >= 0 && /\.(png|jpg|jpeg|webp|gif|ico)/i.test(s.split("?path=")[0]))
            if (!isPixmap)
                return "file:///usr/share/icons/hicolor/256x256/apps/discord.png"
        }
        // Some SNIs put an absolute pixmap path in IconName (no image:// wrapper).
        if (s.startsWith("/") && /\.(png|svg|svgz|xpm|jpg|jpeg|webp|gif|ico)$/i.test(s))
            return "file://" + s
        if (s.indexOf("?path=") < 0) return s
        const chunks = s.split("?path=")
        const name = chunks[0]
        const path = chunks[1]
        if (!path) return s
        const fileName = name.substring(name.lastIndexOf("/") + 1)
        // Pixmap dump in a temp/theme folder → real file.
        if (fileName && /\.(png|svg|svgz|xpm|jpg|jpeg|webp|gif|ico)$/i.test(fileName))
            return "file://" + path + "/" + fileName
        // Theme id (org.waywallen.waywallen, steam_tray_mono, …): resolve to a
        // real SVG/PNG via the icon theme. Vectors scale cleanly — no AA halo.
        if (fileName) {
            try {
                const resolved = Quickshell.iconPath(fileName, "")
                if (resolved) return resolved
            } catch (e) { /* fall through */ }
        }
        // Last resort: original SNI URL (image://icon/name?path=…).
        return s
    }
    // Render size: device pixels for the calm icon, plus magnify headroom so
    // scale transforms never upsample a soft bitmap.
    function trayIconPx() {
        const dpr = Math.max(1, (typeof Screen !== "undefined" && Screen.devicePixelRatio) ? Screen.devicePixelRatio : 1)
        return Math.max(16, Math.round(tv.icon * dpr * (1 + Math.max(0, tv.amp))))
    }

    // Показываем всё, что в лотке есть. KDE прячет «пассивные» значки во всплывающий ящик, но
    // «мой значок пропал» — худшая новость, какую может принести полоса лотка: человек не знает,
    // программа умерла или это оболочка решила за него.
    // Показываем всё, кроме того, что попросили спрятать. «Мой значок пропал» — худшая новость,
    // какую может принести полоса лотка, поэтому сама она ничего не решает: список спрятанного
    // ведёт человек, и каждый значок в нём виден в настройках.
    readonly property var items: SystemTray.items.values.filter(i => !!i && JD.trayShows(i))
    readonly property bool empty: items.length === 0

    // ───────────── увеличение, как в доке ─────────────
    //
    // Тот же движок, повёрнутый на бок. Полоса лотка — такая же сплошная поверхность, и отвечать на
    // курсор она должна так же: ближний значок растёт, соседи подхватывают волну, все расступаются.
    // Разводить два разных поведения у двух соседних полос — верный способ получить оболочку,
    // которая ведёт себя по-разному в зависимости от того, куда попал курсор.
    //
    // Математика здесь проще, чем в доке: все ячейки одинаковые, разделителей нет. Но два подвоха
    // те же. Первый: цель нельзя считать по нарисованному — выйдет петля и дрожь, поэтому курсор
    // переводится обратно в спокойные координаты полосы. Второй: полоса, расширяясь, ещё и
    // переезжает (она центрирована), и это обязано войти в обратный перевод.
    readonly property bool magnify: JD.trayCfg.magnify === undefined ? JD.dockCfg.magnify !== false
                                                                     : JD.trayCfg.magnify !== false
    readonly property real amp: Math.max(0, Math.min(2, (JD.trayCfg.magnify_scale === undefined
        ? (JD.dockCfg.magnify_scale === undefined ? 80 : JD.dockCfg.magnify_scale)
        : JD.trayCfg.magnify_scale) / 100))
    readonly property real spread: Math.max(0.4, Math.min(6, (JD.trayCfg.magnify_spread === undefined
        ? (JD.dockCfg.magnify_spread === undefined ? 200 : JD.dockCfg.magnify_spread)
        : JD.trayCfg.magnify_spread) / 100))
    readonly property string animStyle: JD.dockCfg.animation || "spring"
    // Tray hover must stay calm: full-screen paint + per-frame re-layout thrash
    // when spring is dock-stiff. Cap K, overdamp, and prefer smooth when possible.
    readonly property real springK: Math.max(10, Math.min(140, JD.dockCfg.spring === undefined ? 90 : Math.min(JD.dockCfg.spring, 140)))
    readonly property real springDamp: animStyle === "smooth" ? 1.0
        : Math.max(0.88, Math.min(1, JD.dockCfg.damping === undefined ? 0.97 : Math.max(JD.dockCfg.damping, 0.92)))

    property real pointerScene: -99999   // курсор по вертикали, в координатах окна
    property bool engaged: false
    property int tick: 0
    property var sizes: []
    property var speeds: []
    property real anchorMiddle: 0        // середина, вокруг которой растёт полоса; ставит окно

    function resetPhysics() {
        const n = cells
        const s = sizes.length === n ? sizes.slice() : []
        const v = speeds.length === n ? speeds.slice() : []
        while (s.length < n) { s.push(1); v.push(0) }
        sizes = s; speeds = v; tick++
    }
    onCellsChanged: resetPhysics()
    Component.onCompleted: resetPhysics()

    // Раскладка — такая же ячейка полосы, как значок: она стоит первой и живёт по тем же правилам,
    // включая увеличение под курсором. Отдельная плашка сбоку выглядела бы приклеенной.
    readonly property bool showLayout: JD.trayCfg.layout !== false && !!JD.layoutShort
    readonly property int extras: showLayout ? 1 : 0
    readonly property int cells: items.length + extras

    readonly property real restLength: pad * 2 + cells * cell
    // Rest chrome size (no magnify). PanelWindow uses these + headroom so the
    // invisible layer is content-sized, not a full-edge fence — exclusive/magnet
    // stay on the real strip outline.
    readonly property real restWidth: icon + pad * 2
    readonly property real magExtra: Math.round(cell * amp * spread * 1.8) + 16
    readonly property real sideExtra: Math.round(icon * Math.max(amp, 0.4)) + 10

    // Куда курсор попадает в спокойных координатах полосы. Решаем уравнение: ищем место u, которое
    // при своих же размерах рисуется ровно под курсором.
    function solveRest(scene) {
        let u = scene - anchorMiddle + restLength / 2 - pad
        for (let step = 0; step < 7; step++) {
            let total = pad * 2, before = pad
            for (let i = 0; i < cells; i++) {
                const at = pad + i * cell
                const k = targetSize(i, u), h = cell * k
                total += h
                if (u >= at + cell) before += h
                else if (u > at) before += (u - at) * k
            }
            const err = scene - (anchorMiddle - total / 2 + before)
            if (Math.abs(err) < 0.2) break
            u += err / (1 + amp * 0.5)
        }
        return u
    }
    function restUnderPointer() { return engaged ? solveRest(pointerScene) : -99999 }
    function targetSize(i, u) {
        // Language / layout chip: never magnify — its outline looks broken when it lifts.
        if (i < extras) return 1
        if (!magnify || u < -9000) return 1
        const d = (pad + i * cell + cell / 2 - u) / (cell * spread)
        return 1 + amp * Math.exp(-d * d)
    }
    function stepPhysics(dt) {
        // Cap dt so a hitch cannot overshoot; settle thresholds are looser than the
        // dock so slow pointer travel between icons does not keep the lane buzzing.
        dt = Math.max(0.001, Math.min(0.024, dt))
        const u = restUnderPointer()
        const s = sizes, v = speeds
        const omega = Math.sqrt(springK)
        const c = 2 * springDamp * omega
        let moving = false
        for (let i = 0; i < cells; i++) {
            const t = targetSize(i, u)
            v[i] += (-(s[i] - t) * springK - c * v[i]) * dt
            s[i] += v[i] * dt
            // Snap when close — kills residual micro-oscillation / jitter.
            if (Math.abs(t - s[i]) < 0.004 && Math.abs(v[i]) < 0.01) {
                s[i] = t; v[i] = 0
            } else if (Math.abs(t - s[i]) > 0.004 || Math.abs(v[i]) > 0.01) {
                moving = true
            }
        }
        tick++
        return moving
    }
    FrameAnimation {
        id: physics
        running: false
        onTriggered: if (!tv.stepPhysics(frameTime)) running = false
    }
    function wake() {
        if (JD.animOn && animStyle !== "instant") physics.running = true
        else { physics.running = false; instantly() }
    }
    function instantly() {
        const u = restUnderPointer()
        for (let i = 0; i < cells; i++) { sizes[i] = targetSize(i, u); speeds[i] = 0 }
        tick++
    }

    // Места ячеек считаются из тех же размеров, что и рисуются, — поэтому нарисованное и занятое
    // место совпадают всегда, и наложиться значки не могут в принципе.
    readonly property var geom: {
        tick
        const out = []
        let at = pad
        for (let i = 0; i < cells; i++) {
            const k = sizes[i] === undefined ? 1 : sizes[i]
            const h = cell * k
            out.push({ y: at, h: h, k: k })
            at += h
        }
        return out
    }
    readonly property real laneLength: geom.length ? geom[geom.length - 1].y + geom[geom.length - 1].h + pad : restLength

    implicitWidth: icon + pad * 2
    // Коробка полосы не растёт под курсором, хотя значки в ней растут.
    //
    // Раньше высота равнялась длине ряда, а ряд удлинялся от увеличения: наводишь на значок —
    // полоса вырастает, её края разъезжаются, и она уезжает по рабочему столу из-под курсора.
    // Целиться в неё было тем труднее, чем ближе к ней подводишь руку. Теперь коробка стоит на
    // месте всегда, а выросшие значки по краям чуть выходят за неё — ровно так же, как значки
    // поднимаются над полосой дока на макоси.
    implicitHeight: Math.max(cell, restLength)

    // Проверка движка без мыши: поставить курсор в точку спокойной полосы, дать физике сойтись и
    // вернуть получившуюся раскладку. Синтетическая мышь на вейланде врёт, а «значки расступаются»
    // иначе никак не проверить числом.
    function probe(at) {
        const wasEngaged = engaged, wasAt = pointerScene
        engaged = true
        pointerScene = anchorMiddle - restLength / 2 + at
        for (let n = 0; n < 400 && stepPhysics(1 / 120); n++) { /* до схождения */ }
        let overlap = 0
        for (let i = 1; i < geom.length; i++)
            if (geom[i].y + 0.5 < geom[i - 1].y + geom[i - 1].h) overlap++
        const out = { at: at, u: Math.round(restUnderPointer()), rest: Math.round(restLength),
                      length: Math.round(laneLength), amp: amp, overlap: overlap,
                      cells: geom.map((g, i) => ({ y: Math.round(g.y), h: Math.round(g.h),
                                                   k: Number(g.k.toFixed(3)) })) }
        engaged = wasEngaged
        pointerScene = wasAt
        wake()
        return out
    }

    readonly property Rectangle blurItem: strip

    Rectangle {
        id: strip
        anchors.fill: parent
        radius: Math.round(tv.implicitWidth * 0.34)
        color: Qt.rgba(0, 0, 0, JD.blurOn ? 0.4 : 0.82)
        // Без обводки. Полоса лотка узкая, и светлая черта по её краю на тёмных обоях читается
        // как вторая, лишняя граница рядом с краем значков — а на светлых просто мусорит.
        // Форму ей задаёт тёмная заливка, этого хватает.
        border.width: 0

        // Курсор берём в координатах сцены нарочно: в координатах полосы он «двигался» бы сам,
        // когда она под ним растёт и переезжает, — и получилась бы обратная связь.
        HoverHandler {
            id: laneHover
            onPointChanged: {
                const y = point.scenePosition.y
                // Wider deadzone: slow travel between icons was waking physics every
                // pixel and made the magnify halo thrash.
                if (tv.engaged && Math.abs(y - tv.pointerScene) < 6.0) return
                tv.pointerScene = y
                tv.wake()
            }
            onHoveredChanged: {
                tv.engaged = hovered
                if (hovered) tv.pointerScene = point.scenePosition.y
                else tv.hint = ""
                tv.wake()
            }
        }

        Item {
            anchors.fill: parent

            // ───────────── раскладка ─────────────
            //
            // Первой ячейкой, по тем же правилам, что и значки: растёт под курсором, нажимается,
            // живёт в той же полосе. Две буквы — всё, что нужно: «RU» и «EN» различаются с одного
            // взгляда, а полное имя раскладки в полосу шириной с значок не влезет и не нужно.
            Item {
                visible: tv.showLayout
                readonly property var g: tv.geom[0] || ({ y: tv.pad, h: tv.cell, k: 1 })
                x: (parent.width - tv.cell) / 2
                y: g.y
                width: tv.cell
                height: g.h

                // Fixed chrome — never follow magnify (outline would "lift" and look broken).
                Rectangle {
                    anchors.centerIn: parent
                    width: tv.icon + 10
                    height: width
                    radius: width * 0.3
                    color: layoutHover.hovered ? JD.fill2 : JD.fill1
                    Behavior on color { enabled: JD.animOn; ColorAnimation { duration: 120 } }
                }
                Text {
                    anchors.centerIn: parent
                    text: JD.layoutShort
                    color: JD.text1
                    font.family: JD.fontFamily
                    font.pixelSize: tv.icon * 0.5
                    font.weight: Font.Bold
                }

                HoverHandler {
                    id: layoutHover
                    cursorShape: Qt.PointingHandCursor
                    onHoveredChanged: {
                        if (!hovered) { tv.hint = ""; return }
                        tv.hint = JD.layout ? JD.layout.name : ""
                        tv.hintY = parent.y + parent.height / 2
                    }
                }
                TapHandler {
                    gesturePolicy: TapHandler.ReleaseWithinBounds
                    onTapped: JD.layoutNext()
                }
                WheelHandler { onWheel: event => { JD.layoutNext(); event.accepted = true } }
            }

            Repeater {
                model: tv.items
                delegate: Item {
                    id: slot
                    required property var modelData
                    required property int index
                    readonly property int cell: index + tv.extras
                    readonly property var g: tv.geom[cell] || ({ y: tv.pad + cell * tv.cell, h: tv.cell, k: 1 })
                    x: (parent.width - tv.cell) / 2
                    y: g.y
                    width: tv.cell
                    height: g.h

                    // No circular backplate under app icons: SNI pixmaps (Discord and friends)
                    // already bring their own plate; a second fill1 disk read as a broken badge.
                    // Размер уже посчитан шагом физики — здесь только показываем. Своей анимации
                    // тут быть не должно: она разошлась бы с раскладкой, и значки бы налезли.
                    // Растр просят с запасом: увеличенный значок, нарисованный по обычному
                    // размеру, расплывается.
                    // Crisp SNI icons without IconImage: Quickshell IconImage rewrites
                    // "image://icon/name?path=/theme" into a broken file:// path
                    // (Waywallen → file:///app/share/icons/org.waywallen.waywallen).
                    // Use Image with the original SNI URL; only rewrite real pixmap dumps
                    // (basename has an extension). No mipmap; DPR-aware sourceSize;
                    // ColorOverlay only for black-glyph wash — never on Discord/Waywallen.
                    // No backplate / hover disk under tray glyphs — SNI icons already
                    // bring their own art; a fill disk read as a broken badge.
                    // Наведение: рамка вокруг самого значка, а не пузырь под ним.
                    //
                    // Пузырь — это заливка размером с ячейку: она больше значка, живёт своей
                    // жизнью и читается как второй, сломанный значок под первым. Рамка обводит то,
                    // на что человек смотрит, растёт вместе с ним и ничего собой не закрывает.
                    // Кому и она лишняя — выключается в настройках, тогда остаются одни значки.
                    Rectangle {
                        visible: slotHover.hovered && JD.trayCfg.hover_frame !== false
                        anchors.centerIn: parent
                        width: tv.icon * slot.g.k + 10
                        height: tv.icon * slot.g.k + 10
                        radius: Math.round(height * 0.3)
                        color: "transparent"
                        border.width: 1
                        border.color: Qt.rgba(1, 1, 1, slotTap.pressed ? 0.34 : 0.22)
                        Behavior on border.color { enabled: JD.animOn; ColorAnimation { duration: 120 } }
                        opacity: slotHover.hovered ? 1 : 0
                        Behavior on opacity { enabled: JD.animOn; NumberAnimation { duration: 120 } }
                    }

                    Item {
                        id: trayIconWrap
                        anchors.centerIn: parent
                        width: tv.icon
                        height: tv.icon
                        z: 1
                        scale: slot.g.k * (slotTap.pressed ? 0.88 : 1)
                        transformOrigin: tv.atRight ? Item.Right : Item.Left
                        // Smooth scale without fighting the physics tick (no Behavior on
                        // the spring-driven k — only press feedback is animated).
                        Behavior on scale {
                            enabled: JD.animOn && slotTap.pressed
                            NumberAnimation { duration: 90; easing.type: Easing.OutCubic }
                        }
                        property int probedKind: 0   // 0 keep, 2 truly black
                        readonly property string mode: tv.trayMode(slot.modelData, probedKind)
                        readonly property bool wash: mode !== "none"
                        readonly property string src: tv.trayIconSource(slot.modelData.icon)
                        readonly property int px: tv.trayIconPx()
                        Image {
                            id: trayIconSrc
                            anchors.fill: parent
                            source: trayIconWrap.src
                            sourceSize: Qt.size(trayIconWrap.px, trayIconWrap.px)
                            fillMode: Image.PreserveAspectFit
                            mipmap: false
                            smooth: true
                            antialiasing: true
                            // No layer.enabled — offscreen round-trip was the laggy "halo".
                            visible: !trayIconWrap.wash
                            asynchronous: false
                            onStatusChanged: if (status === Image.Ready && tv.iconStyle === "auto") trayProbe.requestPaint()
                            onSourceChanged: {
                                trayIconWrap.probedKind = 0
                                if (status === Image.Ready && tv.iconStyle === "auto") trayProbe.requestPaint()
                            }
                        }
                        Canvas {
                            id: trayProbe
                            width: 16
                            height: 16
                            visible: false
                            onPaint: {
                                if (tv.iconStyle !== "auto") return
                                if (trayIconSrc.status !== Image.Ready) return
                                const ctx = getContext("2d")
                                if (!ctx) return
                                ctx.clearRect(0, 0, width, height)
                                try { ctx.drawImage(trayIconSrc, 0, 0, width, height) } catch (e) { return }
                                let data
                                try { data = ctx.getImageData(0, 0, width, height) } catch (e) { return }
                                if (!data || !data.data) return
                                let sumLum = 0, sumSat = 0, n = 0
                                const px = data.data
                                for (let i = 0; i < px.length; i += 4) {
                                    const a = px[i + 3]
                                    if (a < 40) continue
                                    const r = px[i] / 255, g = px[i + 1] / 255, b = px[i + 2] / 255
                                    const mx = Math.max(r, g, b), mn = Math.min(r, g, b)
                                    const lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
                                    const sat = mx > 0.001 ? (mx - mn) / mx : 0
                                    sumLum += lum; sumSat += sat; n++
                                }
                                if (n < 3) { trayIconWrap.probedKind = 0; return }
                                const al = sumLum / n, as = sumSat / n
                                if (as < 0.22 && al < 0.22) trayIconWrap.probedKind = 2
                                else trayIconWrap.probedKind = 0
                            }
                        }
                        Image {
                            id: trayIconFxSrc
                            anchors.fill: parent
                            source: trayIconWrap.wash ? trayIconWrap.src : ""
                            sourceSize: Qt.size(trayIconWrap.px, trayIconWrap.px)
                            fillMode: Image.PreserveAspectFit
                            mipmap: false
                            smooth: true
                            antialiasing: true
                            visible: false
                            asynchronous: false
                        }
                        ColorOverlay {
                            anchors.fill: parent
                            visible: trayIconWrap.wash
                            source: trayIconFxSrc
                            color: tv.washColor(trayIconWrap.mode)
                            cached: false
                        }
                    }

                    // Программа просит внимания — оранжевая точка. Это единственное, что полоса
                    // говорит своими словами: всё остальное в ней нарисовано чужими руками.
                    Rectangle {
                        visible: slot.modelData.status === Status.NeedsAttention
                        width: 6
                        height: 6
                        radius: 3
                        color: JD.accentOrange
                        x: tv.atRight ? 2 : parent.width - width - 2
                        y: 3
                    }

                    HoverHandler {
                        id: slotHover
                        cursorShape: Qt.PointingHandCursor
                        onHoveredChanged: {
                            if (!hovered) { tv.hint = ""; return }
                            tv.hint = slot.modelData.tooltipTitle || slot.modelData.title || slot.modelData.id || ""
                            tv.hintY = slot.y + slot.height / 2
                        }
                    }
                    // Значок, у которого есть только меню (onlyMenu), по левой кнопке тоже открывает
                    // меню: у него нет главного действия, и молчать в ответ на щелчок — сломанный значок.
                    TapHandler {
                        id: slotTap
                        gesturePolicy: TapHandler.ReleaseWithinBounds
                        onTapped: {
                            const it = slot.modelData
                            // Меню соседнего значка, если оно открыто, закрывается само: полоса
                            // остаётся нажимаемой из-под меню, и щелчок по ней — это работа со
                            // значком, а не с чужим меню.
                            JD.closeTrayMenu()
                            if (it.onlyMenu && it.hasMenu) tv.showMenu(it, slot)
                            else it.activate()
                        }
                    }
                    // Правая кнопка — меню самой программы, оно тут главное. Спрятать значок —
                    // Ctrl и правая кнопка: редкое действие не должно занимать частый жест. Здесь
                    // MouseArea, а не TapHandler: только она честно отдаёт зажатые модификаторы.
                    MouseArea {
                        anchors.fill: parent
                        acceptedButtons: Qt.RightButton
                        onClicked: mouse => {
                            const it = slot.modelData
                            if (mouse.modifiers & Qt.ControlModifier) JD.trayHideItem(it, true)
                            else tv.showMenu(it, slot)
                        }
                    }
                    TapHandler {
                        acceptedButtons: Qt.MiddleButton
                        gesturePolicy: TapHandler.ReleaseWithinBounds
                        onTapped: slot.modelData.secondaryActivate()
                    }
                    WheelHandler {
                        onWheel: event => slot.modelData.scroll(event.angleDelta.y, false)
                    }
                }
            }
        }
    }

    property string hint: ""
    // Menu grows from the strip edge beside the icon. Coordinates are screen-local: the menu
    // lives in its own full-screen layer, and the tray paint layer is full-screen too — so
    // mapToItem(null) is already screen-local (not a short content-sized panel).
    function showMenu(item, at) {
        if (!item || !item.hasMenu) return
        // Same icon again toggles closed — otherwise the only dismiss is clicking outside.
        if (JD.trayMenu === item) { JD.closeTrayMenu(); return }
        const p = at.mapToItem(null, tv.atRight ? 0 : at.width, at.height / 2)
        // Attachment X: outer edge of the icon (left tray → right of icon; right tray → left).
        const ax = Math.round(tv.atRight ? p.x : p.x + 8)
        const ay = Math.round(p.y)
        JD.openTrayMenu(item, ax, ay)
        tv.hint = ""
    }

    // Подпись рядом с полосой, а не поверх неё: полоса узкая, имя в неё не влезает.
    Rectangle {
        visible: tv.hint !== ""
        width: hintText.implicitWidth + 20
        height: 26
        radius: 13
        color: Qt.rgba(0, 0, 0, 0.82)
        border.width: 1
        border.color: Qt.rgba(1, 1, 1, 0.12)
        x: tv.atRight ? -width - 10 : tv.width + 10
        y: Math.max(0, Math.min(tv.height - height, tv.hintY - height / 2))
        Label1 { id: hintText; anchors.centerIn: parent; text: tv.hint }
    }
    property real hintY: tv.height / 2
}
