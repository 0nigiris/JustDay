// Док: полоса программ у края экрана. Закреплённое, открытое и значок, из которого достаётся меню.
//
// Окна и имена приходят от демона: у открытого окна есть только appId вроде «org.kde.dolphin», и
// превратить его в «Finder» может лишь тот, кто читал .desktop-файлы. Поэтому здесь нет ни своего
// списка программ, ни своего поиска.
//
// ───────────── про увеличение ─────────────
//
// Сначала было сделано наоборот: значок рос, а его ячейка стояла на месте. Так проще и так не
// дрожит, но выходит панель инструментов с ховером, а не док. Весь смысл дока в том, что это одна
// сплошная поверхность, которая целиком отвечает на положение курсора: ближний значок больше всех,
// соседи подхватывают волну, и **все расступаются**, освобождая ему место. Полоса при этом
// расширяется. Без раздвигания значки налезали бы друг на друга, а без него же не было бы главного
// ощущения — что двигаешь не курсор, а саму поверхность.
//
// Отсюда две вещи, которых нет у обычного ховера.
//
// Первая: раскладка считается не привязками, а своим шагом физики на каждый кадр (FrameAnimation).
// Каждый значок имеет цель, текущий размер и скорость; пружина подтягивает размер к цели, а позиции
// пересчитываются из **тех же** текущих размеров. Поэтому нарисованное и занятое место совпадают
// всегда, и наложиться значки не могут в принципе.
//
// Вторая: положение курсора переводится обратно в «спокойные» координаты полосы. Курсор стоит на
// месте в координатах экрана, а полоса под ним едет и растёт; если считать расстояния по
// нарисованным местам, получается обратная связь и дрожь. Поэтому каждый кадр по нарисованной
// раскладке ищется, какой ячейке и в какой её доле курсор соответствует, и уже от этого места
// считаются расстояния до спокойных центров.
import QtQuick
import Quickshell

Item {
    id: dv

    readonly property bool atTop: JD.dockPlace === "top"
    readonly property real icon: JD.dockIconSize
    readonly property real gap: Math.max(4, Math.min(64, JD.dockCfg.spacing === undefined ? 20 : JD.dockCfg.spacing))
    readonly property real cell: icon + gap
    readonly property real pad: Math.round(icon * 0.18)
    readonly property real dotRoom: 9
    readonly property bool magnify: JD.dockCfg.magnify !== false
    readonly property bool labels: JD.dockCfg.labels !== false
    // Заголовки открытых окон под подписью. Настоящих картинок-предпросмотров KWin обычным
    // клиентам не отдаёт, и обещать их было бы враньём.
    readonly property bool preview: JD.dockCfg.preview !== false
    // Черта: сколько места занимает, какой толщины, какой высоты и насколько заметна.
    readonly property real sepWidth: JD.dockCfg.separator_room ? Math.max(2, Math.min(80, JD.dockCfg.separator_room)) : Math.round(gap * 0.8)
    readonly property real sepThick: Math.max(1, Math.min(6, JD.dockCfg.separator_width === undefined ? 1 : JD.dockCfg.separator_width))
    readonly property real sepHeight: Math.max(0.1, Math.min(1, (JD.dockCfg.separator_height === undefined ? 62 : JD.dockCfg.separator_height) / 100))
    readonly property real sepInk: Math.max(0, Math.min(1, (JD.dockCfg.separator_opacity === undefined ? 16 : JD.dockCfg.separator_opacity) / 100))
    readonly property bool showRunning: JD.dockCfg.show_running !== false
    readonly property bool showTrash: JD.dockCfg.show_trash !== false
    // Док уехал за край — кошке незачем перебирать лапами в пустоту: под нагрузкой это тридцать
    // кадров в секунду, которых никто не видит.
    property bool awake: true
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

    // Состав полосы задаётся списком в настройках, а не вшит сюда. Слова простые: launcher, pinned,
    // running, trash, cat, clock — что именно поставить; sep — черта; space — пустой промежуток.
    // Порядок в списке и есть порядок на экране, поэтому «часы слева, перед программами» — это не
    // новая настройка, а другой порядок слов.
    readonly property var layoutWords: {
        const raw = JD.dockCfg.layout
        const list = (Array.isArray(raw) && raw.length ? raw
                     : ["launcher", "sep", "pinned", "running", "sep", "trash", "sep", "cat", "clock"])
        return list.map(w => String(w).trim().toLowerCase()).filter(w => !!w)
    }

    readonly property var entries: {
        const out = [], by = grouped.by, taken = ({})
        const pinnedItems = JD.dockItems
        for (const it of pinnedItems) taken[it.key] = true
        const extra = showRunning ? grouped.order.filter(k => !taken[k]) : []

        // Черта, за которой ничего нет, — это черта в пустоте. Поэтому разделители и промежутки
        // кладём только между тем, что действительно встало в полосу.
        const put = (item) => {
            if (item.t !== "sep" && item.t !== "space") { out.push(item); return }
            if (!out.length) return                        // в самом начале — незачем
            const last = out[out.length - 1]
            if (last.t === "sep" || last.t === "space") return   // две подряд — тоже незачем
            out.push(item)
        }

        for (const word of layoutWords) {
            if (word === "launcher") put({ t: "launcher" })
            else if (word === "sep") put({ t: "sep" })
            else if (word === "space") put({ t: "space" })
            else if (word === "trash") { if (showTrash) put({ t: "trash" }) }
            else if (word === "cat") { if (showCat) put({ t: "cat" }) }
            else if (word === "clock") { if (showClock) put({ t: "clock" }) }
            else if (word === "pinned") {
                for (const it of pinnedItems) {
                    const live = by[it.key]
                    put({ t: "app", key: it.key, kind: it.kind, id: it.id, name: it.name, icon: it.icon,
                          pinned: true, wins: live ? live.wins : [] })
                }
            } else if (word === "running") {
                for (const k of extra) {
                    const g = by[k]
                    put({ t: "app", key: k, kind: g.kind, id: g.id, name: g.name, icon: g.icon,
                          pinned: false, wins: g.wins })
                }
            }
        }
        // Черта в самом конце висит ни на чём.
        while (out.length && (out[out.length - 1].t === "sep" || out[out.length - 1].t === "space")) out.pop()
        return out
    }

    // Ячейки по порядку с готовыми размерами: разделитель узкий, остальное — одинаковые квадраты.
    readonly property var lane: {
        const out = []
        let at = pad
        for (let i = 0; i < entries.length; i++) {
            const t = entries[i].t
            const w = t === "sep" ? dv.sepWidth
                    : t === "space" ? Math.round(cell * 0.6)
                    : t === "cat" ? Math.round(cell * 1.2)
                    : t === "clock" ? Math.round(cell * 1.25) : cell
            out.push(Object.assign({}, entries[i], { at: at, w: w, i: i }))
            at += w
        }
        return out
    }
    // Спокойная длина полосы — та, при которой ничего не увеличено. По ней считаются расстояния.
    readonly property real restLength: (lane.length ? lane[lane.length - 1].at + lane[lane.length - 1].w : 0) + pad

    // ───────────── движок увеличения ─────────────
    readonly property string animStyle: JD.dockCfg.animation || "spring"
    readonly property real amp: Math.max(0, Math.min(2, (JD.dockCfg.magnify_scale === undefined ? 80 : JD.dockCfg.magnify_scale) / 100))
    readonly property real spread: Math.max(0.4, Math.min(6, (JD.dockCfg.magnify_spread === undefined ? 200 : JD.dockCfg.magnify_spread) / 100))
    // Жёсткость и затухание — наружу: «пружинисто» у каждого своё, а на 185 герцах разница видна.
    readonly property real springK: Math.max(10, Math.min(600, JD.dockCfg.spring === undefined ? 180 : JD.dockCfg.spring))
    readonly property real springDamp: animStyle === "smooth" ? 1.0
        : Math.max(0.3, Math.min(1, JD.dockCfg.damping === undefined ? 0.8 : JD.dockCfg.damping))

    property real pointerScene: -99999   // курсор в координатах окна: он-то на месте и стоит
    property bool engaged: false         // курсор в полосе
    property int tick: 0                 // растёт на каждый шаг физики — по нему пересобирается раскладка
    property var sizes: []               // текущий множитель размера каждой ячейки
    property var speeds: []              // и его скорость

    function resetPhysics() {
        const n = lane.length, s = [], v = []
        for (let i = 0; i < n; i++) { s.push(1); v.push(0) }
        sizes = s; speeds = v; tick++
    }
    onLaneChanged: resetPhysics()
    Component.onCompleted: resetPhysics()

    // Середина, вокруг которой полоса растёт. Задаётся снаружи: центрирует док окно, а не он сам.
    property real anchorCentre: 0

    // Куда курсор попадает в спокойных координатах полосы.
    //
    // Тут два подвоха, и оба неочевидны.
    //
    // Первый: считать место курсора по нарисованной раскладке нельзя. Цель тогда зависит от того,
    // докуда доехала анимация, а анимация едет к цели; петля не сходится, и увеличение то
    // недотягивает, то дёргается. Значит, решаем уравнение: ищем спокойное место u, которое при
    // своих же размерах рисуется ровно под курсором.
    //
    // Второй: полоса, расширяясь, ещё и переезжает — она центрирована, и её левый край уходит
    // влево ровно на половину прироста. Если этого не учесть, курсор оказывается не там, где
    // думает решение, увеличение садится между значками и до полного размера не доходит никогда.
    // Поэтому в уравнении участвует и общая длина: центр − длина/2 + путь до u = курсор.
    //
    // Растяжение в любой точке от 1 до 1+amp, поэтому простая итерация сходится за три-четыре шага.
    function solveRest(scene) {
        let u = scene - anchorCentre + restLength / 2 - pad
        for (let step = 0; step < 7; step++) {
            let total = pad * 2, before = pad
            for (let i = 0; i < lane.length; i++) {
                const k = targetSize(i, u)
                const w = lane[i].w * k
                total += w
                if (u >= lane[i].at + lane[i].w) before += w
                else if (u > lane[i].at) before += (u - lane[i].at) * k
            }
            const err = scene - (anchorCentre - total / 2 + before)
            if (Math.abs(err) < 0.2) break
            u += err / (1 + amp * 0.5)
        }
        return u
    }

    function restUnderPointer() {
        return engaged ? solveRest(pointerScene) : -99999
    }

    // Виджеты правилу не подчиняются: кошка и часы показывают цифру, а не ждут нажатия, и прыгать
    // под курсором им незачем — от этого цифру только труднее прочитать.
    function targetSize(i, u) {
        const s = lane[i]
        if (!magnify || u < -9000 || s.t === "cat" || s.t === "clock" || s.t === "sep") return 1
        const d = (s.at + s.w / 2 - u) / (cell * spread)
        return 1 + amp * Math.exp(-d * d)
    }

    // Шаг пружины. Затухание здесь — доля от критического: 1 значит «дойти до размера и замереть»,
    // 0,75 — с маленьким перелётом. Сначала оно было написано как «умножить скорость на что-нибудь
    // каждый кадр», и такая запись значит совсем другое: при 0,75 скорость теряла половину за кадр,
    // пружина ползла к размеру секундами, и увеличение выглядело вялым, хотя цель была верная.
    function stepPhysics(dt) {
        // После пропущенного кадра нельзя швырять пружину на всю задолженность — она взорвётся.
        dt = Math.max(0.001, Math.min(0.033, dt))
        const u = restUnderPointer()
        const n = lane.length
        const s = sizes, v = speeds
        const omega = Math.sqrt(springK)          // собственная частота
        const c = 2 * springDamp * omega          // критическое затухание — при springDamp = 1
        let moving = false
        for (let i = 0; i < n; i++) {
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
        onTriggered: if (!dv.stepPhysics(frameTime)) running = false
    }
    // «Сразу» — это не «без пружины с прежними настройками», а вовсе без физики: размер равен цели
    // в тот же кадр. Раньше этот стиль не делал ничего и молча оставался пружиной.
    function wake() {
        if (JD.animOn && animStyle !== "instant") physics.running = true
        else { physics.running = false; instantly() }
    }
    // Анимации выключены совсем — значит просто ставим целевые размеры без физики.
    function instantly() {
        const u = restUnderPointer()
        for (let i = 0; i < lane.length; i++) { sizes[i] = targetSize(i, u); speeds[i] = 0 }
        tick++
    }

    // Нарисованная раскладка: позиции пересчитываются из ТЕХ ЖЕ размеров, которые сейчас рисуются.
    // Поэтому занятое место и видимое совпадают всегда, и наложиться значки не могут.
    readonly property var geom: {
        tick                                   // зависимость от шага физики
        const out = []
        let at = pad
        for (let i = 0; i < lane.length; i++) {
            const k = sizes[i] === undefined ? 1 : sizes[i]
            const w = lane[i].w * k
            out.push({ x: at, w: w, k: k })
            at += w
        }
        return out
    }
    readonly property real laneLength: geom.length ? geom[geom.length - 1].x + geom[geom.length - 1].w + pad : restLength

    readonly property var focused: {
        tick
        if (!engaged) return null
        const local = pointerScene - dv.x - card.x
        for (let i = 0; i < lane.length; i++)
            if (lane[i].t !== "sep" && local >= geom[i].x && local < geom[i].x + geom[i].w) return lane[i]
        return null
    }

    // ───────────── карточка ─────────────
    readonly property Rectangle blurItem: card

    Rectangle {
        id: card
        width: dv.laneLength
        height: dv.cardHeight
        y: dv.atTop ? 0 : dv.height - height
        radius: Math.round(dv.cardHeight * 0.3)
        // Без размытия под доком та же прозрачность превращается в кашу: значки читаются по тому,
        // что за ними, а не по себе. Нет размытия — нет и прозрачности.
        color: Qt.rgba(0, 0, 0, JD.blurOn ? 0.4 : 0.82)
        border.width: 1
        border.color: Qt.rgba(1, 1, 1, 0.14)

        // Курсор берём в координатах сцены нарочно: в координатах карточки он «двигался» бы сам,
        // когда полоса под ним растёт и переезжает, — и получилась бы обратная связь.
        HoverHandler {
            id: laneHover
            onPointChanged: { dv.pointerScene = point.scenePosition.x; dv.wake() }
            onHoveredChanged: {
                dv.engaged = hovered
                if (hovered) dv.pointerScene = point.scenePosition.x
                else { ctxClose.restart(); tipWait.stop(); dv.tipShown = false }
                dv.wake()
            }
        }

        Repeater {
            model: dv.lane
            delegate: Item {
                id: slot
                required property var modelData
                required property int index
                readonly property var e: modelData
                readonly property var wins: e.wins || []
                readonly property bool running: wins.length > 0
                readonly property bool active: wins.some(w => w.activated && !w.minimized)
                readonly property var g: dv.geom[index] || ({ x: e.at, w: e.w, k: 1 })
                readonly property real k: g.k
                x: g.x
                y: 0
                width: g.w
                height: card.height

                // Разделитель: волосяная черта, а не пустота. Без неё закреплённое и просто
                // открытое сливаются в один ряд, и непонятно, что исчезнет после закрытия окна.
                Rectangle {
                    visible: slot.e.t === "sep"
                    width: dv.sepThick
                    height: dv.icon * dv.sepHeight
                    radius: width / 2
                    anchors.centerIn: parent
                    color: Qt.rgba(1, 1, 1, dv.sepInk)
                }

                Item {
                    id: art
                    visible: slot.e.t !== "sep"
                    width: dv.icon
                    height: dv.icon
                    anchors.horizontalCenter: parent.horizontalCenter
                    // Растёт от края, к которому прижат док: низ значка остаётся на своей линии, и
                    // ряд не начинает плавать по вертикали.
                    y: (dv.atTop ? dv.pad + dv.dotRoom : dv.pad) + slot.bounce
                    // Размер уже посчитан шагом физики — здесь только показываем. Своей анимации
                    // тут быть не должно: она разошлась бы с раскладкой, и значки бы налезли.
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
                        name: JD.trashFull ? "user-trash-full" : "user-trash"
                        fallback: "user-trash"
                        implicitSize: dv.icon
                        renderSize: dv.icon * 2.4
                        theme: true
                    }
                    DockCat {
                        anchors.centerIn: parent
                        visible: slot.e.t === "cat"
                        cpu: JD.cpu
                        awake: dv.awake
                        sleepBelow: JD.dockCfg.cat_sleep_below || 0
                        size: dv.icon
                    }
                    DockClock {
                        anchors.centerIn: parent
                        visible: slot.e.t === "clock"
                        awake: dv.awake
                        size: dv.icon
                    }
                }

                // Открыто — точка. Оно же и подсказка, что значок не запустит второе окно.
                Rectangle {
                    width: slot.wins.length > 1 ? 10 : 4
                    height: 4
                    radius: 2
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: dv.atTop ? dv.pad * 0.5 : card.height - dv.pad * 0.5 - height
                    color: slot.active ? JD.accentBlue : Qt.rgba(1, 1, 1, 0.55)
                    // Появляется и исчезает, а не мигает: окно закрыли — точка уходит, уменьшаясь.
                    opacity: slot.running ? 1 : 0
                    scale: slot.running ? 1 : 0.7
                    Behavior on color { enabled: JD.animOn; ColorAnimation { duration: 150 } }
                    Behavior on opacity { enabled: JD.animOn; NumberAnimation { duration: 140 } }
                    Behavior on scale { enabled: JD.animOn; NumberAnimation { duration: 140; easing.type: Easing.OutBack } }
                }

                // Отскок при запуске: программа открывается не мгновенно, и без него неясно,
                // услышали нажатие или нет. Три затухающих скачка — не больше: док не мультфильм.
                property real bounce: 0
                readonly property bool launching: dv.bouncing !== "" && dv.bouncing === (e.key || e.t)
                onLaunchingChanged: if (launching) bounceAnim.restart()
                SequentialAnimation {
                    id: bounceAnim
                    loops: 3
                    NumberAnimation { target: slot; property: "bounce"; to: dv.atTop ? 13 : -13
                                      duration: 190; easing.type: Easing.OutQuad }
                    NumberAnimation { target: slot; property: "bounce"; to: 0
                                      duration: 240; easing.type: Easing.OutQuad }
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
                    onTapped: dv.openCtx(slot.e, slot.wins, slot.g.x + slot.g.w / 2)
                }
            }
        }
    }

    // ───────────── подпись под курсором ─────────────
    //
    // Не сразу: подпись, выскакивающая в тот же миг, превращает проход вдоль дока в мельтешение
    // плашек. Полсекунды — это ровно «я тут остановился и смотрю».
    property bool tipShown: false
    property string tipFor: ""
    Timer { id: tipWait; interval: 480; onTriggered: dv.tipShown = true }
    onFocusedChanged: {
        const key = focused ? (focused.key || focused.t) : ""
        if (key === tipFor) return
        tipFor = key
        tipShown = false
        if (key && labels) tipWait.restart(); else tipWait.stop()
    }

    Rectangle {
        id: tip
        readonly property bool want: dv.labels && dv.tipShown && !!dv.focused && !ctx.visible
        readonly property string text: !dv.focused ? ""
            : dv.focused.t === "launcher" ? "Программы"
            : dv.focused.t === "trash" ? (JD.trashFull ? "Корзина — не пуста" : "Корзина пуста")
            : dv.focused.t === "cat" ? "Процессор " + Math.round(JD.cpu) + "%"
            : dv.focused.t === "clock" ? Qt.formatDate(new Date(), "d MMMM, dddd")
            : (dv.focused.name || "")
        // Заголовки открытых окон. Настоящих картинок-предпросмотров на KWin обычным клиентам не
        // дают — снимать чужие окна умеет только композитор, — поэтому показываем то, что у нас
        // есть и что на деле нужнее: какие именно окна открыты и какое из них сейчас наверху.
        readonly property var wins: dv.focused && dv.focused.wins ? dv.focused.wins : []
        readonly property bool showsWindows: dv.preview && wins.length > 0
        readonly property int at: dv.focused ? dv.focused.i : -1
        width: Math.max(tipText.implicitWidth, winList.implicitWidth) + 20
        height: showsWindows ? 26 + winList.implicitHeight + 6 : 26
        radius: showsWindows ? 12 : 13
        color: Qt.rgba(0, 0, 0, 0.86)
        border.width: 1
        border.color: Qt.rgba(1, 1, 1, 0.12)
        Behavior on height { enabled: JD.animOn; NumberAnimation { duration: 140; easing.type: Easing.OutCubic } }
        x: {
            const g = at >= 0 && at < dv.geom.length ? dv.geom[at] : null
            return Math.max(0, Math.min(dv.width - width, (g ? g.x + g.w / 2 : 0) - width / 2))
        }
        y: (dv.atTop ? card.height + 10 : dv.height - card.height - height - 10) + (want ? 0 : (dv.atTop ? -5 : 5))
        opacity: want ? 1 : 0
        scale: want ? 1 : 0.94
        visible: opacity > 0.01
        Behavior on opacity { enabled: JD.animOn; NumberAnimation { duration: 130 } }
        Behavior on scale { enabled: JD.animOn; NumberAnimation { duration: 130; easing.type: Easing.OutCubic } }
        Behavior on y { enabled: JD.animOn; NumberAnimation { duration: 130; easing.type: Easing.OutCubic } }
        Label1 {
            id: tipText
            anchors { top: parent.top; topMargin: 5; horizontalCenter: parent.horizontalCenter }
            text: tip.text
        }
        Column {
            id: winList
            visible: tip.showsWindows
            anchors { top: tipText.bottom; topMargin: 4; left: parent.left; leftMargin: 10; right: parent.right; rightMargin: 10 }
            spacing: 2
            Repeater {
                model: tip.showsWindows ? tip.wins.slice(0, 5) : []
                delegate: Row {
                    required property var modelData
                    spacing: 6
                    Rectangle {
                        anchors.verticalCenter: parent.verticalCenter
                        width: 4
                        height: 4
                        radius: 2
                        color: modelData.active ? JD.accentBlue : Qt.rgba(1, 1, 1, 0.35)
                    }
                    Label2 {
                        width: Math.min(implicitWidth, 260)
                        font.pixelSize: 11
                        color: modelData.minimized ? JD.text3 : JD.text2
                        text: (modelData.title || "").trim() || "без названия"
                    }
                }
            }
            Label2 {
                visible: tip.wins.length > 5
                font.pixelSize: 11
                color: JD.text3
                text: "и ещё " + (tip.wins.length - 5)
            }
        }
    }

    // ───────────── правая кнопка ─────────────
    //
    // Не системное меню, а свои три строки: закрепить, закрыть, настройки. Столько и нужно — всё
    // остальное у программы есть в её собственном окне.
    DockAudio { id: audio }

    property var ctxEntry: null
    property var ctxWins: []
    property real ctxAt: 0
    // Ручьи звука той программы, по которой нажали правой кнопкой. Пересчитываются, когда меняется
    // и выбор, и сам список ручьёв: программа могла заиграть уже после открытия меню.
    readonly property var ctxStreams: ctxEntry ? audio.streamsFor(ctxEntry) : []
    readonly property real ctxVolume: audio.volumeOf(ctxStreams)
    readonly property bool ctxMuted: audio.mutedOf(ctxStreams)
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
        width: dv.ctxStreams.length ? 272 : 210
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

            // ───────────── громкость этой программы ─────────────
            //
            // Системная громкость — это громкость всего сразу, и когда мешает один Discord, крутить
            // приходится весь звук. Ползунок появляется только тогда, когда программа действительно
            // что-то играет: пустой ползунок у молчащего значка — обещание, которого он не держит.
            Item {
                width: parent.width
                height: dv.ctxStreams.length ? 42 : 0
                visible: dv.ctxStreams.length > 0
                Row {
                    anchors { left: parent.left; right: parent.right; leftMargin: 12; rightMargin: 12
                              verticalCenter: parent.verticalCenter }
                    spacing: 9
                    Icon {
                        anchors.verticalCenter: parent.verticalCenter
                        name: dv.ctxMuted ? "volume-x" : dv.ctxVolume > 0.5 ? "volume-2" : "volume-1"
                        implicitSize: 15
                        tint: dv.ctxMuted ? JD.text3 : JD.text1
                        HoverHandler { cursorShape: Qt.PointingHandCursor }
                        TapHandler {
                            gesturePolicy: TapHandler.ReleaseWithinBounds
                            onTapped: audio.setMuted(dv.ctxStreams, !dv.ctxMuted)
                        }
                    }
                    // Полоска, за которую тянут. Значение отдаётся сразу, без пружин: звук — это то,
                    // что правят на слух, и задержка между рукой и громкостью тут недопустима.
                    Rectangle {
                        id: volTrack
                        anchors.verticalCenter: parent.verticalCenter
                        width: ctx.width - 24 - 15 - 9 - 40
                        height: 5
                        radius: 2.5
                        color: Qt.rgba(1, 1, 1, 0.18)
                        Rectangle {
                            height: parent.height
                            radius: parent.radius
                            width: parent.width * Math.max(0, Math.min(1, dv.ctxVolume))
                            color: dv.ctxMuted ? JD.text3 : JD.accentBlue
                        }
                        Rectangle {
                            width: 12
                            height: 12
                            radius: 6
                            color: "#ffffff"
                            y: (parent.height - height) / 2
                            x: Math.max(0, Math.min(parent.width - width,
                                        parent.width * Math.max(0, Math.min(1, dv.ctxVolume)) - width / 2))
                        }
                        HoverHandler { cursorShape: Qt.PointingHandCursor }
                        DragHandler {
                            target: null
                            xAxis.enabled: true
                            yAxis.enabled: false
                            onCentroidChanged: if (active) audio.setVolume(dv.ctxStreams, centroid.position.x / volTrack.width)
                        }
                        TapHandler {
                            gesturePolicy: TapHandler.ReleaseWithinBounds
                            onSingleTapped: eventPoint => audio.setVolume(dv.ctxStreams, eventPoint.position.x / volTrack.width)
                        }
                    }
                    Label2 {
                        anchors.verticalCenter: parent.verticalCenter
                        width: 34
                        horizontalAlignment: Text.AlignRight
                        font.pixelSize: 11
                        color: JD.text3
                        text: Math.round(Math.max(0, dv.ctxVolume) * 100) + "%"
                    }
                }
            }
            Rectangle {
                visible: dv.ctxStreams.length > 0
                width: parent.width - 24
                x: 12
                height: 1
                color: Qt.rgba(1, 1, 1, 0.08)
            }

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
        // Нажали в доке при открытом меню — меню своё дело сделало и уходит.
        if (JD.menuOpen) JD.closeMenu()
        if (e.t === "trash") { Quickshell.execDetached(["xdg-open", "trash:///"]); return }
        if (e.t === "cat" || e.t === "clock") { JD.openTools(e.t === "cat" ? "load" : "emoji"); return }
        if (!wins || wins.length === 0) { startBounce(e); JD.dockRun(e); return }
        const front = wins.find(w => w.active && !w.minimized)
        if (front) { for (const w of wins) JD.windowDo("minimize", w.id); return }
        const up = wins.find(w => !w.minimized) || wins[0]
        JD.windowDo("focus", up.id)
    }

    // Проверка движка без мыши: поставить курсор в точку полосы, дать физике сойтись и вернуть
    // получившуюся раскладку. Синтетическая мышь на вейланде врёт, а «значки расступаются» иначе
    // никак не проверить числом. Состояние восстанавливается первым же настоящим движением мыши.
    function probe(x) {
        const wasEngaged = engaged, wasAt = pointerScene
        engaged = true
        // x — место вдоль спокойной полосы, от её левого края. Устойчивая мера: нарисованная
        // полоса под курсором и шире, и сдвинута, и мерить по ней — мерить резиновой линейкой.
        pointerScene = anchorCentre - restLength / 2 + x
        for (let n = 0; n < 400 && stepPhysics(1 / 120); n++) { /* до схождения */ }
        const out = { at: x, u: Math.round(restUnderPointer()), length: Math.round(laneLength), rest: Math.round(restLength),
                      amp: amp, spread: spread, centre: Math.round(anchorCentre),
                      cells: lane.map((s, i) => ({ t: s.t, x: Math.round(geom[i].x), rest: s.at,
                                                   w: Math.round(geom[i].w), k: Number(geom[i].k.toFixed(3)),
                                                   goal: Number(targetSize(i, restUnderPointer()).toFixed(3)) })) }
        engaged = wasEngaged
        pointerScene = wasAt
        wake()
        return out
    }

    // Какой значок сейчас подпрыгивает. Гасим сами через полторы секунды: ждать появления окна
    // нельзя — программа может и не открыться, а значок так и останется скакать.
    property string bouncing: ""
    function startBounce(e) { bouncing = e.key || e.t; bounceStop.restart() }
    Timer { id: bounceStop; interval: 1500; onTriggered: dv.bouncing = "" }

    // Где на экране значок меню — считает shell.qml: только он видит и док, и его окно сразу.
    // По нарисованной раскладке, а не по спокойной: полоса под курсором шире, чем в покое.
    readonly property real launcherCenter: geom.length ? geom[0].x + geom[0].w / 2 : 0
}
