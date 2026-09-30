// Док: полоса программ у края экрана. Закреплённое, открытое и значок, из которого достаётся меню.
//
// Окна берутся у вейланда напрямую (ToplevelManager), имена и значки — у демона: у открытого окна
// есть только appId вроде «org.kde.dolphin», и превратить его в «Finder» может лишь тот, кто читал
// .desktop-файлы. Поэтому здесь нет ни своего списка программ, ни своего поиска.
//
// Увеличение под курсором сделано так, чтобы область нажатия не двигалась: значок растёт наружу от
// края (вверх у нижнего дока), а его ячейка остаётся на месте. Иначе значок уезжает из-под курсора,
// курсор попадает на соседа, тот увеличивается — и полоса начинает дрожать.
import QtQuick
import Quickshell

Item {
    id: dv

    readonly property bool atTop: JD.dockPlace === "top"
    readonly property real icon: JD.dockIconSize
    readonly property real gap: Math.round(icon * 0.34)
    readonly property real cell: icon + gap
    readonly property real pad: Math.round(icon * 0.18)
    readonly property real dotRoom: 9
    readonly property bool magnify: JD.dockCfg.magnify !== false
    readonly property bool labels: JD.dockCfg.labels !== false
    readonly property bool showRunning: JD.dockCfg.show_running !== false
    readonly property bool showTrash: JD.dockCfg.show_trash !== false
    readonly property bool showCat: JD.dockCfg.cat !== false
    readonly property bool showClock: JD.dockCfg.clock === true
    // Значок меню: «apple» — то, что тема значков зовёт start-here (в макосных темах это яблоко),
    // «grid» — своя сетка точек. Файл готовит демон: в темах такие значки нарисованы «цветом
    // текста», которого разрисовщик Qt не разрешает, и на тёмном доке вышло бы чёрное пятно.
    // Темы без start-here есть, поэтому сетка ещё и запасной вариант.
    readonly property string launcherWant: JD.dockCfg.launcher || "grid"
    readonly property string launcherIcon: launcherWant === "grid" ? "" : JD.dockLauncher
    // Сколько места оставить под увеличенный значок и подпись: они выходят за карточку, и им нужна
    // своя высота в окне, иначе верхушка срезается.
    readonly property real headroom: Math.round(icon * 0.55) + 30
    readonly property real cardHeight: icon + pad * 2 + dotRoom

    implicitWidth: laneLength
    implicitHeight: cardHeight + headroom

    // ───────────── что в полосе ─────────────
    //
    // Окна, разложенные по программам. Незнакомая программа — не беда: значок всё равно будет,
    // только подписанный тем, как окно назвало себя само.
    readonly property var grouped: {
        const skip = JD.dockSkip, byKey = ({}), order = []
        for (const w of JD.windows) {
            const a = String(w.app || "").toLowerCase()
            if (!a || skip.indexOf(a) >= 0) continue
            const hit = JD.dockLookup(a)
            const key = hit ? hit.key : "win:" + a
            if (!byKey[key]) {
                byKey[key] = { key: key, kind: hit ? hit.kind : "", id: hit ? hit.id : "",
                               name: hit ? hit.name : (w.app || ""), icon: hit ? hit.icon : a, wins: [] }
                order.push(key)
            }
            byKey[key].wins.push(w)
        }
        return { by: byKey, order: order }
    }

    readonly property var entries: {
        const out = [{ t: "launcher" }], by = grouped.by, taken = ({})
        const pinnedItems = JD.dockItems
        if (pinnedItems.length) out.push({ t: "sep" })
        for (const it of pinnedItems) {
            taken[it.key] = true
            const live = by[it.key]
            out.push({ t: "app", key: it.key, kind: it.kind, id: it.id, name: it.name, icon: it.icon,
                       pinned: true, wins: live ? live.wins : [] })
        }
        if (showRunning) {
            const extra = grouped.order.filter(k => !taken[k])
            if (extra.length) out.push({ t: "sep" })
            for (const k of extra) {
                const g = by[k]
                out.push({ t: "app", key: k, kind: g.kind, id: g.id, name: g.name, icon: g.icon,
                           pinned: false, wins: g.wins })
            }
        }
        if (showTrash) { out.push({ t: "sep" }); out.push({ t: "trash" }) }
        // Виджеты — в самом конце, за своей чертой: они не запускаются и не закрепляются, и стоять
        // вперемешку с программами им незачем.
        if (showCat || showClock) out.push({ t: "sep" })
        if (showCat) out.push({ t: "cat" })
        if (showClock) out.push({ t: "clock" })
        return out
    }

    // Ячейки по порядку с готовыми размерами: разделитель узкий, остальное — одинаковые квадраты.
    readonly property var lane: {
        const out = []
        let at = pad
        for (let i = 0; i < entries.length; i++) {
            const t = entries[i].t
            const w = t === "sep" ? Math.round(gap * 0.8)
                    : t === "cat" ? Math.round(cell * 1.15)
                    : t === "clock" ? Math.round(cell * 1.25) : cell
            out.push(Object.assign({}, entries[i], { at: at, w: w, i: i }))
            at += w
        }
        return out
    }
    readonly property real laneLength: (lane.length ? lane[lane.length - 1].at + lane[lane.length - 1].w : 0) + pad

    // ───────────── увеличение ─────────────
    property real focusX: -9999
    property real power: 0
    Behavior on power { enabled: JD.animOn; NumberAnimation { duration: 170; easing.type: Easing.OutCubic } }
    function magOf(at, w) {
        if (power <= 0.001) return 1
        const d = (at + w / 2 - focusX) / (cell * 1.15)
        return 1 + 0.52 * power * Math.exp(-d * d)
    }
    readonly property var focused: {
        if (power <= 0.3) return null
        for (const s of lane)
            if (s.t !== "sep" && focusX >= s.at && focusX < s.at + s.w) return s
        return null
    }

    // ───────────── карточка ─────────────
    readonly property Item blurItem: card

    Rectangle {
        id: card
        width: dv.laneLength
        height: dv.cardHeight
        y: dv.atTop ? 0 : dv.height - height
        radius: Math.round(dv.cardHeight * 0.3)
        color: Qt.rgba(0, 0, 0, 0.4)
        border.width: 1
        border.color: Qt.rgba(1, 1, 1, 0.14)

        HoverHandler {
            id: laneHover
            onPointChanged: dv.focusX = point.position.x
            onHoveredChanged: {
                dv.power = hovered && dv.magnify ? 1 : 0
                if (!hovered) { dv.focusX = -9999; ctxClose.restart() }
            }
        }

        Repeater {
            model: dv.lane
            delegate: Item {
                id: slot
                required property var modelData
                readonly property var e: modelData
                readonly property var wins: e.wins || []
                readonly property bool running: wins.length > 0
                readonly property bool active: wins.some(w => w.activated && !w.minimized)
                readonly property real k: dv.magOf(e.at, e.w)
                x: e.at
                y: 0
                width: e.w
                height: card.height

                // Разделитель: волосяная черта, а не пустота. Без неё закреплённое и просто
                // открытое сливаются в один ряд, и непонятно, что исчезнет после закрытия окна.
                Rectangle {
                    visible: slot.e.t === "sep"
                    width: 1
                    height: dv.icon * 0.62
                    anchors.centerIn: parent
                    color: Qt.rgba(1, 1, 1, 0.16)
                }

                Item {
                    id: art
                    visible: slot.e.t !== "sep"
                    width: dv.icon
                    height: dv.icon
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: dv.atTop ? dv.pad + dv.dotRoom : dv.pad
                    scale: slot.k
                    transformOrigin: dv.atTop ? Item.Top : Item.Bottom
                    opacity: slotTap.pressed ? 0.7 : 1

                    // Значок меню. Сетка из точек — то, что у этого значка значит «все программы»
                    // на любом рабочем столе; цвета — островка, чтобы он не выглядел чужим.
                    // Яблоко (или что тема зовёт start-here) рисуем без подложки: у макосных тем
                    // это готовый значок со своей формой, и квадрат под ним выглядит наклейкой.
                    Image {
                        anchors.fill: parent
                        anchors.margins: Math.round(dv.icon * 0.06)
                        visible: slot.e.t === "launcher" && dv.launcherIcon !== ""
                        source: dv.launcherIcon ? "file://" + dv.launcherIcon : ""
                        sourceSize: Qt.size(dv.icon * 2.4, dv.icon * 2.4)
                        fillMode: Image.PreserveAspectFit
                        mipmap: true
                        smooth: true
                    }

                    Rectangle {
                        anchors.fill: parent
                        visible: slot.e.t === "launcher" && dv.launcherIcon === ""
                        radius: width * 0.27
                        gradient: Gradient {
                            GradientStop { position: 0; color: "#3f8cff" }
                            GradientStop { position: 1; color: "#7a4df0" }
                        }
                        border.width: 1
                        border.color: Qt.rgba(1, 1, 1, 0.22)
                        Grid {
                            anchors.centerIn: parent
                            rows: 3
                            columns: 3
                            spacing: Math.max(2, Math.round(dv.icon * 0.12))
                            Repeater {
                                model: 9
                                delegate: Rectangle {
                                    width: Math.max(3, Math.round(dv.icon * 0.15))
                                    height: width
                                    radius: width / 2
                                    color: "#ffffff"
                                }
                            }
                        }
                    }

                    Icon {
                        anchors.fill: parent
                        visible: slot.e.t === "app"
                        name: slot.e.icon || ""
                        fallback: "application-x-executable"
                        implicitSize: dv.icon
                        // Растр просят с запасом на увеличение: под курсором значок вырастает в
                        // полтора раза, и нарисованный по обычному размеру он там расплывается.
                        renderSize: dv.icon * 2.4
                        theme: true
                    }
                    Icon {
                        anchors.fill: parent
                        visible: slot.e.t === "trash"
                        name: "user-trash"
                        fallback: "user-trash"
                        implicitSize: dv.icon
                        renderSize: dv.icon * 2.4
                        theme: true
                    }
                    DockCat {
                        anchors.centerIn: parent
                        visible: slot.e.t === "cat"
                        cpu: JD.cpu
                        size: Math.round(dv.icon * 0.82)
                    }
                    DockClock {
                        anchors.centerIn: parent
                        visible: slot.e.t === "clock"
                        size: dv.icon
                    }
                }

                // Открыто — точка. Оно же и подсказка, что значок не запустит второе окно.
                Rectangle {
                    visible: slot.running
                    width: slot.wins.length > 1 ? 10 : 4
                    height: 4
                    radius: 2
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: dv.atTop ? dv.pad * 0.5 : card.height - dv.pad * 0.5 - height
                    color: slot.active ? JD.accentBlue : Qt.rgba(1, 1, 1, 0.55)
                    Behavior on color { enabled: JD.animOn; ColorAnimation { duration: 150 } }
                }

                HoverHandler { enabled: slot.e.t !== "sep"; cursorShape: Qt.PointingHandCursor }
                TapHandler {
                    id: slotTap
                    enabled: slot.e.t !== "sep"
                    gesturePolicy: TapHandler.ReleaseWithinBounds
                    onTapped: dv.press(slot.e, slot.wins)
                }
                TapHandler {
                    enabled: slot.e.t !== "sep"
                    acceptedButtons: Qt.RightButton
                    gesturePolicy: TapHandler.ReleaseWithinBounds
                    onTapped: dv.openCtx(slot.e, slot.wins, slot.e.at + slot.e.w / 2)
                }
            }
        }
    }

    // ───────────── подпись под курсором ─────────────
    Rectangle {
        id: tip
        visible: dv.labels && !!dv.focused && dv.power > 0.5 && !ctx.visible
        readonly property string text: !dv.focused ? ""
            : dv.focused.t === "launcher" ? "Программы"
            : dv.focused.t === "trash" ? "Корзина"
            : dv.focused.t === "cat" ? "Процессор " + Math.round(JD.cpu) + "%"
            : dv.focused.t === "clock" ? Qt.formatDate(new Date(), "d MMMM, dddd")
            : (dv.focused.name || "")
        width: tipText.implicitWidth + 20
        height: 26
        radius: 13
        color: Qt.rgba(0, 0, 0, 0.82)
        border.width: 1
        border.color: Qt.rgba(1, 1, 1, 0.12)
        x: Math.max(0, Math.min(dv.width - width, (dv.focused ? dv.focused.at + dv.focused.w / 2 : 0) - width / 2))
        y: dv.atTop ? card.height + 8 : dv.height - card.height - height - 8
        opacity: visible ? 1 : 0
        Behavior on opacity { enabled: JD.animOn; NumberAnimation { duration: 120 } }
        Label1 { id: tipText; anchors.centerIn: parent; text: tip.text }
    }

    // ───────────── правая кнопка ─────────────
    //
    // Не системное меню, а свои три строки: закрепить, закрыть, настройки. Столько и нужно — всё
    // остальное у программы есть в её собственном окне.
    property var ctxEntry: null
    property var ctxWins: []
    property real ctxAt: 0
    function openCtx(e, wins, at) {
        if (e.t === "sep") return
        ctxEntry = e; ctxWins = wins || []; ctxAt = at
        ctxClose.stop()
    }
    function closeCtx() { ctxEntry = null; ctxWins = [] }
    Timer { id: ctxClose; interval: 1400; onTriggered: dv.closeCtx() }

    Rectangle {
        id: ctx
        visible: !!dv.ctxEntry
        width: 210
        height: ctxRows.implicitHeight + 12
        radius: 14
        color: Qt.rgba(0, 0, 0, 0.9)
        border.width: 1
        border.color: Qt.rgba(1, 1, 1, 0.12)
        x: Math.max(0, Math.min(dv.width - width, dv.ctxAt - width / 2))
        y: dv.atTop ? card.height + 8 : dv.height - card.height - height - 8
        HoverHandler { onHoveredChanged: hovered ? ctxClose.stop() : ctxClose.restart() }
        Column {
            id: ctxRows
            y: 6
            width: parent.width
            Repeater {
                model: dv.ctxActions
                delegate: Rectangle {
                    required property var modelData
                    width: parent.width
                    height: 32
                    color: rowHover.hovered ? JD.fill1 : "transparent"
                    Row {
                        anchors.fill: parent
                        anchors.leftMargin: 12
                        anchors.rightMargin: 12
                        spacing: 9
                        Icon {
                            anchors.verticalCenter: parent.verticalCenter
                            name: modelData.icon
                            implicitSize: 15
                            tint: modelData.danger ? JD.accentRed : JD.text1
                        }
                        Label1 {
                            anchors.verticalCenter: parent.verticalCenter
                            text: modelData.label
                            color: modelData.danger ? JD.accentRed : JD.text1
                        }
                    }
                    HoverHandler { id: rowHover; cursorShape: Qt.PointingHandCursor }
                    TapHandler {
                        gesturePolicy: TapHandler.ReleaseWithinBounds
                        onTapped: { dv.doCtx(modelData.id); dv.closeCtx() }
                    }
                }
            }
        }
    }

    readonly property var ctxActions: {
        const e = ctxEntry
        if (!e) return []
        if (e.t === "launcher") return [{ id: "menu", label: "Открыть меню", icon: "layout-grid" },
                                        { id: "settings", label: "Настроить док", icon: "sliders-horizontal" }]
        if (e.t === "trash") return [{ id: "trash", label: "Открыть корзину", icon: "folder-open" }]
        if (e.t === "cat") return [{ id: "load", label: "Нагрузка машины", icon: "gauge" },
                                   { id: "settings", label: "Настроить док", icon: "sliders-horizontal" }]
        if (e.t === "clock") return [{ id: "settings", label: "Настроить док", icon: "sliders-horizontal" }]
        const out = [{ id: "open", label: "Открыть", icon: "external-link" }]
        if (e.id) out.push(e.pinned ? { id: "unpin", label: "Убрать из дока", icon: "minus" }
                                    : { id: "pin", label: "Оставить в доке", icon: "plus" })
        if (ctxWins.length) out.push({ id: "close", label: ctxWins.length > 1 ? "Закрыть все окна" : "Закрыть окно",
                                       icon: "x", danger: true })
        out.push({ id: "settings", label: "Настроить док", icon: "sliders-horizontal" })
        return out
    }

    function doCtx(what) {
        const e = ctxEntry, wins = ctxWins
        if (what === "menu") JD.toggleMenu()
        else if (what === "settings") JD.openSettings("dock")
        else if (what === "trash") Quickshell.execDetached(["xdg-open", "trash:///"])
        else if (what === "load") JD.openTools("load")
        else if (what === "open") JD.dockRun(e)
        else if (what === "pin") JD.dockPin(e.kind, e.id, true)
        else if (what === "unpin") JD.dockPin(e.kind, e.id, false)
        else if (what === "close") for (const w of wins) JD.windowDo("close", w.id)
    }

    // Нажатие: не запущено — запустить; запущено и не наверху — поднять; наверху — свернуть.
    // Второй запуск того же — самая частая ошибка дока, и именно её эта развилка убирает.
    function press(e, wins) {
        closeCtx()
        if (e.t === "launcher") { JD.toggleMenu(); return }
        if (e.t === "trash") { Quickshell.execDetached(["xdg-open", "trash:///"]); return }
        if (e.t === "cat" || e.t === "clock") { JD.openTools(e.t === "cat" ? "load" : "emoji"); return }
        if (!wins || wins.length === 0) { JD.dockRun(e); return }
        const front = wins.find(w => w.active && !w.minimized)
        if (front) { for (const w of wins) JD.windowDo("minimize", w.id); return }
        const up = wins.find(w => !w.minimized) || wins[0]
        JD.windowDo("focus", up.id)
    }

    // Где на экране значок меню — считает shell.qml: только он видит и док, и его окно сразу.
    readonly property real launcherCenter: lane.length ? lane[0].at + lane[0].w / 2 : 0
}
