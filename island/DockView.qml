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
    readonly property real dotRoom: 11
    // Closed icons sink a touch so the row feels centered; running keep the normal baseline (no raise).
    readonly property real restDrop: Math.max(1, Math.round(icon * 0.06))
    readonly property bool magnify: JD.dockCfg.magnify !== false
    // Подписи: нет совсем, под курсором или всегда. Раньше было только «да/нет», а «всегда» — это
    // другой док: имена под всеми значками сразу, как в Dockish и в старых доках.
    readonly property string labelMode: {
        const raw = JD.dockCfg.labels
        if (raw === false) return "off"
        if (raw === true || raw === undefined) return "hover"
        const word = String(raw).trim().toLowerCase()
        return ["off", "hover", "always"].indexOf(word) >= 0 ? word : "hover"
    }
    readonly property bool labels: labelMode !== "off"
    // Чем отмечено открытое: точка, чёрточка, полоса, свечение — или ничем.
    readonly property string mark: {
        const word = String(JD.dockCfg.indicator || "dot").trim().toLowerCase()
        return ["dot", "line", "bar", "glow", "none"].indexOf(word) >= 0 ? word : "dot"
    }
    // Заголовки открытых окон под подписью. Настоящих картинок-предпросмотров KWin обычным
    // клиентам не отдаёт, и обещать их было бы враньём.
    readonly property bool preview: JD.dockCfg.preview !== false
    // Черта: сколько места занимает, какой толщины, какой высоты и насколько заметна.
    readonly property real sepWidth: JD.dockCfg.separator_room ? Math.max(2, Math.min(80, JD.dockCfg.separator_room)) : Math.round(gap * 0.8)
    readonly property real sepThick: Math.max(1, Math.min(6, JD.dockCfg.separator_width === undefined ? 1 : JD.dockCfg.separator_width))
    readonly property real sepHeight: Math.max(0.1, Math.min(1, (JD.dockCfg.separator_height === undefined ? 62 : JD.dockCfg.separator_height) / 100))
    readonly property real sepInk: Math.max(0, Math.min(1, (JD.dockCfg.separator_opacity === undefined ? 16 : JD.dockCfg.separator_opacity) / 100))
    // ───────────── «колесо» ─────────────
    //
    // Отдельный нрав полосы, на выбор. Обычный док — сплошное поле: под курсором растёт то, что
    // ближе, и никакого «выбранного» нет вовсе. Колесо добавляет под это поле **защёлки**: у полосы
    // появляются дискретные положения, как у хорошего переключателя, и переход между ними —
    // короткий механический щелчок.
    //
    // Зачем так. Выбор, который меняется ровно на геометрической середине между значками, дрожит:
    // рука стоит на границе, и выбранное прыгает туда-сюда от дрожания кисти. Поэтому середина не
    // переключает ничего: переключает только заход в соседа достаточно глубоко (0,58), а обратно —
    // такой же заход назад. Это и есть гистерезис, и он тут не украшение, а то, что делает выбор
    // устойчивым.
    //
    // Что НЕ меняется: увеличение остаётся непрерывным и считается от курсора, как прежде. Защёлка
    // добавляет толчок пружине, а не подменяет собой поле. Логическое состояние меняется мгновенно,
    // инерция есть только у картинки.
    readonly property bool wheel: JD.dockCfg.wheel === true
    readonly property real detent: Math.max(0, Math.min(3, (JD.dockCfg.detent === undefined ? 90 : JD.dockCfg.detent) / 100))
    property int committed: -1           // ячейка, на которой колесо стоит сейчас
    property var nudges: []              // сдвиг ячейки в точках: короткий толчок вбок при щелчке
    property var nudgeSpeeds: []

    readonly property bool showRunning: JD.dockCfg.show_running !== false
    readonly property bool showTrash: JD.dockCfg.show_trash !== false
    // Док уехал за край — кошке незачем перебирать лапами в пустоту: под нагрузкой это тридцать
    // кадров в секунду, которых никто не видит.
    property bool awake: true
    readonly property bool showCat: JD.dockCfg.cat !== false
    readonly property bool showClock: JD.dockCfg.clock === true
    readonly property bool showTrayButton: JD.dockCfg.tray_button === true
    // Значок меню: «apple» — то, что тема значков зовёт start-here (в макосных темах это яблоко),
    // «grid» — своя сетка точек. Файл готовит демон: в темах такие значки нарисованы «цветом
    // текста», которого разрисовщик Qt не разрешает, и на тёмном доке вышло бы чёрное пятно.
    // Темы без start-here есть, поэтому сетка ещё и запасной вариант.
    readonly property string launcherWant: JD.dockCfg.launcher || "grid"
    readonly property string launcherIcon: launcherWant === "grid" ? "" : JD.dockLauncher
    // Сколько места оставить под увеличенный значок и подпись: они выходят за карточку, и им нужна
    // своя высота в окне, иначе верхушка срезается.
    readonly property real headroom: Math.round(icon * 0.55) + 30
    // Место под имя под значком — только в режиме «всегда»: в остальных подпись живёт в плашке
    // под курсором и высоты карточке не добавляет.
    readonly property real labelRoom: labelMode === "always" ? 14 : 0
    readonly property real cardHeight: icon + pad * 2 + dotRoom + restDrop + labelRoom

    implicitWidth: laneLength
    implicitHeight: cardHeight + headroom

    // ───────────── что в полосе ─────────────
    //
    // Окна, разложенные по программам. Незнакомая программа — не беда: значок всё равно будет,
    // только подписанный тем, как окно назвало себя само.
    readonly property var grouped: {
        const skip = JD.dockSkip, byKey = ({}), order = []
        const separate = JD.dockSeparate || []
        for (const w of JD.windows) {
            const a = String(w.app || "").toLowerCase()
            if (!a || skip.indexOf(a) >= 0) continue
            const hit = JD.dockLookup(a)
            // Anti-detect browsers (octium, …): one dock slot per profile window.
            const split = separate.indexOf(a) >= 0 || !!(hit && hit.separate)
            const key = split ? ("win:" + a + ":" + String(w.id || ""))
                      : (hit ? hit.key : "win:" + a)
            if (!byKey[key]) {
                // Unmatched .exe (Wine) → wine icon, not the theme's generic gear fallback.
                const rawIcon = hit ? hit.icon : (a.endsWith(".exe") ? "wine" : a)
                const label = split
                    ? ((w.title || "").trim() || (hit ? hit.name : (w.app || "")))
                    : (hit ? hit.name : (w.app || ""))
                byKey[key] = { key: key, kind: hit ? hit.kind : "", id: hit ? hit.id : "",
                               name: label, icon: rawIcon, wins: [], split: split }
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
        const words = list.map(w => String(w).trim().toLowerCase()).filter(w => !!w)
        // Кнопку включили в настройках, а в порядке её нет — поставить самому, перед корзиной:
        // там и так живёт всё системное. Иначе настройка была бы включена и ничего не делала.
        if (JD.dockCfg.tray_button === true && words.indexOf("tray") < 0) {
            const at = words.indexOf("trash")
            words.splice(at >= 0 ? at : words.length, 0, "tray")
        }
        return words
    }

    // ───────────── перетаскивание значков ─────────────
    //
    // Пока значок тащат, порядок живёт здесь, а не у демона: спрашивать демона на каждый пиксель
    // — это разговор по сокету тридцать раз в секунду ради того, что и так видно. Наружу порядок
    // уходит один раз, когда значок отпустили.
    readonly property bool reorder: JD.dockCfg.reorder !== false
    property string dragKey: ""          // что тащим
    property real dragLocal: 0           // курсор в координатах карточки
    property var pinOverride: []         // порядок закреплённого, пока тащим (и до ответа демона)

    readonly property var entries: {
        const out = [], by = grouped.by, taken = ({})
        // Местный порядок годится, пока в нём ровно то же, что у демона. Закрепили новое или
        // убрали лишнее — местный порядок устарел, и слушаем демона.
        const known = JD.dockItems
        let pinnedItems = known
        if (dv.pinOverride.length === known.length && known.length) {
            const mapped = dv.pinOverride.map(k => known.find(i => i.key === k)).filter(i => !!i)
            if (mapped.length === known.length) pinnedItems = mapped
        }
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
            else if (word === "tray") { if (showTrayButton) put({ t: "tray" }) }
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
    // Extra panel width so magnified end-icons are not clipped. Exclusive zone still
    // uses card height only — this is paint/hit room, not magnet depth.
    readonly property real magExtra: Math.round(icon * amp * spread * 1.8) + 16
    // Жёсткость и затухание — наружу: «пружинисто» у каждого своё, а на 185 герцах разница видна.
    readonly property real springK: Math.max(10, Math.min(600, JD.dockCfg.spring === undefined ? 180 : JD.dockCfg.spring))
    readonly property real springDamp: animStyle === "smooth" ? 1.0
        : Math.max(0.3, Math.min(1, JD.dockCfg.damping === undefined ? 0.8 : JD.dockCfg.damping))

    property real pointerScene: -99999   // курсор в координатах окна: он-то на месте и стоит
    property bool engaged: false         // курсор в полосе
    property int tick: 0                 // растёт на каждый шаг физики — по нему пересобирается раскладка
    property var sizes: []               // текущий множитель размера каждой ячейки
    property var speeds: []              // и его скорость

    // Полоса пересобирается часто: открылось окно, сменилась корзина, переставили значок. Если
    // каждый раз сбрасывать размеры в единицу, увеличение под курсором схлопывается на ровном
    // месте — и это было видно каждый раз, когда под курсором открывалось окно. Пока число ячеек
    // то же, размеры и скорости остаются: их подтянет та же пружина.
    function resetPhysics() {
        const n = lane.length
        const s = sizes.length === n ? sizes.slice() : []
        const v = speeds.length === n ? speeds.slice() : []
        while (s.length < n) { s.push(1); v.push(0) }
        sizes = s; speeds = v; tick++
    }
    onLaneChanged: { resetPhysics(); iconPublish.restart() }
    Component.onCompleted: { resetPhysics(); iconPublish.restart() }

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
    //
    // Значок меню — тоже. Он не программа, а кнопка, и нарисован он голым силуэтом без подложки:
    // выросши в полтора раза, яблоко пересекает кромку карточки, и половина его оказывается над
    // обоями. У значка с подложкой это читается как «поднялся», у силуэта — как «вылез из рамки».
    // На самой макоси яблоко живёт в строке меню и не увеличивается вовсе.
    function targetSize(i, u) {
        const s = lane[i]
        if (!magnify || u < -9000 || s.t === "cat" || s.t === "clock" || s.t === "sep"
            || s.t === "launcher") return 1
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
        if (wheel) moving = settleWheel(u, dt) || moving
        for (let i = 0; i < n; i++) {
            const t = targetSize(i, u)
            v[i] += (-(s[i] - t) * springK - c * v[i]) * dt
            s[i] += v[i] * dt
            if (Math.abs(t - s[i]) > 0.0015 || Math.abs(v[i]) > 0.0015) moving = true
        }
        tick++
        return moving
    }

    // Выбираемые ячейки: черта и промежуток защёлок не имеют — на них колесо не стоит.
    function pickable() {
        const out = []
        for (let i = 0; i < lane.length; i++) {
            const t = lane[i].t
            if (t !== "sep" && t !== "space") out.push(i)
        }
        return out
    }
    function restCentre(i) { return lane[i].at + lane[i].w / 2 }

    // Защёлки и сдвиги. Возвращает true, пока что-то ещё движется.
    function settleWheel(u, dt) {
        const spots = pickable()
        if (!spots.length) return false
        if (nudges.length !== lane.length) {
            const z = [], zv = []
            for (let i = 0; i < lane.length; i++) { z.push(0); zv.push(0) }
            nudges = z; nudgeSpeeds = zv
        }
        if (u > -9000) {
            if (committed < 0 || committed >= lane.length || spots.indexOf(committed) < 0)
                commitTo(nearestSpot(u, spots), 0)
            else {
                const here = restCentre(committed)
                const at = spots.indexOf(committed)
                // Бросок через несколько значков не отыгрывается по одному: цель берётся сразу от
                // курсора, а толчок даётся один. Иначе быстрый проход вдоль полосы превращается в
                // очередь из пяти анимаций, и полоса ещё секунду живёт своей жизнью.
                const far = nearestSpot(u, spots)
                if (Math.abs(spots.indexOf(far) - at) > 1) commitTo(far, u > here ? 1 : -1)
                else {
                    const step = u > here ? 1 : -1
                    const nextAt = at + step
                    if (nextAt >= 0 && nextAt < spots.length) {
                        const next = spots[nextAt]
                        const span = restCentre(next) - here
                        const part = span === 0 ? 0 : (u - here) / span
                        if (part >= 0.58) commitTo(next, step)
                    }
                }
            }
        }
        // Сдвиг вбок возвращается своей пружиной, жёстче основной: он обязан кончиться раньше, чем
        // человек успеет заметить его как движение.
        let moving = false
        const w = Math.sqrt(520), cc = 2 * 0.85 * w
        for (let i = 0; i < lane.length; i++) {
            nudgeSpeeds[i] += (-nudges[i] * 520 - cc * nudgeSpeeds[i]) * dt
            nudges[i] += nudgeSpeeds[i] * dt
            if (Math.abs(nudges[i]) > 0.02 || Math.abs(nudgeSpeeds[i]) > 0.02) moving = true
        }
        return moving
    }
    function nearestSpot(u, spots) {
        let best = spots[0], bestD = Infinity
        for (const i of spots) {
            const d = Math.abs(restCentre(i) - u)
            if (d < bestD) { bestD = d; best = i }
        }
        return best
    }
    // Щелчок защёлки: новой ячейке — толчок пружине вверх, прежней — короткий отпуск вниз, обеим —
    // крошечный сдвиг по ходу движения. Всё это толчки, а не анимации поверх физики: вторая
    // анимация поверх пружины — ровно то, из-за чего значки однажды застыли внахлёст.
    function commitTo(i, dir) {
        const was = committed
        committed = i
        if (was === i || !detent) return
        const push = detent * 1.1
        if (speeds[i] !== undefined) speeds[i] += push
        if (was >= 0 && speeds[was] !== undefined) speeds[was] -= push * 0.35
        if (nudges.length === lane.length && dir !== 0) {
            nudgeSpeeds[i] += dir * 26 * detent
            if (was >= 0) nudgeSpeeds[was] -= dir * 13 * detent
        }
        tick++
    }

    FrameAnimation {
        id: physics
        running: false
        onTriggered: if (!dv.stepPhysics(frameTime)) running = false
    }
    // «Сразу» — это не «без пружины с прежними настройками», а вовсе без физики: размер равен цели
    // в тот же кадр. Раньше этот стиль не делал ничего и молча оставался пружиной.
    // Курсор ушёл с полосы — защёлка не щёлкает: уход это не выбор. Спецификация просит об этом
    // отдельно, и правильно: подпрыгнувший на прощание док выглядит капризным.
    onEngagedChanged: if (!engaged) committed = -1

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

    // Кто сейчас «выбран». В обычном доке это просто ячейка под курсором. В режиме колеса — та, на
    // которой стоит защёлка: иначе подпись меняется на геометрической середине, а увеличение и
    // щелчок — позже, и выходит, что подписано одно, а нажмётся другое.
    readonly property var focused: {
        tick
        if (!engaged) return null
        if (wheel && committed >= 0 && committed < lane.length) return lane[committed]
        const local = pointerScene - dv.x - card.x
        for (let i = 0; i < lane.length; i++)
            if (lane[i].t !== "sep" && local >= geom[i].x && local < geom[i].x + geom[i].w) return lane[i]
        return null
    }

    // ───────────── карточка ─────────────
    readonly property Rectangle blurItem: card

    // Сколько пустоты между карточкой и краем экрана. Док лежит не вплотную к краю — так он
    // выглядит предметом, а не куском рамки, — но **чувствовать** курсор обязан до самого края.
    // Иначе человек уводит мышь вниз до упора, что и значит «к доку», а док там уже не его: ряд
    // пикселей у самого низа принадлежал никому, и полоса на курсор не отзывалась вовсе.
    property real edgeRoom: 0
    readonly property Item hotItem: hot

    // Полоска между карточкой и краем экрана — и только она. Накрывать карточку этой зоной нельзя:
    // наведение достаётся верхнему элементу, и накрывающая зона отбирает его у самой карточки. Так
    // уже вышло: у края значки увеличивались, но нажимать там было нечего, а на самой карточке
    // нажимались, но не увеличивались. Поэтому зон две, они не пересекаются, и каждая делает своё.
    Item {
        id: hot
        x: card.x
        width: card.width
        y: dv.atTop ? card.y - dv.edgeRoom : card.y + card.height
        height: dv.edgeRoom

        HoverHandler {
            id: edgeHover
            onPointChanged: { dv.pointerScene = point.scenePosition.x; dv.engaged = true; dv.wake() }
            onHoveredChanged: {
                if (hovered) { dv.cancelLeave(); dv.engaged = true; dv.pointerScene = point.scenePosition.x }
                else if (!cardHover.hovered && !tipHover.hovered) dv.leaveLane()
                dv.wake()
            }
        }
    }

    // Уход с полосы — с короткой задержкой: курсор часто прыгает с карточки на плашку
    // подписи/превью (и обратно). Без паузы leaveLane гасит tip и срывает engaged → EdgeReveal
    // прячет док, как будто курсор уже ушёл. macOS-док так не делает: пока курсор над доком
    // или его всплывающей UI, полоса остаётся.
    function overDockUi() {
        return cardHover.hovered || edgeHover.hovered || tipHover.hovered
    }
    function cancelLeave() { leaveWait.stop() }
    function leaveLane() { leaveWait.restart() }
    function leaveLaneNow() {
        if (overDockUi()) return
        engaged = false
        ctxClose.restart()
        tipWait.stop()
        tipShown = false
    }
    Timer {
        id: leaveWait
        interval: 220
        onTriggered: dv.leaveLaneNow()
    }

    Rectangle {
        id: card
        width: dv.laneLength
        height: dv.cardHeight
        y: dv.atTop ? 0 : dv.height - height
        radius: Math.round(dv.cardHeight * 0.3)
        // Без размытия под доком та же прозрачность превращается в кашу: значки читаются по тому,
        // что за ними, а не по себе. Нет размытия — нет и прозрачности.
        color: Qt.rgba(0, 0, 0, JD.blurOn ? 0.28 : 0.55)
        border.width: 1
        border.color: Qt.rgba(1, 1, 1, 0.14)

        // Щелчок по пустому месту полосы — мимо значков — тоже закрывает меню. Он объявлен до
        // значков, то есть лежит под ними, и их нажатия у них не отбирает.
        TapHandler {
            acceptedButtons: Qt.LeftButton | Qt.RightButton
            gesturePolicy: TapHandler.ReleaseWithinBounds
            onTapped: { dv.closeCtx(); dv.closeStack() }
        }

        // Курсор берём в координатах сцены нарочно: в координатах карточки он «двигался» бы сам,
        // когда полоса под ним растёт и переезжает, — и получилась бы обратная связь.
        HoverHandler {
            id: cardHover
            onPointChanged: { dv.pointerScene = point.scenePosition.x; dv.engaged = true; dv.wake() }
            onHoveredChanged: {
                if (hovered) { dv.cancelLeave(); dv.engaged = true; dv.pointerScene = point.scenePosition.x }
                else if (!edgeHover.hovered && !tipHover.hovered) dv.leaveLane()
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
                // Тащимый значок идёт за курсором, а его место в полосе уже занято соседями:
                // так видно, куда он встанет, ещё до того, как его отпустили.
                readonly property bool dragged: dv.dragKey !== "" && dv.dragKey === e.key
                // Своей анимации у места быть не должно. Она тут была — и ломала док: анимация
                // включалась только на время перетаскивания, а выключалась ровно в тот миг, когда
                // ещё летела. Qt в этом случае animation останавливает, значение оставляет на
                // полпути, и привязка молчит, пока не поменяется то, от чего она зависит. Значки
                // так и замирали внахлёст. Место значка считает физика полосы — и только она.
                x: (dragged ? dv.dragLocal - g.w / 2 : g.x)
                   + (dv.wheel && dv.nudges.length === dv.lane.length ? dv.nudges[index] : 0)
                z: dragged ? 2 : 0
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
                    // Closed icons sink slightly; running stay at the previous normal height.
                    // Grow from the dock edge so magnification still feels anchored.
                    readonly property real baseY: dv.atTop
                        ? (dv.pad + dv.dotRoom + (slot.running ? 0 : dv.restDrop))
                        : (dv.pad + (slot.running ? 0 : dv.restDrop))
                    y: baseY + slot.bounce
                    Behavior on y { enabled: JD.animOn; NumberAnimation { duration: 160; easing.type: Easing.OutCubic } }
                    // Размер уже посчитан шагом физики — здесь только показываем. Своей анимации
                    // тут быть не должно: она разошлась бы с раскладкой, и значки бы налезли.
                    // Та же история, что и с местом: размер под пальцем считает физика, а
                    // взятый значок просто чуть крупнее. Анимации тут нет нарочно — ей было бы
                    // где замереть на полпути.
                    // Press feedback is macOS-like (subtle scale + light fade). Do NOT drop
                    // opacity to ~0.7: on a dark dock that reads as a black flash.
                    property real pressScale: slotTap.pressed ? 0.9 : 1
                    Behavior on pressScale { enabled: JD.animOn; NumberAnimation { duration: 100; easing.type: Easing.OutCubic } }
                    scale: slot.k * (slot.dragged ? 1.08 : 1) * (drop.containsDrag ? 1.14 : 1) * pressScale
                    Behavior on scale { enabled: JD.animOn && drop.containsDrag
                                        NumberAnimation { duration: 120; easing.type: Easing.OutBack } }
                    transformOrigin: dv.atTop ? Item.Top : Item.Bottom
                    opacity: slot.dragged ? 0.86 : (slotTap.pressed ? 0.88 : 1)
                    Behavior on opacity { enabled: JD.animOn; NumberAnimation { duration: 90 } }

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
                        // Slight inset so filled theme plates (MacTahoe etc.) are not
                        // edge-to-edge in the cell — reads less "solid block", keeps aspect.
                        anchors.fill: parent
                        anchors.margins: Math.round(dv.icon * 0.06)
                        visible: slot.e.t === "app"
                        name: slot.e.icon || ""
                        fallback: "application-x-executable"
                        implicitSize: dv.icon
                        // Растр просят с запасом на увеличение: под курсором значок вырастает в
                        // полтора раза, и нарисованный по обычному размеру он там расплывается.
                        // Prefer ~3x for fine logos (Discord Clyde eyes).
                        renderSize: dv.icon * 3.0
                        theme: true
                        syncLoad: true
                        iconPalette: String(JD.dockCfg.icon_style || "original").toLowerCase()
                        iconPaletteTint: {
                            const t = String(JD.dockCfg.icon_tint || "").trim()
                            return t ? t : "#7AC8FF"
                        }
                    }
                    Icon {
                        anchors.fill: parent
                        visible: slot.e.t === "trash"
                        name: JD.trashFull ? "user-trash-full" : "user-trash"
                        fallback: "user-trash"
                        implicitSize: dv.icon
                        renderSize: dv.icon * 2.4
                        theme: true
                        syncLoad: true
                    }
                    // Кнопка лотка: значки чужих программ за одной кнопкой, вместо полосы, которая
                    // занимает край экрана постоянно. Светится, пока полоса открыта, — иначе
                    // непонятно, нажата она или нет.
                    Item {
                        anchors.fill: parent
                        visible: slot.e.t === "tray"
                        Rectangle {
                            anchors.centerIn: parent
                            width: dv.icon
                            height: dv.icon
                            radius: Math.round(dv.icon * 0.28)
                            color: JD.trayOn ? Qt.rgba(JD.accentBlue.r, JD.accentBlue.g, JD.accentBlue.b, 0.22)
                                             : Qt.rgba(1, 1, 1, 0.10)
                            Behavior on color { enabled: JD.animOn; ColorAnimation { duration: 140 } }
                            Icon {
                                anchors.centerIn: parent
                                name: "layout-grid"
                                fallback: "view-grid"
                                implicitSize: Math.round(dv.icon * 0.58)
                                tint: JD.trayOn ? JD.accentBlue : JD.text1
                            }
                        }
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

                // Под грузом значок светится: цель перетаскивания обязана быть видна без сомнений.
                Rectangle {
                    visible: drop.containsDrag
                    anchors.centerIn: art
                    width: dv.icon * 1.5
                    height: width
                    radius: width / 2
                    color: Qt.rgba(JD.accentBlue.r, JD.accentBlue.g, JD.accentBlue.b, 0.3)
                    z: -1
                }

                // Открыто — отметка под значком. Оно же и подсказка, что значок не запустит
                // второе окно. Вид отметки — на вкус: точка, чёрточка, полоса или свечение.
                Rectangle {
                    visible: dv.mark !== "none"
                    width: dv.mark === "dot" ? (slot.wins.length > 1 ? 10 : 4)
                         : dv.mark === "line" ? Math.round(dv.icon * 0.42)
                         : dv.mark === "bar" ? Math.round(dv.icon * 0.66)
                         : Math.round(dv.icon * 0.8)
                    height: dv.mark === "bar" ? 3 : dv.mark === "glow" ? Math.round(dv.icon * 0.8) : 4
                    radius: height / 2
                    anchors.horizontalCenter: parent.horizontalCenter
                    y: dv.mark === "glow"
                       ? (dv.atTop ? dv.pad + dv.dotRoom : dv.pad) + (dv.icon - height) / 2
                       : dv.atTop ? dv.pad * 0.5 : card.height - dv.labelRoom - dv.pad * 0.5 - height
                    z: dv.mark === "glow" ? -1 : 0
                    color: slot.active ? JD.accentBlue : Qt.rgba(1, 1, 1, 0.55)
                    // Появляется и исчезает, а не мигает: окно закрыли — отметка уходит, уменьшаясь.
                    opacity: !slot.running ? 0 : dv.mark === "glow" ? 0.28 : 1
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

                // Порядок значков — рукой. Порог у DragHandler свой: обычное нажатие остаётся
                // нажатием, перетаскивание начинается только после заметного движения.
                DragHandler {
                    enabled: dv.reorder && slot.e.t === "app" && slot.e.pinned
                    target: null
                    xAxis.enabled: true
                    yAxis.enabled: false
                    onActiveChanged: {
                        if (active) dv.startDrag(slot.e.key)
                        else dv.endDrag()
                    }
                    onCentroidChanged: if (active) dv.moveDrag(centroid.scenePosition.x)
                }

                // Имя под значком — режим «всегда». Оно обрезается по ячейке, а не раздвигает её:
                // док, у которого ширина ячейки зависит от длины имени, перестаёт быть ровным рядом.
                Text {
                    visible: dv.labelMode === "always" && slot.e.t !== "sep" && !!text
                    width: parent.width - 4
                    x: 2
                    y: card.height - dv.labelRoom
                    horizontalAlignment: Text.AlignHCenter
                    elide: Text.ElideRight
                    textFormat: Text.PlainText
                    font.family: JD.fontFamily
                    font.pixelSize: 10
                    color: slot.running ? JD.text1 : JD.text2
                    // Значок меню подписывать нечем: «Программы» в ячейку не влезает и обрезается
                    // в «Програм…», а яблоко и так понятно.
                    text: slot.e.t === "app" ? (slot.e.name || "")
                        : slot.e.t === "trash" ? "Корзина"
                        : slot.e.t === "tray" ? "Лоток" : ""
                }

                // Колесо по значку перебирает окна этой программы — так же, как в доке макоси и в
                // Dockish. Программе с одним окном перебирать нечего, и колесо там молчит.
                WheelHandler {
                    enabled: slot.wins.length > 1
                    onWheel: event => {
                        if (Math.abs(event.angleDelta.y) < 30) return
                        dv.cycle(slot.wins, event.angleDelta.y < 0 ? 1 : -1)
                        event.accepted = true
                    }
                }

                // Бросить файл на значок — отдать его этой программе, на корзину — выбросить. Это
                // то, ради чего док вообще стоит на краю экрана: до него дотягиваются, не отпуская
                // перетаскиваемое. Значок под грузом приподнимается и светится — иначе непонятно,
                // попал ты в него или в соседа, а попасть надо в один из тридцати.
                DropArea {
                    id: drop
                    anchors.fill: parent
                    enabled: slot.e.t === "app" || slot.e.t === "trash"
                    onDropped: event => {
                        if (!event.hasUrls || !event.urls.length) return
                        if (slot.e.t === "trash") JD.dropToTrash(event.urls)
                        else { dv.startBounce(slot.e); JD.dropOn(slot.e, event.urls) }
                        event.accept(Qt.CopyAction)
                    }
                }

                HoverHandler { enabled: slot.e.t !== "sep"; cursorShape: Qt.PointingHandCursor }
                TapHandler {
                    id: slotTap
                    enabled: slot.e.t !== "sep"
                    gesturePolicy: TapHandler.ReleaseWithinBounds
                    // В режиме колеса нажимается то, что защёлкнуто, а не то, под чем курсор: иначе
                    // бывает случай, когда увеличено одно, а запускается другое, — а этого не
                    // должно быть никогда.
                    onTapped: {
                        const e = dv.wheel && dv.committed >= 0 && dv.committed < dv.lane.length
                                ? dv.lane[dv.committed] : slot.e
                        dv.press(e, e.wins || [])
                    }
                }
                // Средняя кнопка закрывает окно. Это самый короткий путь из всех: до «закрыть» в
                // меню правой кнопки три движения, до крестика в чужом заголовке — прицеливание, а
                // здесь значок уже под курсором и уже увеличен. Одно окно — закроется оно; несколько
                // — то, что сейчас наверху, по одному на нажатие, а не все разом: «закрыть всё»
                // средней кнопкой было бы ловушкой.
                TapHandler {
                    enabled: slot.wins.length > 0
                    acceptedButtons: Qt.MiddleButton
                    gesturePolicy: TapHandler.ReleaseWithinBounds
                    onTapped: {
                        const wins = slot.wins
                        const front = wins.find(w => w.active && !w.minimized) || wins.find(w => !w.minimized) || wins[0]
                        if (front) JD.windowDo("close", front.id)
                    }
                }
                TapHandler {
                    enabled: slot.e.t !== "sep"
                    acceptedButtons: Qt.RightButton
                    gesturePolicy: TapHandler.ReleaseWithinBounds
                    onTapped: {
                        // Второй раз по тому же значку — закрыть: иначе единственный способ убрать
                        // меню это целиться мимо, а мимо ещё надо попасть.
                        if (dv.ctxEntry === slot.e) { dv.closeCtx(); return }
                        dv.openCtx(slot.e, slot.wins, slot.g.x + slot.g.w / 2)
                    }
                }
            }
        }
    }


    // Tell the genie effect / overlay where each dock icon sits on the screen.
    function publishIcons() {
        const icons = ({})
        for (let i = 0; i < lane.length; i++) {
            const e = lane[i]
            if (e.t !== "app") continue
            const g = geom[i]
            if (!g) continue
            const r = JD.dockIconScreenRect(g)
            if (!r) continue
            if (e.key) icons[e.key] = r
            if (e.id) icons[String(e.id).toLowerCase()] = r
            // Per-window slots (octium profiles) and appId aliases.
            for (const w of (e.wins || [])) {
                if (w && w.id) icons[String(w.id)] = r
                if (w && w.app) icons[String(w.app).toLowerCase()] = r
            }
            // Bare app id from key app:foo
            if (e.key && e.key.indexOf(":") > 0)
                icons[e.key.split(":").slice(1).join(":").toLowerCase()] = r
        }
        icons["*"] = { x: Math.round(JD.screenWidth / 2 - 24),
                       y: Math.round(dv.atTop ? 8 : JD.screenHeight - 56), w: 48, h: 48 }
        JD.publishDockIcons(icons)
    }
    Timer {
        id: iconPublish
        interval: 280
        onTriggered: dv.publishIcons()
    }
    // Do NOT republish on every magnify geom tick — that rewrote kwinrc + reconfigureEffect
    // dozens of times per second and froze Plasma / blanked dock icons. Rest positions on
    // lane / dockRect / windows changes are enough for the genie effect.
    onAwakeChanged: if (awake) iconPublish.restart()
    Connections {
        target: JD
        function onDockRectChanged() { iconPublish.restart() }
        function onWindowsChanged() { iconPublish.restart() }
    }

    // ───────────── подпись под курсором ─────────────
    //
    // Не сразу: подпись, выскакивающая в тот же миг, превращает проход вдоль дока в мельтешение
    // плашек. Полсекунды — это ровно «я тут остановился и смотрю».
    property bool tipShown: false
    property string tipFor: ""
    // shell.qml mask + EdgeReveal.keepVisible need these from outside DockView.
    readonly property Item tipItem: tip
    readonly property bool tipHovered: tipHover.hovered
    readonly property bool dockUiActive: engaged || tipHovered || tipShown || !!ctxEntry
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
        readonly property bool want: dv.labelMode === "hover" && dv.tipShown && !!dv.focused && !ctx.visible
        readonly property string text: !dv.focused ? ""
            : dv.focused.t === "launcher" ? "Программы"
            : dv.focused.t === "trash" ? (JD.trashFull ? "Корзина — не пуста" : "Корзина пуста")
            : dv.focused.t === "cat" ? "Процессор " + Math.round(JD.cpu) + "%"
            : dv.focused.t === "clock" ? Qt.formatDate(new Date(), "d MMMM, dddd")
            : (dv.focused.name || "")
        readonly property var wins: dv.focused && dv.focused.wins ? dv.focused.wins : []
        // JPEG thumbnail cards only when a real capture path works AND at least one JPEG arrived.
        // Never show empty blue frames with the app logo — that looked like a broken teleport tip.
        readonly property bool thumbsReady: {
            const _ = JD.thumbs
            if (JD.thumbCaptureBroken || !dv.preview || wins.length === 0) return false
            for (let i = 0; i < Math.min(wins.length, 5); i++) {
                if (JD.thumbPath(wins[i].id)) return true
            }
            return false
        }
        readonly property bool showsThumbs: thumbsReady
        // Compact window-title list (macOS/KDE style) when preview is on but thumbs unavailable.
        readonly property bool showsWinList: dv.preview && wins.length > 0 && !showsThumbs
        readonly property bool expanded: showsThumbs || showsWinList
        readonly property int at: dv.focused ? dv.focused.i : -1
        // Ask for thumbs in the background; tip stays classic until a JPEG lands (or capture is marked broken).
        onWinsChanged: tip.requestThumbs()
        onWantChanged: {
            if (want) tip.requestThumbs()
            else { frozenX = liveX; frozenY = liveY }
        }
        function requestThumbs() {
            if (!dv.preview || JD.thumbCaptureBroken) return
            for (const w of wins.slice(0, 5))
                if (w && w.id) JD.requestThumb(w.id)
        }
        // Cap tip width. Chromium/Electron page titles are huge; sizing from
        // titleLab.implicitWidth made a full-width black strip that looked like a broken
        // Helium/CSD title bar floating above the dock — not a real window decoration.
        readonly property real tipMax: Math.min(360, Math.max(200, Math.round(dv.width * 0.42)))
        width: Math.min(tipMax,
                        showsThumbs ? Math.max(tipText.implicitWidth + 20, winRow.implicitWidth + 16)
                      : showsWinList ? Math.max(tipText.implicitWidth + 20, winList.implicitWidth + 20)
                      : tipText.implicitWidth + 20)
        height: showsThumbs ? 28 + winRow.implicitHeight + 10
              : showsWinList ? 28 + winList.implicitHeight + 8
              : 26
        radius: expanded ? 14 : 13
        color: Qt.rgba(0, 0, 0, 0.9)
        border.width: 1
        border.color: Qt.rgba(1, 1, 1, 0.12)
        // Live geometry while shown; freeze last spot while fading out (no lag-slide up-left).
        readonly property real liveX: {
            const g = at >= 0 && at < dv.geom.length ? dv.geom[at] : null
            return Math.max(0, Math.min(dv.width - width, (g ? g.x + g.w / 2 : 0) - width / 2))
        }
        readonly property real liveY: dv.atTop ? card.height + 10 : dv.height - card.height - height - 10
        property real frozenX: 0
        property real frozenY: 0
        x: want ? liveX : frozenX
        y: want ? liveY : frozenY
        opacity: want ? 1 : 0
        visible: opacity > 0.01
        // Opacity fade only — no Behavior on x/y/width/height/scale (those caused the wild leave slide).
        Behavior on opacity { enabled: JD.animOn; NumberAnimation { duration: 120 } }
        Label1 {
            id: tipText
            anchors { top: parent.top; topMargin: 5; horizontalCenter: parent.horizontalCenter }
            width: Math.min(implicitWidth, tip.tipMax - 20)
            elide: Text.ElideRight
            text: tip.text
        }
        // ─── real window thumbnails (Win/KDE task-manager style) ───
        Row {
            id: winRow
            visible: tip.showsThumbs
            anchors { top: tipText.bottom; topMargin: 6; horizontalCenter: parent.horizontalCenter }
            spacing: 8
            Repeater {
                model: tip.showsThumbs ? tip.wins.slice(0, 5) : []
                delegate: Item {
                    id: cardWin
                    required property var modelData
                    width: 148
                    height: 118
                    readonly property string thumb: {
                        const _ = JD.thumbs
                        return JD.thumbPath(modelData.id)
                    }
                    Rectangle {
                        anchors.fill: parent
                        radius: 10
                        color: Qt.rgba(1, 1, 1, thumbCardHover.hovered ? 0.12 : 0.06)
                        border.width: modelData.active ? 2 : 1
                        border.color: modelData.active ? JD.accentBlue : Qt.rgba(1, 1, 1, 0.14)
                        Column {
                            anchors { fill: parent; margins: 6 }
                            spacing: 4
                            Item {
                                width: parent.width
                                height: 72
                                Rectangle {
                                    anchors.fill: parent
                                    radius: 6
                                    color: Qt.rgba(0, 0, 0, 0.45)
                                    clip: true
                                    Image {
                                        anchors.fill: parent
                                        fillMode: Image.PreserveAspectCrop
                                        asynchronous: true
                                        visible: !!cardWin.thumb && !modelData.minimized
                                        source: cardWin.thumb ? ("file://" + cardWin.thumb) : ""
                                    }
                                    Label2 {
                                        anchors.centerIn: parent
                                        visible: !!modelData.minimized || !cardWin.thumb
                                        text: modelData.minimized ? "свернуто" : "…"
                                        color: JD.text3
                                    }
                                }
                            }
                            Label2 {
                                width: parent.width
                                font.pixelSize: 11
                                elide: Text.ElideRight
                                color: modelData.minimized ? JD.text3 : JD.text1
                                text: (modelData.title || "").trim() || "без названия"
                            }
                        }
                    }
                    HoverHandler { id: thumbCardHover }
                    TapHandler {
                        onTapped: {
                            JD.windowDo("focus", String(modelData.id))
                            dv.tipShown = false
                        }
                    }
                }
            }
        }
        // ─── clean macOS-style tip: compact clickable window titles, no empty frames ───
        Column {
            id: winList
            visible: tip.showsWinList
            anchors { top: tipText.bottom; topMargin: 4; horizontalCenter: parent.horizontalCenter }
            spacing: 2
            width: Math.min(tip.tipMax - 20, Math.max(160, tipText.implicitWidth))
            Repeater {
                model: tip.showsWinList ? tip.wins.slice(0, 5) : []
                delegate: Item {
                    required property var modelData
                    // Width from tip cap + app name — never from the raw page title
                    // (titleLab.implicitWidth stretched Helium tips across the screen).
                    width: winList.width
                    height: 22
                    Rectangle {
                        anchors.fill: parent
                        radius: 6
                        color: Qt.rgba(1, 1, 1, winRowHover.hovered ? 0.12 : 0)
                    }
                    Label2 {
                        id: titleLab
                        anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; leftMargin: 8; rightMargin: 8 }
                        font.pixelSize: 11
                        elide: Text.ElideRight
                        color: modelData.minimized ? JD.text3 : (modelData.active ? JD.accentBlue : JD.text1)
                        text: ((modelData.title || "").trim() || "без названия") + (modelData.minimized ? " · свёрнуто" : "")
                    }
                    HoverHandler { id: winRowHover }
                    TapHandler {
                        onTapped: {
                            JD.windowDo("focus", String(modelData.id))
                            dv.tipShown = false
                        }
                    }
                }
            }
            Label2 {
                visible: tip.showsWinList && tip.wins.length > 5
                anchors.horizontalCenter: parent.horizontalCenter
                font.pixelSize: 11
                color: JD.text3
                text: "и ещё " + (tip.wins.length - 5)
            }
        }
        Label2 {
            visible: tip.showsThumbs && tip.wins.length > 5
            anchors { top: winRow.bottom; topMargin: 2; horizontalCenter: parent.horizontalCenter }
            font.pixelSize: 11
            color: JD.text3
            text: "и ещё " + (tip.wins.length - 5)
        }
        // Pointer over the tip counts as still on the dock (do not leaveLane / autohide).
        HoverHandler {
            id: tipHover
            onHoveredChanged: {
                if (hovered) { dv.cancelLeave(); dv.engaged = true }
                else if (!cardHover.hovered && !edgeHover.hovered) dv.leaveLane()
                dv.wake()
            }
        }
    }

    // ───────────── правая кнопка ─────────────
    //
    // Не системное меню, а свои три строки: закрепить, закрыть, настройки. Столько и нужно — всё
    // остальное у программы есть в её собственном окне.
    DockAudio { id: audio }

    // ───────────── стопка ─────────────
    property var stackEntry: null
    property var stackItems: []
    property real stackAt: 0
    function openStack(e) {
        if (!e || !e.id) return
        closeCtx()
        if (stackEntry && stackEntry.id === e.id) { closeStack(); return }
        stackEntry = e
        stackItems = []
        const i = lane.findIndex(s => s.key === e.key)
        stackAt = i >= 0 && geom[i] ? geom[i].x + geom[i].w / 2 : dv.width / 2
        JD.folderList(e.id)
    }
    function closeStack() { stackEntry = null; stackItems = [] }
    Connections {
        target: JD
        function onFolderItemsChanged() {
            if (dv.stackEntry && JD.folderPath === dv.stackEntry.id) dv.stackItems = JD.folderItems
        }
    }

    property var ctxEntry: null
    property var ctxWins: []
    property string ctxConfirm: ""     // пункт, который ждёт второго щелчка
    property real ctxAt: 0
    // Ручьи звука той программы, по которой нажали правой кнопкой. Пересчитываются, когда меняется
    // и выбор, и сам список ручьёв: программа могла заиграть уже после открытия меню.
    readonly property var ctxStreams: ctxEntry ? audio.streamsFor(ctxEntry) : []
    readonly property real ctxVolume: audio.volumeOf(ctxStreams)
    readonly property bool ctxMuted: audio.mutedOf(ctxStreams)
    function openCtx(e, wins, at) {
        if (e.t === "sep") return
        ctxEntry = e; ctxWins = wins || []; ctxAt = at; ctxConfirm = ""
        ctxClose.stop()
    }
    function closeCtx() { ctxEntry = null; ctxWins = []; ctxConfirm = "" }
    Timer { id: ctxClose; interval: 1400; onTriggered: dv.closeCtx() }

    // ───────────── стопка: что лежит в папке ─────────────
    //
    // Решёткой, а не списком: у файлов есть имена, но узнают их по значкам, и в решётке за один
    // взгляд видно вдвое больше. Папки первыми — это то, куда идут дальше, а файлы то, что берут.
    Rectangle {
        id: stack
        visible: !!dv.stackEntry
        width: Math.min(dv.width - 24, 92 * Math.max(1, Math.min(5, dv.stackItems.length)) + 24)
        height: Math.min(360, stackGrid.contentHeight + (stackMore.visible ? 46 : 22))
        radius: 18
        color: Qt.rgba(0, 0, 0, 0.92)
        border.width: 1
        border.color: Qt.rgba(1, 1, 1, 0.12)
        x: Math.max(0, Math.min(dv.width - width, dv.stackAt - width / 2))
        y: dv.atTop ? card.height + 10 : dv.height - card.height - height - 10
        HoverHandler { }

        GridView {
            id: stackGrid
            anchors { fill: parent; margins: 11; bottomMargin: stackMore.visible ? 34 : 11 }
            clip: true
            cellWidth: 92
            cellHeight: 84
            model: dv.stackItems
            boundsBehavior: Flickable.StopAtBounds
            delegate: Item {
                required property var modelData
                width: 92
                height: 84
                Rectangle {
                    anchors.fill: parent
                    anchors.margins: 3
                    radius: 10
                    color: cellHover.hovered ? JD.fill1 : "transparent"
                    Behavior on color { enabled: JD.animOn; ColorAnimation { duration: 110 } }
                }
                Column {
                    anchors.centerIn: parent
                    spacing: 5
                    Icon {
                        anchors.horizontalCenter: parent.horizontalCenter
                        name: modelData.dir ? "folder" : "file"
                        fallback: modelData.dir ? "folder" : "text-x-generic"
                        implicitSize: 30
                        theme: true
                    }
                    Text {
                        width: 82
                        horizontalAlignment: Text.AlignHCenter
                        elide: Text.ElideMiddle
                        maximumLineCount: 2
                        wrapMode: Text.Wrap
                        font.family: JD.fontFamily
                        font.pixelSize: 10
                        color: JD.text2
                        text: modelData.name
                    }
                }
                HoverHandler { id: cellHover; cursorShape: Qt.PointingHandCursor }
                TapHandler {
                    gesturePolicy: TapHandler.ReleaseWithinBounds
                    onTapped: { JD.folderOpen(modelData.path); dv.closeStack() }
                }
            }
        }

        // Папка может быть большой, и честнее сказать, сколько осталось за краем, чем молча
        // показать первые сорок и сделать вид, что это всё.
        Label2 {
            id: stackMore
            visible: JD.folderMore > 0
            anchors { left: parent.left; bottom: parent.bottom; leftMargin: 14; bottomMargin: 10 }
            font.pixelSize: 11
            color: JD.text3
            text: JD.tr("…и ещё ") + JD.folderMore
        }
        PillButton {
            visible: !!dv.stackEntry
            anchors { right: parent.right; bottom: parent.bottom; rightMargin: 11; bottomMargin: 7 }
            height: 24
            label: JD.tr("Открыть папку")
            onClicked: { JD.folderOpen(dv.stackEntry.id); dv.closeStack() }
        }
    }

    Rectangle {
        id: ctx
        visible: !!dv.ctxEntry
        width: Math.max(dv.ctxStreams.length ? 272 : 210, dv.ctxWins.length ? 264 : 0)
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
                delegate: Item {
                    id: ctxRow
                    required property var modelData
                    readonly property bool sep: modelData.id === "sep"
                    readonly property bool asking: dv.ctxConfirm === modelData.id
                    width: parent.width
                    height: sep ? 9 : 32

                    Rectangle {
                        visible: ctxRow.sep
                        anchors.centerIn: parent
                        width: parent.width - 24
                        height: 1
                        color: Qt.rgba(1, 1, 1, 0.08)
                    }

                    Rectangle {
                        visible: !ctxRow.sep
                        anchors.fill: parent
                        color: ctxRow.asking ? Qt.rgba(1, 0.27, 0.23, 0.18)
                             : rowHover.hovered ? JD.fill1 : "transparent"
                        Behavior on color { enabled: JD.animOn; ColorAnimation { duration: 110 } }
                    }
                    Row {
                        visible: !ctxRow.sep
                        anchors.fill: parent
                        anchors.leftMargin: 12
                        anchors.rightMargin: ctxRow.modelData.closes ? 34 : 12
                        spacing: 9
                        Icon {
                            anchors.verticalCenter: parent.verticalCenter
                            name: ctxRow.asking ? "circle-alert" : ctxRow.modelData.icon
                            implicitSize: 15
                            tint: ctxRow.modelData.danger ? JD.accentRed
                                : ctxRow.modelData.dim ? JD.text3 : JD.text1
                        }
                        Label1 {
                            anchors.verticalCenter: parent.verticalCenter
                            width: parent.width - 15 - 9
                            text: ctxRow.asking ? ctxRow.modelData.confirm : ctxRow.modelData.label
                            color: ctxRow.modelData.danger ? JD.accentRed
                                 : ctxRow.modelData.dim ? JD.text3 : JD.text1
                        }
                    }

                    // Крестик у окна закрывает именно его. Он появляется под курсором, а не висит
                    // всегда: строка — это прежде всего «перейти к окну», и красный крестик у
                    // каждой строки превратил бы список окон в список кнопок «уничтожить».
                    Rectangle {
                        visible: !!ctxRow.modelData.closes
                        anchors { right: parent.right; rightMargin: 8; verticalCenter: parent.verticalCenter }
                        width: 22
                        height: 22
                        radius: 11
                        color: killHover.hovered ? Qt.rgba(1, 0.27, 0.23, 0.30) : "transparent"
                        opacity: rowHover.hovered || killHover.hovered ? 1 : 0
                        Behavior on opacity { enabled: JD.animOn; NumberAnimation { duration: 110 } }
                        Icon {
                            anchors.centerIn: parent
                            name: "x"
                            implicitSize: 12
                            tint: killHover.hovered ? JD.accentRed : JD.text2
                        }
                        HoverHandler { id: killHover; cursorShape: Qt.PointingHandCursor }
                        TapHandler {
                            gesturePolicy: TapHandler.ReleaseWithinBounds
                            onTapped: {
                                JD.windowDo("close", String(ctxRow.modelData.closes))
                                if (dv.ctxWins.length <= 1) dv.closeCtx()
                            }
                        }
                    }

                    HoverHandler { id: rowHover; enabled: !ctxRow.sep; cursorShape: Qt.PointingHandCursor }
                    TapHandler {
                        enabled: !ctxRow.sep
                        gesturePolicy: TapHandler.ReleaseWithinBounds
                        onTapped: {
                            // Необратимое ждёт второго щелчка по тому же пункту. Это не «вы
                            // уверены?» перед каждым действием — только перед тем, что нельзя
                            // отменить, и прямо на месте, без отдельного окна.
                            if (ctxRow.modelData.confirm && !ctxRow.asking) {
                                dv.ctxConfirm = ctxRow.modelData.id
                                ctxClose.restart()
                                return
                            }
                            dv.doCtx(ctxRow.modelData.id)
                            dv.closeCtx()
                        }
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
        // Очистить корзину предлагается только тогда, когда в ней что-то есть: пункт, который
        // ничего не делает, — обещание впустую. Он же и единственный необратимый в этом меню,
        // поэтому ждёт второго щелчка.
        if (e.t === "trash") {
            const rows = [{ id: "trash", label: "Открыть корзину", icon: "folder-open" }]
            if (JD.trashFull) rows.push({ id: "empty", label: "Очистить корзину", icon: "trash-2",
                                          danger: true, confirm: "Точно очистить?" })
            return rows
        }
        if (e.t === "cat") return [{ id: "load", label: "Нагрузка машины", icon: "gauge" },
                                   { id: "settings", label: "Настроить док", icon: "sliders-horizontal" }]
        if (e.t === "clock") return [{ id: "settings", label: "Настроить док", icon: "sliders-horizontal" }]
        const out = [{ id: "open", label: "Открыть", icon: "external-link" }]
        if (e.id) out.push(e.pinned ? { id: "unpin", label: "Убрать из дока", icon: "minus" }
                                    : { id: "pin", label: "Оставить в доке", icon: "plus" })
        // Окна перечислены поимённо. Раньше меню умело только «закрыть всё», и чтобы убрать одно
        // лишнее окно из шести, приходилось искать его самому. Строка ведёт к окну, крестик в
        // строке закрывает именно его.
        if (ctxWins.length) {
            out.push({ id: "sep" })
            for (let i = 0; i < ctxWins.length; i++) {
                const w = ctxWins[i]
                out.push({ id: "focus:" + w.id, closes: w.id, dim: !!w.minimized,
                           icon: w.minimized ? "chevron-down" : w.active ? "app-window" : "square",
                           label: JD.flat(w.title || e.name || "Окно") })
            }
            if (ctxWins.length > 1) out.push({ id: "close", label: "Закрыть все окна", icon: "x", danger: true })
            out.push({ id: "sep" })
        }
        out.push({ id: "settings", label: "Настроить док", icon: "sliders-horizontal" })
        return out
    }

    function doCtx(what) {
        const e = ctxEntry, wins = ctxWins
        if (what === "menu") JD.toggleMenu()
        else if (what === "settings") JD.openSettings("dock")
        else if (what === "trash") Quickshell.execDetached(["xdg-open", "trash:///"])
        else if (what === "empty") JD.send({ cmd: "trash_empty" })
        else if (what === "load") JD.openTools("load")
        else if (what === "open") JD.dockRun(e)
        else if (what === "pin") JD.dockPin(e.kind, e.id, true)
        else if (what === "unpin") JD.dockPin(e.kind, e.id, false)
        else if (what === "close") for (const w of wins) JD.windowDo("close", w.id)
        else if (what.startsWith("focus:")) JD.windowDo("focus", what.slice(6))
    }

    // Взяли значок. Порядок замораживаем сразу: дальше он меняется только этим перетаскиванием,
    // и список из-под руки не поедет, если демон в этот момент пришлёт своё.
    function startDrag(key) {
        if (!reorder || !key) return
        pinOverride = JD.dockItems.map(i => i.key)
        dragKey = key
    }

    // Куда значок встаёт: не «перепрыгнул половину соседа», а «курсор оказался над чужой ячейкой».
    // Ячейки под курсором увеличены, и мерить надо по нарисованному — по нему рука и целится.
    function moveDrag(sceneX) {
        dragLocal = sceneX - dv.x - card.x
        if (dragKey === "") return
        const spots = []
        for (let i = 0; i < lane.length; i++)
            if (lane[i].t === "app" && lane[i].pinned) spots.push({ key: lane[i].key, i: i })
        const from = spots.findIndex(s => s.key === dragKey)
        if (from < 0) return
        let to = from
        for (let n = 0; n < spots.length; n++) {
            const g = geom[spots[n].i]
            if (!g) continue
            if (dragLocal >= g.x && dragLocal < g.x + g.w) { to = n; break }
        }
        if (to === from) return
        const next = pinOverride.slice()
        const at = next.indexOf(dragKey)
        if (at < 0) return
        next.splice(at, 1)
        // Порядок в pinOverride и порядок закреплённых ячеек — одно и то же: и там и там только
        // закреплённое, в одном и том же порядке.
        next.splice(to, 0, dragKey)
        pinOverride = next
    }

    function endDrag() {
        if (dragKey === "") return
        dragKey = ""
        // Порядок остаётся местным, пока демон не подтвердит его своим ответом: иначе значок на
        // миг отскакивает туда, откуда его унесли.
        JD.dockArrange(pinOverride)
    }

    // Следующее окно этой же программы. Считаем от того, что сейчас наверху: «следующее» имеет
    // смысл только относительно текущего, а не относительно порядка, в котором окна открывали.
    property real lastCycle: 0
    function cycle(wins, step) {
        if (!wins || wins.length < 2) return
        const now = Date.now()
        if (now - lastCycle < 180) return      // одно движение колеса — одно окно, а не пять
        lastCycle = now
        let at = wins.findIndex(w => w.active && !w.minimized)
        if (at < 0) at = 0
        const next = wins[(at + step + wins.length) % wins.length]
        if (next) JD.windowDo("focus", next.id)
    }

    // Нажатие: не запущено — запустить; запущено и не наверху — поднять; наверху — свернуть.
    // Второй запуск того же — самая частая ошибка дока, и именно её эта развилка убирает.
    function press(e, wins) {
        // Открыто меню правой кнопки — первый щелчок куда угодно его просто закрывает, и больше
        // ничего. Иначе промах мимо меню запускал бы программу, по значку которой промахнулись, —
        // а человек в этот момент хотел всего лишь убрать меню. Второй щелчок уже работает как
        // обычно; так это сделано везде, где меню закрывается щелчком мимо.
        if (ctxEntry) { closeCtx(); return }
        closeCtx()
        if (e.t === "launcher") { JD.toggleMenu(); return }
        // Нажали в доке при открытом меню — меню своё дело сделало и уходит.
        if (JD.menuOpen) JD.closeMenu()
        if (e.t === "trash") { Quickshell.execDetached(["xdg-open", "trash:///"]); return }
        if (e.t === "tray") { JD.trayToggle(); return }
        // Папка в доке — стопка: показать, что внутри, а не открывать файловый менеджер. За самим
        // менеджером человек пойдёт сам, если ему нужна именно папка, а не файл из неё.
        if (e.kind === "dir") { dv.openStack(e); return }
        if (e.t === "cat" || e.t === "clock") { JD.openTools(e.t === "cat" ? "load" : "emoji"); return }
        if (!wins || wins.length === 0) { startBounce(e); JD.dockRun(e); return }
        const front = wins.find(w => w.active && !w.minimized)
        if (front) {
            // Genie: scale each window toward this dock icon, then minimize.
            const g = e.i !== undefined && e.i < dv.geom.length ? dv.geom[e.i] : null
            const iconRect = g ? JD.dockIconScreenRect(g) : null
            for (const w of wins) JD.minimizeGenie(w, iconRect)
            return
        }
        const up = wins.find(w => !w.minimized) || wins[0]
        JD.windowDo("focus", up.id)
    }

    // Перетаскивание без мыши: взять n-й закреплённый значок, отнести в точку x спокойной полосы
    // и отпустить. Отдаёт получившийся порядок и места ячеек — по ним видно и наложение.
    function dragProbe(n, x) {
        const spots = lane.filter(s => s.t === "app" && s.pinned)
        const pick = spots[Math.max(0, Math.min(spots.length - 1, n))]
        if (!pick) return JSON.stringify({ pinned: 0 })
        engaged = true
        pointerScene = anchorCentre - restLength / 2 + x
        startDrag(pick.key)
        moveDrag(pointerScene)
        for (let i = 0; i < 200 && stepPhysics(1 / 120); i++) { /* до схождения */ }
        const order = lane.filter(s => s.t === "app" && s.pinned).map(s => s.key)
        // Проверка не переставляет значки по-настоящему: она смотрит, что получилось бы, и
        // кладёт всё обратно. Иначе каждый запуск проверки менял бы человеку док.
        dragKey = ""
        pinOverride = []
        engaged = false
        pointerScene = -99999
        wake()
        let overlap = 0
        for (let i = 1; i < lane.length; i++)
            if (geom[i].x + 0.5 < geom[i - 1].x + geom[i - 1].w) overlap++
        return JSON.stringify({ took: pick.key, order: order, overlap: overlap,
                                cells: lane.map((s, i) => [s.t, Math.round(geom[i].x), Math.round(geom[i].w)]) })
    }

    // Прогулка курсора по полосе маленькими шагами: где именно колесо щёлкает. Одной пробой этого
    // не увидеть — гистерезис по определению зависит от того, откуда пришли, а каждая проба
    // начинает с чистого листа. Здесь состояние живёт от шага к шагу, как под настоящей рукой.
    function wheelWalk(from, to, steps) {
        const was = engaged, wasAt = pointerScene, wasCommit = committed
        engaged = true
        committed = -1
        const events = []
        const n = Math.max(2, Math.min(400, steps || 60))
        let last = -1
        for (let k = 0; k < n; k++) {
            const x = from + (to - from) * k / (n - 1)
            pointerScene = anchorCentre - restLength / 2 + x
            for (let f = 0; f < 3; f++) stepPhysics(1 / 120)
            if (committed !== last) {
                events.push({ x: Math.round(x), cell: committed,
                              name: committed >= 0 && committed < lane.length
                                    ? (lane[committed].name || lane[committed].t) : "" })
                last = committed
            }
        }
        const centres = lane.map((s, i) => ({ t: s.t, c: Math.round(restCentre(i)) }))
        engaged = was
        pointerScene = wasAt
        committed = wasCommit
        wake()
        return JSON.stringify({ from: from, to: to, commits: events, centres: centres })
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
                      wheel: wheel, committed: committed,
                      committedName: wheel && committed >= 0 && committed < lane.length ? (lane[committed].name || lane[committed].t) : "",
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
