// Вынесено из shell.qml (Р-80).
import QtQuick
import QtQuick.Layouts
import QtQuick.Shapes
import Quickshell
import Quickshell.Services.Pipewire

View {
    id: ev
    property string pendingProvider: ""
    property int voiceWas: 0   // the level the mute button came from, for the way back
    property int musicWas: 0
    readonly property var player: JD.playerInExpanded ? JD.musicPlayer : null
    readonly property var sink: Pipewire.defaultAudioSink
    PwObjectTracker { objects: ev.sink ? [ev.sink] : [] }
    SystemClock { id: evClock; precision: SystemClock.Minutes }
    // В правке справа выезжает галерея виджетов: пульт раздвигается, а не теснится.
    readonly property int galW: 300
    implicitWidth: 740 + (editing ? galW : 0)
    implicitHeight: editing ? Math.max(620, Math.min(col.implicitHeight + 40, 800)) : Math.min(col.implicitHeight + 40, 800)

    // Правка самого меню, как раскладка значков на айфоне: блоки подрагивают, у каждого красный минус
    // (или правая кнопка мыши) прячет его, перетаскиванием меняется порядок, а спрятанное лежит внизу
    // и возвращается нажатием. Порядок хранит GridLayout (Layout.row у блоков), поэтому блоки не пришлось
    // дробить на компоненты; поверх них в режиме правки лежит слой с перехватом мыши (`eo`).
    readonly property bool editing: JD.menuEditing
    // Пульт — сетка на четыре колонки, как виджеты на айфоне. Раньше плеер и плитки были одним блоком:
    // спрятать плеер значило спрятать и кофе, а кофе занимал две клетки, потому что пятой плитке
    // в сетке на две колонки было больше негде стоять. Теперь каждая плитка — свой виджет со своим
    // размером (`island.menu_sizes`, «id:размер»), а порядок общий (`island.menu_order`).
    readonly property var blockIds: ["ask", "player", "t_mic", "t_voice", "t_sounds", "t_notifs",
        "t_coffee", "t_wifi", "t_bt", "t_server", "sound", "event", "model", "lists",
        "w_clock", "w_weather", "w_load", "w_note",
        "a_shot", "a_emoji", "a_clip", "a_mixer", "a_load", "a_files", "a_kde", "a_update"]
    // Новые виджеты (16 нояб.) по умолчанию не на пульте: их берут из галереи справа в правке.
    // Пульт у всех уже настроен — внезапно выросший вдвое он был бы не подарком, а беспорядком.
    readonly property var optIn: ["t_server", "w_clock", "w_weather", "w_load", "w_note",
        "a_shot", "a_emoji", "a_clip", "a_mixer", "a_load", "a_files", "a_kde", "a_update"]
    readonly property var blocks: ({ ask: blkAsk, player: blkPlayer, sound: blkSound, event: blkEvent, model: blkModel, lists: blkLists,
        t_mic: tMic, t_voice: tVoice, t_sounds: tSounds, t_notifs: tNotifs, t_coffee: tCoffee, t_wifi: tWifi, t_bt: tBt, t_server: tServer,
        w_clock: wClock, w_weather: wWeather, w_load: wLoad, w_note: wNote,
        a_shot: aShot, a_emoji: aEmoji, a_clip: aClip, a_mixer: aMixer, a_load: aLoad, a_files: aFiles, a_kde: aKde, a_update: aUpdate })
    // Размеры пишутся в четвертях ширины, как раньше («2x1» — половина пульта в один ряд), а сетка
    // внутри на восемь колонок: так появилась плитка «h» шириной в полколонки — одна иконка
    // (16 нояб.: «кнопки размером в иконку»), и сохранённые размеры не поехали. Хвост «v» — стоймя.
    // Первый размер в списке — размер по умолчанию.
    readonly property var tileSizes: ["1x1", "hx1", "2x1", "1x2", "4x1"]
    readonly property var sizeChoices: ({ ask: ["4x1", "2x1", "3x1", "1x1", "hx1"],
        player: ["2x2", "3x2", "4x2", "4x1", "2x1", "1x1", "1x2"],
        sound: ["4x1", "2x1", "2x2v", "1x2v", "1x1", "hx2v"],
        event: ["4x1", "2x1", "1x1", "2x2"], model: ["4x1", "2x2"], lists: ["4x1"],
        w_clock: ["2x1", "4x1", "2x2", "1x1", "1x2"], w_weather: ["2x1", "2x2", "4x1", "1x1", "1x2"],
        w_load: ["2x1", "4x1", "2x2", "1x1", "1x2"], w_note: ["2x2", "4x1", "2x1", "4x2", "1x1", "1x2"] })
    // [ширина в восьмых, высота в рядах]
    function dims(sz) { const m = String(sz).match(/^([h\d])x(\d)/); return m ? [m[1] === "h" ? 1 : 2 * +m[1], +m[2]] : [8, 1] }
    function choices(id) { return sizeChoices[id] || tileSizes }
    function sizeOf(id) {
        const all = Array.isArray(JD.island.menu_sizes) ? JD.island.menu_sizes : []
        for (const x of (forcedSizes || all)) { const kv = String(x).split(":"); if (kv[0] === id && choices(id).includes(kv[1])) return kv[1] }
        return choices(id)[0]
    }
    function vert(id) { return sizeOf(id).endsWith("v") }
    property var forcedSizes: null
    function cycleSize(id) {
        const c = choices(id)
        setSize(id, c[(c.indexOf(sizeOf(id)) + 1) % c.length], true)
    }
    function setSize(id, size, save) {
        if (size === sizeOf(id) && !save) return
        const rest = (forcedSizes || (Array.isArray(JD.island.menu_sizes) ? JD.island.menu_sizes : [])).filter(x => String(x).split(":")[0] !== id)
        forcedSizes = rest.concat([id + ":" + size])
        if (save) JD.setConfig("island.menu_sizes", forcedSizes)
    }
    // Растягивание за уголок (16 нояб.: «брать за правый нижний кончик и тянуть»). Рамка идёт за
    // курсором свободно, а виджет на ходу встаёт в ближайший из своих размеров — сетка
    // перестраивается прямо под рукой, сохраняется по отпусканию.
    property string resizeId: ""
    property real resizeW: 0
    property real resizeH: 0
    function resizeTo(id, w, h, rowH) {
        const cw = (col.width + col.columnSpacing) / 8, rh = rowH + col.rowSpacing
        const wantW = (w + col.columnSpacing) / cw, wantH = (h + col.rowSpacing) / rh
        let best = sizeOf(id), bestD = 1e9
        for (const c of choices(id)) {
            const m = dims(c), d = Math.abs(m[0] - wantW) / 2 + Math.abs(m[1] - wantH)
            if (d < bestD - 0.01) { bestD = d; best = c }
        }
        setSize(id, best, false)
    }
    // Есть ли что показать: спрятанное и пустое (нет события, нет уведомлений) места не занимает.
    function present(id) {
        if (id === "lists") return (JD.notifications.length > 0 && JD.island.show_notifications !== false) || (JD.history.length > 0 && JD.island.menu_recent !== false)
        if (id === "event") return !!JD.nextEvent && isShown(id)
        return isShown(id)
    }
    // Раскладка: по порядку, каждый виджет в первое свободное место не выше предыдущего. Однострочный
    // виджет, после которого ряд до конца пуст, растягивается до края — иначе одна плитка в ряду
    // оставляла бы дыру (как было с кофе).
    readonly property var grid: {
        const busy = [], out = {}
        const free = (r, c, w, h) => { for (let y = r; y < r + h; y++) for (let x = c; x < c + w; x++) if (x > 7 || (busy[y] && busy[y][x])) return false; return true }
        let top = 0
        for (const id of order) {
            if (!present(id)) continue
            const m = dims(sizeOf(id)), w = m[0], h = m[1]
            let r = top, c = 0
            while (!free(r, c, w, h)) { if (++c > 8 - w) { c = 0; r++ } }
            for (let y = r; y < r + h; y++) { busy[y] = busy[y] || []; for (let x = c; x < c + w; x++) busy[y][x] = id }
            out[id] = { r: r, c: c, w: w, h: h }
            top = r
        }
        // Растягиваем только размер по умолчанию: выбранный руками остаётся каким выбран. Иначе
        // уменьшить последний в ряду виджет было нельзя — он тут же вырастал обратно до края (16 нояб.).
        for (const id in out) {
            const g = out[id]
            if (g.h !== 1 || chosen(id)) continue
            let end = g.c + g.w
            while (end < 8 && !busy[g.r][end]) end++
            if (end === 8 && busy[g.r].slice(g.c + g.w).every(x => !x)) g.w = 8 - g.c
        }
        return out
    }
    function g(id) { return grid[id] || ({ r: 0, c: 0, w: 8, h: 1 }) }
    function chosen(id) { return (forcedSizes || (Array.isArray(JD.island.menu_sizes) ? JD.island.menu_sizes : [])).some(x => String(x).split(":")[0] === id) }
    readonly property var blockNames: ({ ask: JD.tr("Строка запроса"), player: JD.tr("Музыка"),
        t_mic: JD.tr("Микрофон"), t_voice: JD.tr("Голос"), t_sounds: JD.tr("Звуки"), t_notifs: JD.tr("Плитка уведомлений"),
        t_coffee: JD.tr("Кофе"), t_wifi: "Wi‑Fi", t_bt: "Bluetooth", t_server: JD.tr("Режим сервера"), lists: JD.tr("Списки"),
        sound: JD.tr("Громкость"), event: JD.tr("Ближайшее событие"), model: JD.tr("Модель"),
        notifs: JD.tr("Уведомления"), recent: JD.tr("Недавнее"),
        w_clock: JD.tr("Часы"), w_weather: JD.tr("Погода"), w_load: JD.tr("Нагрузка"), w_note: JD.tr("Заметка"),
        a_shot: JD.tr("Снимок экрана"), a_emoji: JD.tr("Эмодзи"), a_clip: JD.tr("Буфер обмена"), a_mixer: JD.tr("Микшер"),
        a_load: JD.tr("Диспетчер"), a_files: JD.tr("Файлы"), a_kde: JD.tr("Настройки KDE"), a_update: JD.tr("Обновление"),
        top_chat: JD.tr("Кнопка чата"), top_tools: JD.tr("Кнопка инструментов"), top_settings: JD.tr("Кнопка настроек") })
    readonly property var topIds: ["top_chat", "top_tools", "top_settings"]
    // Верхняя кнопка: в правке нажатие прячет её (красный минус в углу), в обычном режиме — делает своё.
    component TopBtn: IconButton {
        id: tb
        property string bid
        property var act
        size: 32
        // В правке спрятанная кнопка остаётся на своём месте, тусклая и с зелёным плюсом: раньше
        // убранное пропадало, и где его вернуть, было не догадаться.
        readonly property bool off: !ev.isShown(tb.bid)
        visible: !off || ev.editing
        opacity: off ? 0.35 : 1
        onClicked: ev.editing ? (off ? ev.unhide(tb.bid) : ev.hide(tb.bid)) : tb.act()
        Rectangle {
            visible: ev.editing
            width: 14; height: 14; radius: 7
            anchors { top: parent.top; right: parent.right; margins: -3 }
            color: tb.off ? JD.accentGreen : JD.accentRed
            Rectangle { anchors.centerIn: parent; width: 7; height: 2; color: "white" }
            Rectangle { visible: tb.off; anchors.centerIn: parent; width: 2; height: 7; color: "white" }
        }
    }
    component GTile: Tile {
        id: gt
        property string bid
        visible: ev.present(bid)
        Layout.row: 10 + ev.g(bid).r
        Layout.column: ev.g(bid).c
        Layout.rowSpan: ev.g(bid).h
        Layout.columnSpan: ev.g(bid).w
        Layout.preferredWidth: 0
        Layout.minimumWidth: 0
        Layout.fillHeight: true
        rotation: ev.editing ? ev.wig * ev.sign(bid) : 0
        transform: [Scale { xScale: ev.fl(gt.bid).sx; yScale: ev.fl(gt.bid).sy },
                    Translate { x: (ev.dragId === gt.bid ? ev.dragDx : 0) + ev.fl(gt.bid).x; y: (ev.dragId === gt.bid ? ev.dragDy : 0) + ev.fl(gt.bid).y },
                    Translate { y: gt.hovered && !ev.editing ? -2 : 0; Behavior on y { enabled: JD.animOn; NumberAnimation { duration: JD.durFast; easing.type: JD.easeOut } } }]
        z: ev.dragId === bid ? 5 : 0
        // В правке плитка — предмет, а не выключатель: нажатие на её красный минус включало
        // заодно и саму плитку (Wi‑Fi гас, когда его убирали, 16 нояб.).
        pressEnabled: !ev.editing
    }
    // Карточка-виджет в сетке пульта: место, размер, покачивание в правке — как у плитки.
    component GBox: Rectangle {
        id: gb
        property string bid
        visible: ev.present(bid)
        Layout.row: 10 + ev.g(bid).r
        Layout.column: ev.g(bid).c
        Layout.rowSpan: ev.g(bid).h
        Layout.columnSpan: ev.g(bid).w
        Layout.preferredWidth: 0
        Layout.minimumWidth: 0
        Layout.fillWidth: true
        Layout.fillHeight: true
        implicitHeight: 62
        radius: 18
        property color tint: JD.fill1   // свой оттенок виджета, как у плиток
        color: Qt.tint(gbHover.hovered && !ev.editing ? JD.fill2 : JD.fill1, Qt.rgba(tint.r, tint.g, tint.b, 0.06))
        Behavior on color { enabled: JD.animOn; ColorAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
        HoverHandler { id: gbHover }
        clip: true
        rotation: ev.editing ? ev.wig * ev.sign(bid) : 0
        transform: [Scale { xScale: ev.fl(gb.bid).sx; yScale: ev.fl(gb.bid).sy },
                    Translate { x: (ev.dragId === gb.bid ? ev.dragDx : 0) + ev.fl(gb.bid).x; y: (ev.dragId === gb.bid ? ev.dragDy : 0) + ev.fl(gb.bid).y },
                    Translate { y: gbHover.hovered && !ev.editing ? -2 : 0; Behavior on y { enabled: JD.animOn; NumberAnimation { duration: JD.durFast; easing.type: JD.easeOut } } }]
        z: ev.dragId === bid ? 5 : 0
    }
    // Плитка-действие: не выключатель, а кнопка «сделай» — круг значка не загорается.
    component ATile: GTile { on: false; lit: true; offText: onText; sound: "click" }
    // Неизвестное из конфига отбрасываем, пропавшее (новый блок после обновления) дописываем в конец.
    // `forced` держит порядок до ответа демона: иначе блок после броска на миг прыгал бы обратно.
    property var forced: null
    readonly property var order: {
        if (forced) return forced
        const saved = Array.isArray(JD.island.menu_order) ? JD.island.menu_order.filter((x, i, a) => blockIds.includes(x) && a.indexOf(x) === i) : []
        // Новый виджет встаёт за тем, за кем стоит по умолчанию: плитки, вынутые из старого блока
        // «player», оказываются сразу за плеером, а не в самом низу.
        for (let i = 0; i < blockIds.length; i++) {
            const id = blockIds[i]
            if (saved.includes(id)) continue
            const at = i ? saved.indexOf(blockIds[i - 1]) : -1
            saved.splice(at + 1, 0, id)
        }
        return saved
    }
    Connections { target: JD; function onIslandChanged() { ev.forced = null; ev.forcedSizes = null } }
    // Режим сервера гасит экраны — случайное нажатие слишком дорого, поэтому плитка по умолчанию спрятана.
    function isShown(id) { const v = JD.island["menu_" + id]; return optIn.includes(id) ? v === true : v !== false }
    function flagKey(id) { return id === "notifs" ? "island.show_notifications" : "island.menu_" + id }
    // Удаление и возврат — с движением: «хоп, и всё удалилось» выглядело как сбой (16 нояб.).
    // Виджет сжимается и гаснет, и только потом прячется; возвращённый вырастает из 0.6.
    function hide(id) {
        const b = blocks[id]
        if (!b || !b.visible || !JD.animOn) { JD.setConfig(flagKey(id), false); return }
        outAnim.stop()
        outAnim.target = b; outAnim.bid = id
        outAnim.start()
    }
    function unhide(id) {
        const b = blocks[id]
        if (b && JD.animOn) { b.opacity = 0; b.scale = 0.6; inAnim.target = b; inAnim.restart() }
        JD.setConfig(flagKey(id), true)
    }
    ParallelAnimation {
        id: outAnim
        property Item target
        property string bid
        NumberAnimation { target: outAnim.target; property: "scale"; to: 0.6; duration: 200; easing.type: Easing.InCubic }
        NumberAnimation { target: outAnim.target; property: "opacity"; to: 0; duration: 200; easing.type: Easing.InCubic }
        onFinished: {
            JD.setConfig(ev.flagKey(bid), false)
            // Вернуть вид сразу: спрятанный блок невидим и так, а пропусти мы это — он однажды
            // вернётся из «Спрятано» прозрачным.
            target.scale = 1; target.opacity = 1
        }
    }
    SequentialAnimation {
        id: inAnim
        property Item target
        // ответ демона приходит не сразу: без паузы блок вырос бы ещё невидимым
        PauseAnimation { duration: 120 }
        ParallelAnimation {
            NumberAnimation { target: inAnim.target; property: "scale"; to: 1; duration: 320; easing.type: Easing.OutBack; easing.overshoot: 1.4 }
            NumberAnimation { target: inAnim.target; property: "opacity"; to: 1; duration: 220; easing.type: Easing.OutCubic }
        }
    }
    function sign(id) { return order.indexOf(id) % 2 ? -1 : 1 }   // соседние блоки качаются в разные стороны
    function resetMenu() {
        forced = null
        forcedSizes = []
        JD.setConfig("island.menu_order", blockIds)
        JD.setConfig("island.menu_sizes", [])
        for (const id of blockIds.filter(x => x !== "lists" && !optIn.includes(x)).concat(["notifs", "recent"], topIds)) unhide(id)
        for (const id of optIn) if (isShown(id)) hide(id)
    }

    // Перетаскивание: пока блок тянут, он едет за пальцем (dragDy), порядок меняется при отпускании.
    property string dragId: ""
    property real dragDx: 0
    property real dragDy: 0
    property real wig: 0
    SequentialAnimation on wig {
        running: ev.editing && JD.animOn
        loops: Animation.Infinite
        NumberAnimation { to: 0.45; duration: 110 }
        NumberAnimation { to: -0.45; duration: 220 }
        NumberAnimation { to: 0; duration: 110 }
    }
    // Перестройка сетки — плавно (16 нояб.: «чтобы анимация изменения размера была плавнее»).
    // GridLayout ставит блоки сразу на новое место, Behavior на его x/width не срабатывает: раскладка
    // пишет их мимо QML. Поэтому FLIP: запомнили, где блок был, после раскладки сдвинули его
    // трансформом назад на старое место и в старый размер, а потом один общий flipT отпускает всех
    // к нулю. Одна анимация на весь пульт, а не по одной на каждый из двух десятков блоков.
    property var flipFrom: ({})
    property real flipT: 0
    property var dropAt: null   // брошенный блок едет из-под пальца, а не из своей старой клетки
    readonly property var flipNone: ({ x: 0, y: 0, sx: 1, sy: 1 })
    // «Кирпичики» (16 нояб.: «чтобы перемещение ощущалось не группой, а кирпичиками»): flipT идёт
    // линейно, а у каждого блока свой отрезок внутри него — волна по порядку чтения, свой перелёт
    // и лёгкий подъём в полёте, будто блок взяли рукой и поставили на новое место.
    readonly property int flipStep: 45
    function fl(id) {
        const f = flipFrom[id], t = flipT
        if (!f || t === 0) return flipNone
        const total = JD.durSlow + flipStep * f.n
        const u = Math.max(0, Math.min(1, ((1 - t) * total - flipStep * f.i) / JD.durSlow))
        const c = 1.7, e = 1 + (c + 1) * Math.pow(u - 1, 3) + c * Math.pow(u - 1, 2)   // OutBack
        const k = 1 - e, lift = 1 + 0.025 * Math.sin(Math.PI * u)
        return { x: f.dx * k, y: f.dy * k, sx: (1 + (f.sw - 1) * k) * lift, sy: (1 + (f.sh - 1) * k) * lift }
    }
    function geo() {
        const out = {}
        for (const id of blockIds) { const b = blocks[id]; if (b && b.visible) out[id] = [b.x, b.y, b.width, b.height] }
        return out
    }
    onGridChanged: {
        if (!JD.animOn || !shown) return
        const was = geo(), d = dropAt
        dropAt = null
        if (d && was[d.id]) { was[d.id][0] += d.dx; was[d.id][1] += d.dy }
        Qt.callLater(() => {
            col.ensurePolished()   // раскладка — сейчас, а не в следующем кадре: иначе кадр мелькнул бы без сдвига
            const now = geo(), from = {}
            for (const id in now) {
                const a = was[id], b = now[id]
                if (!a || b[2] <= 0 || b[3] <= 0) continue
                if (Math.abs(a[0] - b[0]) + Math.abs(a[1] - b[1]) + Math.abs(a[2] - b[2]) + Math.abs(a[3] - b[3]) < 1) continue
                from[id] = { dx: a[0] - b[0], dy: a[1] - b[1], sw: a[2] / b[2], sh: a[3] / b[3] }
            }
            const ids = Object.keys(from)
            if (!ids.length) return
            ids.sort((p, q) => (now[p][1] - now[q][1]) || (now[p][0] - now[q][0]))
            ids.forEach((id, i) => { from[id].i = i; from[id].n = ids.length - 1 })
            flipAnim.duration = JD.durSlow + flipStep * (ids.length - 1)
            flipAnim.stop()
            flipFrom = from
            flipT = 1
            flipAnim.start()
        })
    }
    NumberAnimation {
        id: flipAnim
        target: ev; property: "flipT"; to: 0
        // линейно: перелёт и задержку каждому блоку считает fl()
    }
    function drop() {
        const id = dragId
        if (!id) return
        const b = blocks[id], cx = b.x + b.width / 2 + dragDx, cy = b.y + b.height / 2 + dragDy
        let hit = ""
        for (const o of order) {
            const t = blocks[o]
            if (o !== id && t.visible && cx >= t.x && cx <= t.x + t.width && cy >= t.y && cy <= t.y + t.height) { hit = o; break }
        }
        const moved = { id: id, dx: dragDx, dy: dragDy }
        dragId = ""; dragDx = 0; dragDy = 0
        const next = order.filter(x => x !== id)
        if (hit) {
            // Брошенный встаёт на место того, в кого попал: тянули вперёд — за ним, назад — перед ним.
            const fwd = order.indexOf(hit) > order.indexOf(id)
            next.splice(next.indexOf(hit) + (fwd ? 1 : 0), 0, id)
        } else {
            // Брошен в пустое место (16 нояб.: «пытаюсь перенести — не получается»: Микшер в дыру
            // после Bluetooth возвращался назад). Встаёт перед первым блоком, который по порядку
            // чтения идёт после точки броска, а если такого нет — в конец.
            const after = next.find(o => { const t = blocks[o]
                return t && t.visible && (cy < t.y || (cy <= t.y + t.height && cx < t.x + t.width / 2)) })
            next.splice(after ? next.indexOf(after) : next.length, 0, id)
            if (next.join() === order.join()) return
        }
        dropAt = moved
        forced = next
        JD.setConfig("island.menu_order", next)
    }
    Shortcut { sequence: "Escape"; enabled: JD.menuEditing; onActivated: JD.menuEditing = false }
    // Долгое нажатие на пустое место меню: тот же вход, что и карандаш.
    TapHandler { onLongPressed: JD.menuEditing = true }

    function setting(key, value) { JD.setConfig(key, value) }
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
        anchors { fill: parent; rightMargin: ev.editing ? ev.galW : 0 }
        contentHeight: col.implicitHeight + 40
        clip: true
        interactive: contentHeight > height
        boundsBehavior: Flickable.StopAtBounds

    GridLayout {
        id: col
        x: 20
        y: 20
        width: evFlick.width - 40
        columns: 8
        rowSpacing: 12
        columnSpacing: 12

        // Ряд-распорка: по одной нулевой ячейке в колонку, чтобы восемь колонок были равными, а не
        // по ширине того, что в них попало.
        Repeater {
            model: 8
            Item { required property int index; Layout.row: 9; Layout.column: index; Layout.fillWidth: true
                   Layout.preferredWidth: 1000; Layout.minimumWidth: 0; implicitHeight: 0 }
        }

        // ── header: who, what it is doing · time, date, weather · settings
        RowLayout {
            Layout.row: 0
            Layout.columnSpan: 8
            Layout.fillWidth: true
            spacing: 14
            Orb { visible: JD.orbsOn; main: true; size: 36 }
            Ring { size: 36; visible: !JD.orbsOn }
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
                        // Р3-5: длинная подсказка обрезалась многоточием; клавиша — единственное, что
                        // из неё нужно, и она помещается.
                        : ({ idle: JD.tr("Готов · ") + (JD.micOn ? (JD.hotkeys.talk || "Meta+J") : (JD.hotkeys.type || "Meta+K")),
                             listening: JD.tr("Слушаю"), transcribing: JD.tr("Распознаю"), thinking: JD.activity || JD.tr("Работаю"),
                             speaking: JD.tr("Говорит"), approval: JD.tr("Ждёт подтверждения"), offline: JD.islandOnly ? JD.tr("Джарвис запускается…") : JD.tr("Демон не запущен") })[JD.dstate] || JD.dstate
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
            // П14: громкость голоса сверху убрана — такая же есть в блоке «Громкость». Верхние кнопки
            // прячутся в правке, как и блоки; «Править» стоит последней перед крестиком и не прячется,
            // иначе спрятав всё, человек не нашёл бы, как вернуть.
            TopBtn { bid: "top_chat"; icon: "message-circle"; act: () => { JD.expanded = false; JD.chatOpen = true } }   // отдельный чат: файлы, история
            TopBtn { bid: "top_tools"; icon: "wand-sparkles"; act: () => JD.openTools("emoji") }
            TopBtn { bid: "top_settings"; icon: "configure"; act: () => JD.openSettings("general") }
            IconButton { icon: "pencil"; size: 32; onClicked: JD.menuEditing = !JD.menuEditing }   // правка меню; правка островка — из неё же
            IconButton { icon: "window-close"; size: 32; onClicked: JD.expanded = false }
        }

        // update available
        Rectangle {
            visible: !!JD.update
            Layout.row: 1
            Layout.columnSpan: 8
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
            visible: ev.present("ask")
            id: blkAsk
            Layout.row: 10 + ev.g("ask").r
            Layout.column: ev.g("ask").c
            Layout.rowSpan: ev.g("ask").h
            Layout.columnSpan: ev.g("ask").w
            Layout.preferredWidth: 0
            Layout.minimumWidth: 0
            Layout.fillHeight: true
            rotation: ev.editing ? ev.wig * ev.sign("ask") : 0
            transform: [Scale { xScale: ev.fl("ask").sx; yScale: ev.fl("ask").sy },
                        Translate { x: (ev.dragId === "ask" ? ev.dragDx : 0) + ev.fl("ask").x; y: (ev.dragId === "ask" ? ev.dragDy : 0) + ev.fl("ask").y }]
            z: ev.dragId === "ask" ? 5 : 0
            Layout.fillWidth: true
            implicitHeight: 46
            radius: 23
            color: askHover.hovered ? JD.fill2 : JD.fill1
            Behavior on color { enabled: JD.animOn; ColorAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
            // Узкая строка — короче подпись, без подсказки клавиши; в полколонки — одна лупа.
            readonly property bool tiny: width < 120
            RowLayout {
                anchors { fill: parent; leftMargin: blkAsk.tiny ? 0 : 16; rightMargin: blkAsk.tiny ? 0 : 6 }
                spacing: 8
                Icon { name: "search"; fallback: "edit-find"; implicitSize: blkAsk.tiny ? 20 : 16; opacity: 0.6; Layout.alignment: Qt.AlignCenter; Layout.fillWidth: blkAsk.tiny }
                Text { visible: !blkAsk.tiny; font.family: JD.fontFamily; text: blkAsk.width < 320 ? JD.tr("Спросить…") : JD.tr("Спросите или попросите что-нибудь…")
                       color: JD.text3; font.pixelSize: 14; Layout.fillWidth: true; elide: Text.ElideRight }
                Rectangle {
                    visible: !!JD.hotkeys.type && blkAsk.width > 420
                    implicitWidth: hk.implicitWidth + 12; implicitHeight: 22; radius: 6
                    color: JD.fill1
                    Text { id: hk; anchors.centerIn: parent; text: JD.hotkeys.type || ""; color: JD.text2; font.family: JD.fontFamily; font.pixelSize: 11 }
                }
                IconButton { visible: JD.micOn && !blkAsk.tiny; icon: "audio-input-microphone"; size: 34; onClicked: { JD.expanded = false; JD.send({ cmd: "listen" }) } }
            }
            HoverHandler { id: askHover; cursorShape: Qt.IBeamCursor }
            TapHandler { onTapped: JD.openCompose() }
        }

        // ── now playing
        Item {
            visible: ev.present("player")
            id: blkPlayer
            Layout.row: 10 + ev.g("player").r
            Layout.column: ev.g("player").c
            Layout.rowSpan: ev.g("player").h
            Layout.columnSpan: ev.g("player").w
            Layout.preferredWidth: 0
            Layout.minimumWidth: 0
            Layout.fillHeight: true
            rotation: ev.editing ? ev.wig * ev.sign("player") : 0
            transform: [Scale { xScale: ev.fl("player").sx; yScale: ev.fl("player").sy },
                        Translate { x: (ev.dragId === "player" ? ev.dragDx : 0) + ev.fl("player").x; y: (ev.dragId === "player" ? ev.dragDy : 0) + ev.fl("player").y }]
            z: ev.dragId === "player" ? 5 : 0
            Layout.fillWidth: true
            // В один ряд плеер не тянет за собой высоту полного вида — иначе ряд раздувался бы до 136
            implicitHeight: ev.g("player").h >= 2 ? np.implicitHeight : 62
            // Сетка делит высоту двухрядного блока по рядам как вздумается: рядом с громкостью
            // в 2x1 плеер получал меньше своего, и кнопки обрезались снизу (16 нояб., скриншот).
            Layout.minimumHeight: ev.g("player").h >= 2 ? np.implicitHeight : 0
            Rectangle {
                id: np
                // Маленький плеер (16 нояб.: «разные размеры каждого виджета»): в ряд — обложка,
                // название и кнопки; узкий стоячий — обложка над кнопками.
                readonly property bool small: height < 110 || width < 260
                readonly property bool stack: small && height >= 110
                // Невысокий полный плеер: сетка отдаёт двум рядам меньше, чем ему нужно, и нижняя
                // строка кнопок обрезалась (16 нояб.: «посмотри же на эту красоту»). Тогда кнопки
                // встают справа от названия, а снизу остаётся одна полоса времени.
                readonly property bool low: !small && height < 168
                anchors.fill: parent
                readonly property bool own: JD.musicOn
                readonly property bool any: own || !!ev.player
                readonly property var p: JD.player || ({})
                property color tint: own ? JD.artTint(p.color) : JD.accentPink
                Behavior on tint { enabled: JD.animOn; ColorAnimation { duration: JD.durSlow; easing.type: JD.easeOut } }
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
                GridLayout {
                    visible: np.small
                    anchors { fill: parent; margins: 10 }
                    columns: np.stack ? 1 : 3
                    columnSpacing: 10; rowSpacing: 6
                    Art {
                        Layout.alignment: Qt.AlignCenter
                        size: np.stack ? Math.min(64, np.width - 20) : Math.min(44, np.height - 18)
                        tint: np.tint; src: np.own ? (np.p.thumb || "") : (ev.player ? ev.player.trackArtUrl || "" : "")
                    }
                    ColumnLayout {
                        visible: np.stack || np.width >= 300
                        spacing: 0
                        Layout.fillWidth: true
                        Label1 { text: !np.any ? JD.tr("Ничего не играет") : np.own ? (np.p.title || "") : ev.player ? (JD.cleanTitle(ev.player.trackTitle) || ev.player.identity) : ""
                                 font.pixelSize: 12; Layout.fillWidth: true; elide: Text.ElideRight
                                 horizontalAlignment: np.stack ? Text.AlignHCenter : Text.AlignLeft }
                        Label2 { visible: np.any; text: np.own ? (np.p.artist || "") : ev.player ? (ev.player.trackArtist || "") : ""
                                 font.pixelSize: 11; Layout.fillWidth: true; elide: Text.ElideRight
                                 horizontalAlignment: np.stack ? Text.AlignHCenter : Text.AlignLeft }
                    }
                    Item { visible: !np.stack && np.width < 300; Layout.fillWidth: true }
                    RowLayout {
                        Layout.alignment: Qt.AlignCenter
                        spacing: 2
                        IconButton { visible: np.any && (np.stack || np.width >= 220); icon: "media-skip-backward"; size: 28
                                     onClicked: np.own ? JD.media("prev") : ev.player.previous() }
                        Rectangle {
                            implicitWidth: 34; implicitHeight: 34; radius: 17
                            color: np.tint
                            PlayGlyph { anchors.centerIn: parent; size: 13; tint: "black"; paused: !np.any || (np.own ? !!np.p.paused : !(ev.player && ev.player.isPlaying)) }
                            HoverHandler { cursorShape: Qt.PointingHandCursor }
                            TapHandler { onTapped: {
                                if (!np.any) { JD.expanded = false; JD.playerPage = "library"; JD.libRefresh(); JD.playerOpen = true }
                                else if (np.own) JD.media("toggle")
                                else ev.player.togglePlaying()
                            } }
                        }
                        IconButton { visible: np.any; icon: "media-skip-forward"; size: 28
                                     onClicked: np.own ? JD.media("next") : ev.player.next() }
                    }
                }
                // something plays
                ColumnLayout {
                    visible: np.any && !np.small
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
                            Label1 { text: np.own ? (np.p.title || "") : ev.player ? (JD.cleanTitle(ev.player.trackTitle) || ev.player.identity) : ""; font.pixelSize: 14; Layout.fillWidth: true; elide: Text.ElideRight }
                            Label2 { text: np.own ? (np.p.artist || "") : ev.player ? (ev.player.trackArtist || "") : ""; Layout.fillWidth: true; elide: Text.ElideRight }
                        }
                        RowLayout {
                            visible: np.low
                            spacing: 2
                            IconButton { icon: "media-skip-backward"; size: 30; onClicked: np.own ? JD.media("prev") : ev.player.previous() }
                            Rectangle {
                                implicitWidth: 38; implicitHeight: 38; radius: 19
                                color: np.tint
                                PlayGlyph { anchors.centerIn: parent; size: 14; tint: "black"; paused: np.own ? !!np.p.paused : !(ev.player && ev.player.isPlaying) }
                                HoverHandler { cursorShape: Qt.PointingHandCursor }
                                TapHandler { onTapped: np.own ? JD.media("toggle") : ev.player.togglePlaying() }
                            }
                            IconButton { icon: "media-skip-forward"; size: 30; onClicked: np.own ? JD.media("next") : ev.player.next() }
                        }
                        IconButton { visible: np.own && !np.low; icon: "view-fullscreen"; size: 28; Layout.alignment: Qt.AlignTop
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
                                Behavior on height { enabled: JD.animOn; NumberAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
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
                        visible: !np.low
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
                    visible: !np.any && !np.small
                    anchors { fill: parent; margins: 14 }
                    spacing: 6
                    RowLayout {
                        spacing: 10
                        Rectangle {
                            implicitWidth: 44; implicitHeight: 44; radius: 12
                            color: "#fc3c44"
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
                               onClicked: { JD.expanded = false; JD.playerPage = "library"; JD.libRefresh(); JD.playerOpen = true } }
                    }
                }
            }
        }

        // ── плитки: каждая своим виджетом
        GTile { id: tMic; bid: "t_mic"; icon: JD.micOn ? "mic" : "mic-off"; title: JD.tr("Микрофон"); onText: JD.tr("голос и текст"); offText: JD.tr("только текст")
                on: JD.micOn; tint: JD.accentCyan; onToggled: ev.setting("audio.microphone", !JD.micOn) }
        GTile { id: tVoice; bid: "t_voice"; icon: "audio-speakers"; title: JD.tr("Голос")
                onText: JD.tr("отвечает вслух")
                offText: JD.muted ? JD.tr("молчит по просьбе") : JD.tr("только текстом")
                on: JD.voiceOn; tint: JD.accentBlue; onToggled: ev.toggleVoice() }
        GTile { id: tSounds; bid: "t_sounds"; icon: "audio-lines"; title: JD.tr("Звуки"); onText: JD.tr("сигналы"); offText: JD.tr("тишина")
                on: !!JD.settings.earcons; tint: JD.accentOrange
                onToggled: ev.setting("audio.earcons", !JD.settings.earcons) }
        GTile { id: tNotifs; bid: "t_notifs"; icon: "preferences-desktop-notification-bell"; title: JD.tr("Уведомления"); onText: JD.tr("на острове"); offText: JD.tr("не беспокоить")
                on: JD.island.show_notifications !== false; tint: JD.accentPurple
                onToggled: ev.setting("island.show_notifications", JD.island.show_notifications === false) }
        GTile { id: tCoffee; bid: "t_coffee"; icon: "coffee"; title: JD.tr("Кофе"); onText: JD.tr("экран не гаснет"); offText: JD.tr("экран гаснет сам")
                on: JD.coffeeOn; tint: JD.accentOrange
                onToggled: ev.setting("desktop.coffee", !JD.coffeeOn) }
        GTile { id: tWifi; bid: "t_wifi"; icon: JD.wifiOn ? "wifi" : "wifi-off"; title: "Wi‑Fi"
                onText: JD.netKind === "wifi" && JD.netName ? JD.netName : JD.tr("включён"); offText: JD.tr("выключен")
                on: JD.wifiOn; tint: JD.accentBlue; onToggled: JD.setWifi(!JD.wifiOn)
                holdable: true; onHeld: radioSheet.show("wifi") }
        GTile { id: tBt; bid: "t_bt"; icon: "bluetooth"; title: "Bluetooth"
                onText: JD.tr("включён"); offText: JD.tr("выключен")
                on: JD.btOn; tint: JD.accentBlue; onToggled: JD.setBt(!JD.btOn)
                holdable: true; onHeld: radioSheet.show("bt") }
        GTile { id: tServer; bid: "t_server"; icon: "moon"; title: JD.tr("Режим сервера"); onText: JD.tr("экраны погашены"); offText: JD.tr("обычная работа")
                on: JD.serverMode; tint: JD.accentPurple; onToggled: JD.toggleServerMode() }

        // ── виджеты из галереи (16 нояб.)
        GBox {
            id: wClock; bid: "w_clock"; tint: JD.accentBlue
            ColumnLayout {
                anchors.centerIn: parent
                spacing: 0
                Text { Layout.alignment: Qt.AlignHCenter; text: Qt.formatTime(evClock.date, "HH:mm"); color: JD.text1; font.family: JD.fontFamily
                       font.pixelSize: Math.min(wClock.height > 100 ? 52 : 30, wClock.width / 3.3); font.weight: Font.Bold; font.features: { "tnum": 1 } }
                Label2 { Layout.alignment: Qt.AlignHCenter; text: evClock.date.toLocaleDateString(Qt.locale(JD.lang === "en" ? "en_US" : "ru_RU"), wClock.width < 200 ? "ddd, d MMM" : "dddd, d MMMM"); font.pixelSize: 11 }
            }
        }
        GBox {
            id: wWeather; bid: "w_weather"; tint: JD.accentOrange
            readonly property bool big: height > 100
            GridLayout {
                anchors.centerIn: parent
                columns: wWeather.big ? 1 : 2
                columnSpacing: 12; rowSpacing: 4
                Image { Layout.alignment: Qt.AlignHCenter; source: JD.weather ? Quickshell.shellDir + "/icons/" + JD.weather.icon + ".svg" : ""
                        sourceSize: Qt.size(64, 64); Layout.preferredWidth: wWeather.big ? 44 : 30; Layout.preferredHeight: Layout.preferredWidth }
                ColumnLayout {
                    spacing: 0
                    Text { Layout.alignment: wWeather.big ? Qt.AlignHCenter : Qt.AlignLeft
                           text: JD.weather ? (JD.weather.temp > 0 ? "+" : "") + JD.weather.temp + "°" : "—"; color: JD.text1; font.family: JD.fontFamily
                           font.pixelSize: wWeather.big ? 30 : 22; font.weight: Font.Bold }
                    Label2 { Layout.alignment: wWeather.big ? Qt.AlignHCenter : Qt.AlignLeft; text: JD.weather ? JD.tr(JD.weather.text || "") : JD.tr("нет данных"); font.pixelSize: 11 }
                }
            }
        }
        GBox {
            id: wLoad; bid: "w_load"; tint: JD.accentGreen
            // Процессор и память — те же цифры, что у кошки в доке (демон шлёт их раз в две секунды).
            ColumnLayout {
                anchors { fill: parent; margins: 12 }
                spacing: 6
                Repeater {
                    model: [{ n: JD.tr("Процессор"), v: JD.cpu, c: JD.accentBlue }, { n: JD.tr("Память"), v: JD.mem, c: JD.accentPurple }]
                    ColumnLayout {
                        required property var modelData
                        Layout.fillWidth: true
                        spacing: 3
                        RowLayout {
                            Label2 { text: modelData.n; font.pixelSize: 11; Layout.fillWidth: true }
                            Label1 { text: Math.round(modelData.v) + "%"; font.pixelSize: 11; font.features: { "tnum": 1 } }
                        }
                        Rectangle {
                            Layout.fillWidth: true; implicitHeight: 5; radius: 2.5; color: JD.fill2
                            Rectangle { width: parent.width * Math.min(1, modelData.v / 100); height: parent.height; radius: 2.5; color: modelData.c
                                        Behavior on width { enabled: JD.animOn; NumberAnimation { duration: JD.durSlow; easing.type: Easing.OutCubic } } }
                        }
                    }
                }
            }
            TapHandler { enabled: !ev.editing; onTapped: JD.openTools("load") }
            HoverHandler { cursorShape: Qt.PointingHandCursor }
        }
        GBox {
            id: wNote; bid: "w_note"; tint: JD.accentPurple
            // Заметка живёт в настройках островка (island.menu_note_text): одна, короткая, «не забыть».
            Flickable {
                anchors { fill: parent; margins: 12 }
                contentHeight: noteEdit.implicitHeight
                clip: true
                TextEdit {
                    id: noteEdit
                    width: parent.width
                    wrapMode: TextEdit.Wrap
                    color: JD.text1
                    font.family: JD.fontFamily
                    font.pixelSize: 13
                    selectByMouse: true
                    Component.onCompleted: text = JD.island.menu_note_text || ""
                    onTextChanged: noteSave.restart()
                    Label2 {
                        visible: !noteEdit.text && !noteEdit.activeFocus
                        text: JD.tr("Заметка: нажмите и пишите")
                        font.pixelSize: 13
                    }
                }
            }
            Timer { id: noteSave; interval: 700; onTriggered: if (noteEdit.text !== (JD.island.menu_note_text || "")) JD.setConfig("island.menu_note_text", noteEdit.text) }
        }
        ATile { id: aShot; bid: "a_shot"; icon: "camera"; title: JD.tr("Снимок"); onText: JD.tr("область экрана")
                onToggled: { JD.closeAll(); Quickshell.execDetached(["spectacle", "-r"]) } }
        ATile { id: aEmoji; bid: "a_emoji"; icon: "smile"; title: JD.tr("Эмодзи"); onText: JD.tr("найти и вставить"); onToggled: JD.openTools("emoji") }
        ATile { id: aClip; bid: "a_clip"; icon: "clipboard"; title: JD.tr("Буфер"); onText: JD.tr("что копировали"); onToggled: JD.openTools("clip") }
        ATile { id: aMixer; bid: "a_mixer"; icon: "volume-2"; title: JD.tr("Микшер"); onText: JD.tr("звук программ"); onToggled: JD.openTools("mixer") }
        ATile { id: aLoad; bid: "a_load"; icon: "cpu"; title: JD.tr("Диспетчер"); onText: JD.tr("что грузит машину"); onToggled: JD.openTools("load") }
        ATile { id: aFiles; bid: "a_files"; icon: "folder-open"; title: JD.tr("Файлы"); onText: JD.tr("домашняя папка")
                onToggled: { JD.closeAll(); Quickshell.execDetached(["xdg-open", Quickshell.env("HOME")]) } }
        ATile { id: aKde; bid: "a_kde"; icon: "sliders-horizontal"; title: JD.tr("Система"); onText: JD.tr("настройки KDE")
                onToggled: { JD.closeAll(); JD.systemSettings("") } }
        ATile { id: aUpdate; bid: "a_update"; icon: "download"; title: JD.tr("Обновление"); onText: JD.tr("проверить сейчас"); onToggled: JD.checkUpdate() }

        // ── sound: the assistant, the music, the whole computer. Three knobs in one card, each one only
        //    moves what it names — turning the assistant down leaves every other app where it was.
        Rectangle {
            visible: ev.present("sound")
            id: blkSound
            Layout.row: 10 + ev.g("sound").r
            Layout.column: ev.g("sound").c
            Layout.rowSpan: ev.g("sound").h
            Layout.columnSpan: ev.g("sound").w
            Layout.preferredWidth: 0
            Layout.minimumWidth: 0
            Layout.fillHeight: true
            rotation: ev.editing ? ev.wig * ev.sign("sound") : 0
            transform: [Scale { xScale: ev.fl("sound").sx; yScale: ev.fl("sound").sy },
                        Translate { x: (ev.dragId === "sound" ? ev.dragDx : 0) + ev.fl("sound").x; y: (ev.dragId === "sound" ? ev.dragDy : 0) + ev.fl("sound").y }]
            z: ev.dragId === "sound" ? 5 : 0
            Layout.fillWidth: true
            implicitHeight: sndCol.implicitHeight + 24
            radius: 20
            color: JD.fill1
            // Стоймя ползунки встают рядом, по одному на каждую ручку.
            GridLayout {
                id: sndCol
                readonly property bool v: ev.vert("sound")
                // Маленькая громкость (1x1, полколонки стоймя) — одна ручка, общая для компьютера
                readonly property bool one: ["1x1", "hx2v"].includes(ev.sizeOf("sound"))
                columns: v && !one ? 3 : 1
                uniformCellWidths: v
                columnSpacing: 4
                rowSpacing: 6
                anchors { left: parent.left; right: parent.right; verticalCenter: parent.verticalCenter; leftMargin: v ? 8 : 10; rightMargin: v ? 8 : 16 }
                VolumeRow {
                    vertical: sndCol.v
                    visible: !sndCol.one
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
                    vertical: sndCol.v
                    readonly property var pl: JD.musicOn ? null : ev.player
                    readonly property bool viaMpris: !!pl && pl.volumeSupported && pl.canControl
                    readonly property var stream: pl && !viaMpris ? JD.playerStream(pl) : null
                    PwObjectTracker { objects: otherVol.stream ? [otherVol.stream] : [] }
                    property real was: 0.7
                    visible: !sndCol.one && (viaMpris || (!!stream && !!stream.audio))
                    icon: "audio-x-generic"; label: pl ? pl.identity : ""; tint: JD.accentPink
                    value: viaMpris ? pl.volume : (stream && stream.audio ? stream.audio.volume : 0)
                    function put(v) { if (viaMpris) pl.volume = v; else if (stream && stream.audio) stream.audio.volume = v }
                    onMoved: v => put(v)
                    onMuteToggled: { const now = value; put(now > 0 ? 0 : (was || 0.7)); was = now }
                }
                VolumeRow {
                    vertical: sndCol.v
                    visible: !otherVol.visible && !sndCol.one
                    readonly property int level: JD.player && JD.player.volume !== undefined ? JD.player.volume : (JD.mediaCfg.volume !== undefined ? JD.mediaCfg.volume : 70)
                    icon: "audio-x-generic"; label: JD.tr("Музыка")
                    tint: JD.musicOn ? JD.artTint(JD.player.color) : JD.accentPink
                    value: level / 100
                    onMoved: v => JD.media("volume", Math.round(v * 100))
                    onMuteToggled: { JD.media("volume", level > 0 ? 0 : (ev.musicWas || 70)); ev.musicWas = level }
                }
                VolumeRow {
                    vertical: sndCol.v
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
            Layout.row: 2
            Layout.columnSpan: 8
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
            Layout.row: 3
            Layout.columnSpan: 8
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
            visible: ev.present("event")
            id: blkEvent
            Layout.row: 10 + ev.g("event").r
            Layout.column: ev.g("event").c
            Layout.rowSpan: ev.g("event").h
            Layout.columnSpan: ev.g("event").w
            Layout.preferredWidth: 0
            Layout.minimumWidth: 0
            Layout.fillHeight: true
            rotation: ev.editing ? ev.wig * ev.sign("event") : 0
            transform: [Scale { xScale: ev.fl("event").sx; yScale: ev.fl("event").sy },
                        Translate { x: (ev.dragId === "event" ? ev.dragDx : 0) + ev.fl("event").x; y: (ev.dragId === "event" ? ev.dragDy : 0) + ev.fl("event").y }]
            z: ev.dragId === "event" ? 5 : 0
            Layout.fillWidth: true
            implicitHeight: 40
            radius: 14
            color: JD.fill1
            // Высокое событие — время крупно, название в несколько строк; узкое — время над названием.
            readonly property bool tall: height > 100
            readonly property bool narrow: width < 260
            Rectangle { x: 12; y: 12; width: 4; height: parent.height - 24; radius: 2; color: JD.accentOrange }
            GridLayout {
                anchors { fill: parent; leftMargin: 26; rightMargin: 12; topMargin: blkEvent.tall ? 12 : 0; bottomMargin: blkEvent.tall ? 12 : 0 }
                columns: blkEvent.tall || blkEvent.narrow ? 1 : 2
                columnSpacing: 10; rowSpacing: blkEvent.tall ? 4 : 0
                Label1 { text: JD.nextEvent ? Qt.formatTime(new Date(JD.nextEvent.start), "HH:mm") : ""; color: JD.accentOrange
                         font.pixelSize: blkEvent.tall ? 28 : 13; font.weight: blkEvent.tall ? Font.Bold : Font.DemiBold
                         Layout.alignment: blkEvent.tall ? Qt.AlignTop : Qt.AlignVCenter }
                Label1 { text: JD.nextEvent ? JD.nextEvent.title : ""; font.weight: Font.Normal; Layout.fillWidth: true
                         Layout.fillHeight: blkEvent.tall; verticalAlignment: blkEvent.tall ? Text.AlignTop : Text.AlignVCenter
                         wrapMode: blkEvent.tall ? Text.WordWrap : Text.NoWrap; maximumLineCount: 4; elide: Text.ElideRight }
            }
        }

        // ── model
        // Квадратная «Модель» (2x2) — кнопки в два столбца, а не в одну строку
        GridLayout {
            visible: ev.present("model")
            id: blkModel
            Layout.row: 10 + ev.g("model").r
            Layout.column: ev.g("model").c
            Layout.rowSpan: ev.g("model").h
            Layout.columnSpan: ev.g("model").w
            Layout.preferredWidth: 0
            Layout.minimumWidth: 0
            Layout.fillHeight: true
            rotation: ev.editing ? ev.wig * ev.sign("model") : 0
            transform: [Scale { xScale: ev.fl("model").sx; yScale: ev.fl("model").sy },
                        Translate { x: (ev.dragId === "model" ? ev.dragDx : 0) + ev.fl("model").x; y: (ev.dragId === "model" ? ev.dragDy : 0) + ev.fl("model").y }]
            z: ev.dragId === "model" ? 5 : 0
            Layout.fillWidth: true
            columns: ev.g("model").w >= 8 ? 6 : 2
            columnSpacing: 10; rowSpacing: 8
            SectionLabel { text: JD.tr("МОДЕЛЬ"); Layout.alignment: Qt.AlignVCenter }
            // На Windows думают только бесплатные модели по ключу (freellm): Claude Code и локальной
            // модели там нет, и выбор «Claude/Локальная» молча ничего не менял. Вместо него — ключи.
            Repeater {
                model: Qt.platform.os === "windows" ? JD.freeProviders : []
                Component.onCompleted: if (Qt.platform.os === "windows") JD.send({ cmd: "free_key" })
                Rectangle {
                    required property var modelData
                    Layout.fillWidth: true
                    implicitHeight: 40
                    radius: 12
                    color: keyHover.hovered ? JD.fill2 : JD.fill1
                    ColumnLayout {
                        anchors.centerIn: parent
                        spacing: -1
                        Text { font.family: JD.fontFamily; text: modelData.name; color: JD.text1; font.pixelSize: 12; font.weight: Font.DemiBold; Layout.alignment: Qt.AlignHCenter }
                        Text { font.family: JD.fontFamily; text: modelData.has ? JD.tr("ключ есть") : JD.tr("вставить ключ"); color: modelData.has ? JD.text3 : JD.accentBlue; font.pixelSize: 10; Layout.alignment: Qt.AlignHCenter }
                    }
                    HoverHandler { id: keyHover; cursorShape: Qt.PointingHandCursor }
                    TapHandler { onTapped: JD.openTools("welcome") }
                }
            }
            Repeater {
                model: Qt.platform.os === "windows" ? [] : [
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
                    Behavior on color { enabled: JD.animOn; ColorAnimation { duration: JD.durBase; easing.type: JD.easeOut } }
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
            Layout.row: 99
            Layout.columnSpan: 8
            Layout.fillWidth: true
            spacing: 10
            Label2 { text: JD.tr("Модель сменится после перезапуска (текущий разговор начнётся заново)"); Layout.fillWidth: true }
            PillButton { label: JD.tr("Перезапустить"); tint: JD.accentBlue; onClicked: { JD.run(["restart"]); ev.pendingProvider = "" } }
        }

        // ── notifications | recent
        RowLayout {
            visible: ev.present("lists")
            id: blkLists
            Layout.row: 10 + ev.g("lists").r
            Layout.column: ev.g("lists").c
            Layout.rowSpan: ev.g("lists").h
            Layout.columnSpan: ev.g("lists").w
            Layout.preferredWidth: 0
            Layout.minimumWidth: 0
            Layout.fillHeight: true
            rotation: ev.editing ? ev.wig * ev.sign("lists") : 0
            transform: [Scale { xScale: ev.fl("lists").sx; yScale: ev.fl("lists").sy },
                        Translate { x: (ev.dragId === "lists" ? ev.dragDx : 0) + ev.fl("lists").x; y: (ev.dragId === "lists" ? ev.dragDy : 0) + ev.fl("lists").y }]
            z: ev.dragId === "lists" ? 5 : 0
            Layout.fillWidth: true
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
                visible: JD.history.length > 0 && JD.island.menu_recent !== false
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

        // ── в режиме правки: спрятанное и кнопки выхода
        ColumnLayout {
            visible: ev.editing
            Layout.row: 100
            Layout.columnSpan: 8
            Layout.fillWidth: true
            spacing: 8
            Label2 { text: JD.tr("Красный минус или правая кнопка прячет виджет, перетаскивание меняет порядок, уголок справа снизу тянется — так меняется размер."); Layout.fillWidth: true; wrapMode: Text.WordWrap }
            RowLayout {
                Layout.fillWidth: true
                spacing: 8
                PillButton { label: JD.tr("Вернуть как было"); onClicked: ev.resetMenu() }
                Item { Layout.fillWidth: true }
                PillButton { label: JD.tr("Правка островка"); onClicked: { JD.menuEditing = false; JD.expanded = false; JD.editMode = true } }
                PillButton { label: JD.tr("Готово"); tint: JD.accentBlue; onClicked: JD.menuEditing = false }
            }
        }
    }

    // Слой правки: лежит поверх блоков, глотает нажатия (иначе кнопки под ним продолжали бы работать),
    // ловит перетаскивание и правую кнопку. Шевелится вместе с блоком, чтобы рамка не отставала.
    Item {
        id: eo
        visible: ev.editing
        width: evFlick.width
        height: col.implicitHeight + 40
        Repeater {
            model: ev.blockIds
            Item {
                id: slot
                required property string modelData
                readonly property Item blk: ev.blocks[modelData]
                readonly property bool lists: modelData === "lists"
                readonly property bool hasNotifs: JD.notifications.length > 0 && JD.island.show_notifications !== false
                readonly property bool hasRecent: JD.history.length > 0 && JD.island.menu_recent !== false
                visible: !!blk && blk.visible
                x: col.x + blk.x + (ev.dragId === modelData ? ev.dragDx : 0)
                y: col.y + blk.y + (ev.dragId === modelData ? ev.dragDy : 0)
                width: blk.width
                height: blk.height
                z: ev.dragId === modelData ? 10 : 1
                // Пока целятся в уголок или тянут его — не качается: в качающийся угол не попасть
                rotation: ev.editing && !cornerHover.hovered && ev.resizeId !== modelData ? ev.wig * ev.sign(modelData) : 0
                Rectangle {
                    anchors.fill: parent
                    radius: 16
                    color: ev.dragId === slot.modelData ? Qt.rgba(1, 1, 1, 0.06) : "transparent"
                    border.width: 1
                    border.color: Qt.rgba(1, 1, 1, 0.16)
                }
                MouseArea {
                    anchors.fill: parent
                    acceptedButtons: Qt.AllButtons
                    cursorShape: ev.dragId === slot.modelData ? Qt.ClosedHandCursor : Qt.OpenHandCursor
                    // Один обработчик на всю карточку, а что делать — решает место нажатия: из уголка
                    // тянется размер, из остального — перенос. Раньше у уголка был свой DragHandler, и
                    // жест забирал обработчик карточки: размер менялся только с полоски за краем
                    // (16 нояб., «в третий раз говорю, размер менять неудобно»).
                    DragHandler {
                        id: slotDrag
                        target: null
                        property bool sizing: false
                        property real w0: 0
                        property real h0: 0
                        property real rowH: 0
                        onActiveChanged: {
                            if (active) {
                                const p = centroid.pressPosition
                                sizing = corner.visible && p.x >= slot.width - corner.width && p.y >= slot.height - corner.height
                                if (sizing) {
                                    w0 = slot.width; h0 = slot.height
                                    rowH = (slot.height - (corner.span - 1) * col.rowSpacing) / corner.span
                                    ev.resizeW = w0; ev.resizeH = h0; ev.resizeId = slot.modelData
                                } else { ev.dragId = slot.modelData; ev.dragDx = 0; ev.dragDy = 0 }
                            } else if (sizing) {
                                ev.setSize(slot.modelData, ev.sizeOf(slot.modelData), true)
                                ev.resizeId = ""
                            } else ev.drop()
                        }
                        // Сдвиг по сцене: карточка сама едет (за курсором или в новую клетку), и
                        // translation, посчитанный от неё, гулял.
                        onCentroidChanged: if (active) {
                            const dx = centroid.scenePosition.x - centroid.scenePressPosition.x
                            const dy = centroid.scenePosition.y - centroid.scenePressPosition.y
                            if (sizing) {
                                ev.resizeW = w0 + dx; ev.resizeH = h0 + dy
                                ev.resizeTo(slot.modelData, ev.resizeW, ev.resizeH, rowH)
                            } else { ev.dragDx = dx; ev.dragDy = dy }
                        }
                    }
                    TapHandler {
                        acceptedButtons: Qt.RightButton
                        onTapped: point => {
                            if (!slot.lists) ev.hide(slot.modelData)
                            else if (slot.hasNotifs && (point.position.x < slot.width / 2 || !slot.hasRecent)) ev.hide("notifs")
                            else if (slot.hasRecent) ev.hide("recent")
                        }
                    }
                }
                // Призрак размера: пока тянут уголок, рамка идёт за курсором, а виджет под ней
                // прыгает в ближайший свой размер — видно и куда тянешь, и что получится.
                Rectangle {
                    visible: ev.resizeId === slot.modelData
                    width: Math.max(40, ev.resizeW); height: Math.max(40, ev.resizeH)
                    radius: 16
                    color: Qt.rgba(1, 1, 1, 0.05)
                    border.width: 2
                    border.color: JD.accentBlue
                }
                // Уголок размера справа снизу. Тянуть — менять размер, нажать — следующий размер
                // (на случай, когда тянуть неудобно, например на тачпаде).
                Item {
                    id: corner
                    visible: ev.choices(slot.modelData).length > 1
                    readonly property int span: { const m = ev.sizeOf(slot.modelData).match(/x(\d)/); return m ? +m[1] : 1 }
                    // Ловится с запасом (16 нояб.: «нужно прям очень наводиться»): дуга та же, а
                    // зона захвата — квадрат 52 вглубь карточки и за её край. У плитки в иконку
                    // поменьше, иначе за саму плитку было бы не взяться.
                    // Зона целиком внутри карточки: выступ за край накрывала соседняя карточка
                    // (она выше по порядку), и вместо размера начиналось перетаскивание соседа.
                    width: Math.min(64, slot.width * 0.5); height: Math.min(64, slot.height * 0.6)
                    x: (ev.resizeId === slot.modelData ? ev.resizeW : slot.width) - width
                    y: (ev.resizeId === slot.modelData ? ev.resizeH : slot.height) - height
                    z: 5
                    Rectangle {   // подсветка зоны, чтобы было видно, что взялся
                        anchors.fill: parent; radius: width / 2
                        color: Qt.rgba(1, 1, 1, cornerHover.hovered || ev.resizeId === slot.modelData ? 0.08 : 0)
                        Behavior on color { enabled: JD.animOn; ColorAnimation { duration: JD.durFast } }
                    }
                    Shape {
                        x: parent.width - 20; y: parent.height - 20
                        width: 22; height: 22
                        preferredRendererType: Shape.CurveRenderer
                        ShapePath {
                            strokeColor: "white"; strokeWidth: 4; fillColor: "transparent"; capStyle: ShapePath.RoundCap
                            startX: 22; startY: 4
                            PathArc { x: 4; y: 22; radiusX: 18; radiusY: 18 }
                        }
                        // дуга идёт вдоль скругления карточки, по ту сторону рамки — как у виджетов айфона
                        scale: cornerHover.hovered || ev.resizeId === slot.modelData ? 1.2 : 1
                        Behavior on scale { enabled: JD.animOn; NumberAnimation { duration: JD.durFast; easing.type: JD.easeOut } }
                    }
                    HoverHandler { id: cornerHover; cursorShape: Qt.SizeFDiagCursor }
                    TapHandler { onTapped: ev.cycleSize(slot.modelData) }
                }
                // красный минус: у нижнего ряда их два, по одному на половину
                Repeater {
                    model: slot.lists ? [{ id: "notifs", on: slot.hasNotifs, at: 0 }, { id: "recent", on: slot.hasRecent, at: slot.hasNotifs ? slot.width / 2 : 0 }]
                                      : [{ id: slot.modelData, on: true, at: 0 }]
                    Rectangle {
                        required property var modelData
                        visible: modelData.on
                        x: modelData.at - 7
                        y: -7
                        width: 26; height: 26; radius: 13
                        color: "#E5484D"
                        border.width: 2
                        border.color: Qt.rgba(0, 0, 0, 0.6)
                        Icon { anchors.centerIn: parent; name: "minus"; implicitSize: 14 }
                        // MouseArea, а не TapHandler: тот берёт захват пассивно, и нажатие проваливалось
                        // в плитку под минусом.
                        MouseArea { anchors.fill: parent; anchors.margins: -4; cursorShape: Qt.PointingHandCursor; onClicked: ev.hide(parent.modelData.id) }
                    }
                }
            }
        }
    }
    }

    // Долгое нажатие на Wi‑Fi или Bluetooth — список сетей или устройств поверх пульта.
    // ── Галерея виджетов (16 нояб.): «отдельное меню справа, гигантский список, который можно
    // крутить, и визуальный пример». Раньше спрятанное лежало строкой кнопок под пультом — и
    // выглядело как список текста, а не как выбор виджета.
    readonly property var galGroups: [
        { name: JD.tr("Плитки"), ids: ["t_mic", "t_voice", "t_sounds", "t_notifs", "t_coffee", "t_wifi", "t_bt", "t_server"] },
        { name: JD.tr("Виджеты"), ids: ["w_clock", "w_weather", "w_load", "w_note", "player", "ask", "sound", "event", "model"] },
        { name: JD.tr("Действия"), ids: ["a_shot", "a_emoji", "a_clip", "a_mixer", "a_load", "a_files", "a_kde", "a_update"] },
        { name: JD.tr("Остальное"), ids: ["notifs", "recent", "top_chat", "top_tools", "top_settings"] }]
    readonly property var galLook: ({
        t_mic: ["mic", "tile", JD.tr("Вкл")], t_voice: ["volume-2", "tile", JD.tr("Вкл")], t_sounds: ["audio-lines", "tile", JD.tr("Вкл")],
        t_notifs: ["bell", "tile", JD.tr("Вкл")], t_coffee: ["coffee", "tile", JD.tr("не засыпать")], t_wifi: ["wifi", "tile", JD.tr("сеть")],
        t_bt: ["bluetooth", "tile", JD.tr("Вкл")], t_server: ["moon", "tile", JD.tr("гасит экраны")],
        w_clock: ["timer", "clock", ""], w_weather: ["cloud-sun", "big", "+21°"], w_load: ["cpu", "bars", ""], w_note: ["pencil", "note", ""],
        player: ["music", "player", ""], ask: ["message-circle", "bar", JD.tr("Спросить…")], sound: ["volume-2", "slider", ""],
        event: ["calendar-clock", "event", "10:30"], model: ["brain", "bar", "Haiku"],
        a_shot: ["camera", "tile", JD.tr("область экрана")], a_emoji: ["smile", "tile", JD.tr("найти и вставить")],
        a_clip: ["clipboard", "tile", JD.tr("что копировали")], a_mixer: ["volume-2", "tile", JD.tr("звук программ")],
        a_load: ["cpu", "tile", JD.tr("что грузит машину")], a_files: ["folder-open", "tile", JD.tr("домашняя папка")],
        a_kde: ["sliders-horizontal", "tile", JD.tr("настройки KDE")], a_update: ["download", "tile", JD.tr("проверить сейчас")],
        notifs: ["bell-ring", "lines", ""], recent: ["list", "lines", ""],
        top_chat: ["message-circle", "dot", ""], top_tools: ["wand-sparkles", "dot", ""], top_settings: ["settings", "dot", ""] })
    function onBoard(id) {
        if (id === "notifs") return JD.island.show_notifications !== false
        if (id === "recent") return JD.island.menu_recent !== false
        return isShown(id)
    }
    Rectangle {
        id: gallery
        visible: ev.editing
        // Отдельная скруглённая карточка с отступом от края островка: прямоугольник во всю высоту
        // торчал углами из скругления, а нижние карточки резались его краем (16 нояб., скриншот).
        anchors { top: parent.top; bottom: parent.bottom; right: parent.right; margins: 8 }
        width: ev.galW - 8
        radius: 22
        color: JD.fill1
        clip: true
        ListView {
            id: galList
            anchors { fill: parent; margins: 12; bottomMargin: 0 }
            footer: Item { width: 1; height: 16 }
            clip: true
            spacing: 8
            boundsBehavior: Flickable.StopAtBounds
            model: ev.galGroups
            header: ColumnLayout {
                width: galList.width
                spacing: 2
                Label1 { text: JD.tr("Виджеты"); font.pixelSize: 17; font.weight: Font.Bold }
                Label2 { text: JD.tr("Нажмите, чтобы добавить на пульт или убрать."); font.pixelSize: 11; Layout.fillWidth: true; wrapMode: Text.WordWrap; Layout.bottomMargin: 6 }
            }
            delegate: ColumnLayout {
                id: grp
                required property var modelData
                width: galList.width
                spacing: 8
                SectionLabel { text: grp.modelData.name.toUpperCase(); Layout.topMargin: 6 }
                Flow {
                  Layout.fillWidth: true
                  spacing: 8
                  Repeater {
                    model: grp.modelData.ids
                    Pressable {
                        id: card
                        required property string modelData
                        readonly property var look: ev.galLook[modelData] || ["square", "tile", ""]
                        readonly property bool on: ev.onBoard(modelData)
                        readonly property string sz: ev.choices(modelData)[0] || (look[1] === "dot" ? "1x1" : "4x1")
                        readonly property int cw: ev.dims(sz)[0]
                        readonly property int ch: ev.dims(sz)[1]
                        // Широкие виджеты — во всю ширину, узкие по два в ряд: как они лягут на пульте.
                        width: card.cw >= 8 && card.look[1] !== "dot" ? grp.width : (grp.width - 8) / 2
                        height: pv.height + 46
                        radius: 16
                        color: hovered ? JD.fill2 : "transparent"
                        border.width: 1
                        border.color: on ? Qt.rgba(JD.accentBlue.r, JD.accentBlue.g, JD.accentBlue.b, 0.55) : JD.fill2
                        onClicked: card.on ? ev.hide(modelData) : ev.unhide(modelData)
                        // Пример: уменьшенный вид виджета в его собственной пропорции.
                        Rectangle {
                            id: pv
                            x: 10; y: 10
                            width: card.look[1] === "dot" ? 40 : card.width - 20
                            height: card.look[1] === "dot" ? 40 : 46 * card.ch + (card.ch - 1) * 8
                            radius: card.look[1] === "dot" ? 20 : 12
                            color: JD.fill2
                            opacity: card.on ? 1 : 0.85
                            RowLayout {
                                visible: ["tile", "bar", "slider", "event"].includes(card.look[1])
                                anchors { fill: parent; leftMargin: 8; rightMargin: 10 }
                                spacing: 8
                                // Тот же объёмный значок, что на пульте, в цвете своей плитки; нет полоски — прежний круг
                                Rectangle { visible: card.look[1] === "tile"; implicitWidth: 28; implicitHeight: 28; radius: 14
                                            color: gk.ok ? "transparent" : card.modelData.startsWith("a_") ? JD.fill1 : JD.accentBlue
                                            KubaiIcon { id: gk; anchors.centerIn: parent; width: 28; height: 28; name: card.look[0]; hovered: card.hovered
                                                        color: ev.blocks[card.modelData] && ev.blocks[card.modelData].tint !== undefined ? ev.blocks[card.modelData].tint : JD.accentBlue }
                                            Icon { anchors.centerIn: parent; name: card.look[0]; implicitSize: 14; visible: !gk.ok } }
                                Icon { visible: card.look[1] === "bar" || card.look[1] === "slider"; name: card.look[0]; implicitSize: 16 }
                                Rectangle { visible: card.look[1] === "event"; implicitWidth: 3; implicitHeight: 18; radius: 1.5; color: JD.accentOrange }
                                ColumnLayout {
                                    visible: card.look[1] !== "slider"
                                    spacing: 0; Layout.fillWidth: true
                                    Rectangle { visible: card.look[1] === "tile"; implicitWidth: 44; implicitHeight: 6; radius: 3; color: JD.text2; Layout.bottomMargin: 4 }
                                    Label2 { text: card.look[2]; font.pixelSize: 10; Layout.fillWidth: true; elide: Text.ElideRight
                                             color: card.look[1] === "event" ? JD.accentOrange : JD.text2 }
                                }
                                Rectangle { visible: card.look[1] === "slider"; Layout.fillWidth: true; implicitHeight: 5; radius: 2.5; color: JD.fill1
                                            Rectangle { width: parent.width * 0.6; height: parent.height; radius: 2.5; color: JD.text1 } }
                            }
                            Icon { visible: card.look[1] === "dot"; anchors.centerIn: parent; name: card.look[0]; implicitSize: 18 }
                            Text { visible: card.look[1] === "clock"; anchors.centerIn: parent; text: Qt.formatTime(evClock.date, "HH:mm")
                                   color: JD.text1; font.family: JD.fontFamily; font.pixelSize: 22; font.weight: Font.Bold; font.features: { "tnum": 1 } }
                            RowLayout {
                                visible: card.look[1] === "big"; anchors.centerIn: parent; spacing: 6
                                Icon { name: card.look[0]; implicitSize: 20 }
                                Text { text: card.look[2]; color: JD.text1; font.family: JD.fontFamily; font.pixelSize: 18; font.weight: Font.Bold }
                            }
                            Column {
                                visible: card.look[1] === "bars" || card.look[1] === "lines" || card.look[1] === "note"
                                anchors { fill: parent; margins: 10 }
                                spacing: card.look[1] === "bars" ? 9 : 6
                                Repeater {
                                    model: card.look[1] === "bars" ? [0.35, 0.62] : card.look[1] === "note" ? [0.9, 0.7, 0.8] : [0.8, 0.55]
                                    Rectangle {
                                        required property real modelData
                                        required property int index
                                        width: parent.width * (card.look[1] === "bars" ? 1 : modelData); height: card.look[1] === "bars" ? 5 : 6; radius: 3
                                        color: card.look[1] === "bars" ? JD.fill1 : JD.text3
                                        Rectangle { visible: card.look[1] === "bars"; width: parent.width * modelData; height: parent.height; radius: 3
                                                    color: index ? JD.accentPurple : JD.accentBlue }
                                    }
                                }
                            }
                            RowLayout {
                                visible: card.look[1] === "player"; anchors { fill: parent; margins: 10 } spacing: 10
                                Rectangle { implicitWidth: pv.height - 20; implicitHeight: implicitWidth; radius: 8; color: JD.accentPink
                                            Icon { anchors.centerIn: parent; name: "music"; implicitSize: 18 } }
                                ColumnLayout { spacing: 6; Layout.fillWidth: true
                                    Rectangle { Layout.fillWidth: true; implicitHeight: 6; radius: 3; color: JD.text3 }
                                    Rectangle { Layout.preferredWidth: parent.width * 0.6; implicitHeight: 6; radius: 3; color: JD.fill1 } }
                            }
                        }
                        RowLayout {
                            anchors { left: parent.left; right: parent.right; bottom: parent.bottom; leftMargin: 12; rightMargin: 10; bottomMargin: 8 }
                            spacing: 8
                            Label1 { text: ev.blockNames[card.modelData] || card.modelData; font.pixelSize: 12; Layout.fillWidth: true; elide: Text.ElideRight }
                            Rectangle {
                                implicitWidth: 22; implicitHeight: 22; radius: 11
                                color: card.on ? JD.accentBlue : JD.accentGreen
                                Behavior on color { enabled: JD.animOn; ColorAnimation { duration: JD.durBase } }
                                Icon { anchors.centerIn: parent; name: card.on ? "check" : "plus"; implicitSize: 13 }
                            }
                        }
                    }
                  }
                }
            }
        }
    }

    RadioSheet {
        id: radioSheet
        anchors.fill: parent
        z: 50
        Connections { target: ev; function onVisibleChanged() { if (!ev.visible) radioSheet.close() } }
    }
}
