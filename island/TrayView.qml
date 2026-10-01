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
import Quickshell
import Quickshell.Widgets
import Quickshell.Services.SystemTray

Item {
    id: tv

    readonly property real icon: JD.trayIconSize
    readonly property real pad: 8
    readonly property real cell: icon + 14
    readonly property bool atRight: JD.trayPlace === "right"

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
    readonly property real springK: Math.max(10, Math.min(600, JD.dockCfg.spring === undefined ? 180 : JD.dockCfg.spring))
    readonly property real springDamp: animStyle === "smooth" ? 1.0
        : Math.max(0.3, Math.min(1, JD.dockCfg.damping === undefined ? 0.8 : JD.dockCfg.damping))

    property real pointerScene: -99999   // курсор по вертикали, в координатах окна
    property bool engaged: false
    property int tick: 0
    property var sizes: []
    property var speeds: []
    property real anchorMiddle: 0        // середина, вокруг которой растёт полоса; ставит окно

    function resetPhysics() {
        const n = items.length
        const s = sizes.length === n ? sizes.slice() : []
        const v = speeds.length === n ? speeds.slice() : []
        while (s.length < n) { s.push(1); v.push(0) }
        sizes = s; speeds = v; tick++
    }
    onItemsChanged: resetPhysics()
    Component.onCompleted: resetPhysics()

    readonly property real restLength: pad * 2 + items.length * cell

    // Куда курсор попадает в спокойных координатах полосы. Решаем уравнение: ищем место u, которое
    // при своих же размерах рисуется ровно под курсором.
    function solveRest(scene) {
        let u = scene - anchorMiddle + restLength / 2 - pad
        for (let step = 0; step < 7; step++) {
            let total = pad * 2, before = pad
            for (let i = 0; i < items.length; i++) {
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
        if (!magnify || u < -9000) return 1
        const d = (pad + i * cell + cell / 2 - u) / (cell * spread)
        return 1 + amp * Math.exp(-d * d)
    }
    function stepPhysics(dt) {
        dt = Math.max(0.001, Math.min(0.033, dt))
        const u = restUnderPointer()
        const s = sizes, v = speeds
        const omega = Math.sqrt(springK)
        const c = 2 * springDamp * omega
        let moving = false
        for (let i = 0; i < items.length; i++) {
            const t = targetSize(i, u)
            v[i] += (-(s[i] - t) * springK - c * v[i]) * dt
            s[i] += v[i] * dt
            if (Math.abs(t - s[i]) > 0.0015 || Math.abs(v[i]) > 0.0015) moving = true
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
        for (let i = 0; i < items.length; i++) { sizes[i] = targetSize(i, u); speeds[i] = 0 }
        tick++
    }

    // Места ячеек считаются из тех же размеров, что и рисуются, — поэтому нарисованное и занятое
    // место совпадают всегда, и наложиться значки не могут в принципе.
    readonly property var geom: {
        tick
        const out = []
        let at = pad
        for (let i = 0; i < items.length; i++) {
            const k = sizes[i] === undefined ? 1 : sizes[i]
            const h = cell * k
            out.push({ y: at, h: h, k: k })
            at += h
        }
        return out
    }
    readonly property real laneLength: geom.length ? geom[geom.length - 1].y + geom[geom.length - 1].h + pad : restLength

    implicitWidth: icon + pad * 2
    implicitHeight: Math.max(cell, laneLength)

    readonly property Rectangle blurItem: strip

    Rectangle {
        id: strip
        anchors.fill: parent
        radius: Math.round(tv.implicitWidth * 0.34)
        color: Qt.rgba(0, 0, 0, JD.blurOn ? 0.4 : 0.82)
        border.width: 1
        border.color: Qt.rgba(1, 1, 1, 0.12)

        // Курсор берём в координатах сцены нарочно: в координатах полосы он «двигался» бы сам,
        // когда она под ним растёт и переезжает, — и получилась бы обратная связь.
        HoverHandler {
            id: laneHover
            onPointChanged: { tv.pointerScene = point.scenePosition.y; tv.wake() }
            onHoveredChanged: {
                tv.engaged = hovered
                if (hovered) tv.pointerScene = point.scenePosition.y
                else tv.hint = ""
                tv.wake()
            }
        }

        Item {
            anchors.fill: parent
            Repeater {
                model: tv.items
                delegate: Item {
                    id: slot
                    required property var modelData
                    required property int index
                    readonly property var g: tv.geom[index] || ({ y: tv.pad + index * tv.cell, h: tv.cell, k: 1 })
                    x: (parent.width - tv.cell) / 2
                    y: g.y
                    width: tv.cell
                    height: g.h

                    Rectangle {
                        anchors.centerIn: parent
                        width: (tv.icon + 10) * slot.g.k
                        height: width
                        radius: width / 2
                        color: slotHover.hovered ? JD.fill1 : "transparent"
                        Behavior on color { enabled: JD.animOn; ColorAnimation { duration: 120 } }
                    }
                    // Размер уже посчитан шагом физики — здесь только показываем. Своей анимации
                    // тут быть не должно: она разошлась бы с раскладкой, и значки бы налезли.
                    // Растр просят с запасом: увеличенный значок, нарисованный по обычному
                    // размеру, расплывается.
                    Image {
                        anchors.centerIn: parent
                        width: tv.icon
                        height: tv.icon
                        source: slot.modelData.icon
                        sourceSize: Qt.size(tv.icon * 2.4, tv.icon * 2.4)
                        fillMode: Image.PreserveAspectFit
                        mipmap: true
                        smooth: true
                        scale: slot.g.k * (slotTap.pressed ? 0.88 : 1)
                        transformOrigin: tv.atRight ? Item.Right : Item.Left
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
                            if (mouse.modifiers & Qt.ControlModifier) JD.trayHide(it.id || it.title, true)
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
    // Меню растёт от того края полосы, у которого она стоит, и от середины значка: так видно, чьё
    // оно. Точка — в координатах экрана: меню живёт в отдельном окне во весь экран.
    function showMenu(item, at) {
        if (!item || !item.hasMenu) return
        // Повторный щелчок по тому же значку закрывает меню, а не открывает его заново: иначе
        // единственный способ убрать его — целиться мимо.
        if (JD.trayMenu === item) { JD.closeTrayMenu(); return }
        const p = at.mapToItem(null, tv.atRight ? 0 : at.width, at.height / 2)
        const left = tv.atRight ? JD.screenWidth - tv.width - 10 : tv.x + tv.width
        JD.openTrayMenu(item, Math.round(tv.atRight ? left : left + 8), Math.round(p.y))
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
