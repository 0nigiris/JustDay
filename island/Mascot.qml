// Маскот: шар с деталями, нарисованный кодом целиком.
//
// Почему шар. Он садится в островок, как будто там и был, — островок сам пилюля, и круглое в нём не
// спорит ни с чем. Но главная причина другая: **шар с деталями рисуется кодом**, а значит каждая
// деталь живёт отдельно. Ухо дёргается само, хвост виляет сам, тело тянется и мнётся. Нарисуй мы
// зверя картинкой — и он навсегда остался бы с одной позой, потому что вторую надо рисовать руками,
// и третью, и сотую. Здесь же анимация стоит ровно столько, сколько строчек на неё написано.
//
// Что задаёт скин: цвета, форму ушей, хвост, усы, где глаза. Что задаёт движок: как всё это живёт.
// Поэтому «сделай лису» — это десять строк в TOML, а не сто нарисованных кадров.
//
// Правило, выученное дорого: всё, что шевелится, спрашивает `visible`. Анимация в скрытом виде
// шевелит сцену каждый кадр, окно считается изменившимся, и оболочка рисует шестьдесят кадров в
// секунду в пустоту — однажды это стоило трети процессорного ядра круглые сутки.
import QtQuick

Item {
    id: me

    property var skin: null
    property real size: 26
    property string mood: "idle"
    property string emote: ""
    property real voice: 0
    property real lookX: -99999
    property real lookY: -99999
    signal poked()

    readonly property bool ready: !!skin
    readonly property var body: (skin && skin.body) || ({})
    readonly property var ears: (skin && skin.ears) || ({})
    readonly property var tail: (skin && skin.tail) || ({})
    readonly property var face: (skin && skin.face) || ({})
    readonly property var whisk: (skin && skin.whiskers) || ({})
    readonly property var eyeCfg: (skin && skin.eyes) || ({})

    implicitWidth: size
    implicitHeight: size

    // ───────────── состояния ─────────────
    readonly property var states: ({
        "idle":      { eye: "pill",   badge: "",         breathes: true },
        "working":   { eye: "pill",   badge: "dots",     tint: JD.accentBlue },
        "thinking":  { eye: "pill",   badge: "dots",     tint: JD.accentPurple, look: [0.55, -0.55] },
        "searching": { eye: "pill",   badge: "dots",     tint: "#6366f1",       scans: true },
        "listening": { eye: "wide",   badge: "",         tint: JD.accentCyan,   perk: true },
        "talking":   { eye: "pill",   badge: "",         tint: JD.accentBlue,   mouth: true },
        "approval":  { eye: "wide",   badge: "bang",     tint: JD.accentOrange, bounces: true, perk: true },
        "question":  { eye: "pill",   badge: "question", tint: JD.accentCyan,   tilt: 0.17 },
        "error":     { eye: "flat",   badge: "dot",      tint: JD.accentRed },
        "finished":  { eye: "happy",  badge: "dot",      tint: JD.accentGreen,  wag: true },
        "ratelimit": { eye: "tired",  badge: "dot",      tint: "#fb923c" },
        "sleeping":  { eye: "closed", badge: "",         breathes: true, zz: true, droop: true },
        "dizzy":     { eye: "spiral", badge: "" }
    })
    readonly property var emotes: ({
        "love": "heart", "surprised": "dot", "proud": "star", "wink": "wink",
        "yawn": "tired", "happy": "happy", "annoyed": "line"
    })

    readonly property var now: states[dizzy ? "dizzy" : mood] || states["idle"]
    readonly property string eyeShape: emote !== "" && emotes[emote] ? emotes[emote] : now.eye
    readonly property color accent: now.tint || JD.accentBlue
    readonly property bool awake: visible && mood !== "sleeping"

    onEmoteChanged: if (emote !== "") emoteOff.restart()
    Timer { id: emoteOff; interval: 1500; onTriggered: me.emote = "" }

    // ───────────── взгляд ─────────────
    property real gazeX: 0
    property real gazeY: 0
    readonly property bool watching: lookX > -9000 && !now.look && !now.scans
    property real wanderX: 0
    property real wanderY: 0
    Timer {
        interval: 1500 + Math.random() * 2500
        running: me.awake && me.visible && !me.watching && !me.now.scans && JD.animOn
        repeat: true
        onTriggered: {
            interval = 1500 + Math.random() * 2500
            me.wanderX = (Math.random() - 0.5) * 1.3
            me.wanderY = (Math.random() - 0.5) * 0.9
        }
    }
    property real scan: 0
    SequentialAnimation on scan {
        running: me.now.scans === true && me.visible && JD.animOn
        loops: Animation.Infinite
        NumberAnimation { to: 1; duration: 700; easing.type: Easing.InOutSine }
        NumberAnimation { to: -1; duration: 1400; easing.type: Easing.InOutSine }
        NumberAnimation { to: 0; duration: 700; easing.type: Easing.InOutSine }
    }
    readonly property real wantX: now.scans ? scan : now.look ? now.look[0]
        : mood === "sleeping" ? 0 : (watching ? aim(lookX, false) : wanderX)
    readonly property real wantY: now.look ? now.look[1]
        : mood === "sleeping" ? 0.9 : (watching ? aim(lookY, true) : wanderY)
    function aim(at, vertical) {
        const c = me.mapToItem(null, me.width / 2, me.height / 2)
        const d = (vertical ? (at - c.y) : (at - c.x)) / (me.size * 4)
        return Math.max(-1, Math.min(1, d))
    }
    Behavior on gazeX { enabled: JD.animOn; NumberAnimation { duration: JD.durSlow; easing.type: JD.easeOut } }
    Behavior on gazeY { enabled: JD.animOn; NumberAnimation { duration: JD.durSlow; easing.type: JD.easeOut } }
    onWantXChanged: gazeX = wantX
    onWantYChanged: gazeY = wantY
    Component.onCompleted: { gazeX = wantX; gazeY = wantY }

    // ───────────── что умеет тело ─────────────
    //
    // Каждая живость — своя величина, и все они складываются. Так зверь может одновременно дышать,
    // дёргать ухом и вилять хвостом, не мешая сам себе: если бы это была одна анимация на всё,
    // каждая новая отменяла бы предыдущую, и получился бы не зверь, а переключатель поз.
    property real breath: 0        // дыхание
    property real squish: 0        // сминание от тычка
    property real stretch: 0       // потягивание
    property real hop: 0           // подскок
    property real lean: 0          // наклон головы
    property real shiver: 0        // дрожь
    property real earL: 0          // левое ухо: дёрг
    property real earR: 0          // правое ухо
    property real wag: 0           // хвост
    property real open: 1          // веки
    property bool dizzy: false

    SequentialAnimation on breath {
        running: me.awake && me.visible && JD.animOn
        loops: Animation.Infinite
        NumberAnimation { to: 1; duration: 2100; easing.type: Easing.InOutSine }
        NumberAnimation { to: 0; duration: 2400; easing.type: Easing.InOutSine }
    }

    // ───────────── безделье ─────────────
    //
    // Зверь, который в покое только дышит, — это заставка. Живым его делает то, что он сам по себе
    // что-то делает: дёрнул ухом, повилял хвостом, потянулся, склонил голову, вздрогнул. Выбор
    // наугад и с разным весом, чтобы не получилось расписание: предсказуемая живость — не живость.
    Timer {
        id: idleBeat
        interval: 2200 + Math.random() * 3600
        running: me.awake && me.visible && JD.animOn && me.mood === "idle" && !me.dizzy
        repeat: true
        onTriggered: {
            interval = 2200 + Math.random() * 3600
            me.doIdle()
        }
    }
    function doIdle() {
        const roll = Math.random()
        if (roll < 0.26) twitch(Math.random() < 0.5)
        else if (roll < 0.46) wagTail.restart()
        else if (roll < 0.60) stretchOut.restart()
        else if (roll < 0.72) tiltHead.restart()
        else if (roll < 0.80) shiverOff.restart()
        else if (roll < 0.88) { emote = "happy" }
        else if (roll < 0.94) { twitch(true); twitch(false) }
        else blinkTwice.restart()
    }
    function twitch(left) {
        if (left) twitchL.restart(); else twitchR.restart()
    }

    SequentialAnimation {
        id: twitchL
        NumberAnimation { target: me; property: "earL"; to: 1; duration: 90; easing.type: Easing.OutQuad }
        NumberAnimation { target: me; property: "earL"; to: 0; duration: 260; easing.type: Easing.OutBack }
    }
    SequentialAnimation {
        id: twitchR
        NumberAnimation { target: me; property: "earR"; to: 1; duration: 90; easing.type: Easing.OutQuad }
        NumberAnimation { target: me; property: "earR"; to: 0; duration: 260; easing.type: Easing.OutBack }
    }
    SequentialAnimation {
        id: wagTail
        loops: 3
        NumberAnimation { target: me; property: "wag"; to: 1; duration: 230; easing.type: Easing.InOutSine }
        NumberAnimation { target: me; property: "wag"; to: -1; duration: 300; easing.type: Easing.InOutSine }
        NumberAnimation { target: me; property: "wag"; to: 0; duration: 230; easing.type: Easing.InOutSine }
    }
    // Потягивание: сначала вытянулся вверх, потом осел. Обратный порядок читается как «испугался».
    SequentialAnimation {
        id: stretchOut
        NumberAnimation { target: me; property: "stretch"; to: 1; duration: 420; easing.type: Easing.OutCubic }
        PauseAnimation { duration: 260 }
        NumberAnimation { target: me; property: "stretch"; to: -0.35; duration: 320; easing.type: Easing.InOutSine }
        NumberAnimation { target: me; property: "stretch"; to: 0; duration: 420; easing.type: Easing.OutBack }
    }
    SequentialAnimation {
        id: tiltHead
        NumberAnimation { target: me; property: "lean"; to: Math.random() < 0.5 ? 1 : -1
                          duration: 320; easing.type: Easing.OutCubic }
        PauseAnimation { duration: 900 }
        NumberAnimation { target: me; property: "lean"; to: 0; duration: 420; easing.type: Easing.OutBack }
    }
    SequentialAnimation {
        id: shiverOff
        loops: 4
        NumberAnimation { target: me; property: "shiver"; to: 1; duration: 55 }
        NumberAnimation { target: me; property: "shiver"; to: -1; duration: 55 }
        NumberAnimation { target: me; property: "shiver"; to: 0; duration: 55 }
    }
    SequentialAnimation {
        id: blinkTwice
        loops: 2
        NumberAnimation { target: me; property: "open"; to: 0.06; duration: 70 }
        NumberAnimation { target: me; property: "open"; to: 1; duration: 110 }
    }

    // Обычное моргание — неровное: ровное мигание читается как индикатор, а не как глаза.
    Timer {
        interval: 2600 + Math.random() * 3800
        running: me.awake && me.visible && JD.animOn && me.eyeShape !== "closed"
        repeat: true
        onTriggered: { interval = 2600 + Math.random() * 3800; blink.restart() }
    }
    SequentialAnimation {
        id: blink
        NumberAnimation { target: me; property: "open"; to: 0.06; duration: 70; easing.type: Easing.InQuad }
        NumberAnimation { target: me; property: "open"; to: 1; duration: 110; easing.type: Easing.OutQuad }
    }

    // Хвост виляет сам, когда дело кончилось хорошо: радость у зверя видна хвостом.
    SequentialAnimation on wag {
        running: me.now.wag === true && me.visible && JD.animOn
        loops: Animation.Infinite
        NumberAnimation { to: 1; duration: 180; easing.type: Easing.InOutSine }
        NumberAnimation { to: -1; duration: 240; easing.type: Easing.InOutSine }
    }

    // ───────────── тычок ─────────────
    property int pokes: 0
    Timer { id: pokeWindow; interval: 1300; onTriggered: me.pokes = 0 }
    Timer { id: dizzyOff; interval: 2600; onTriggered: me.dizzy = false }
    SequentialAnimation {
        id: squeeze
        NumberAnimation { target: me; property: "squish"; to: 1; duration: 90; easing.type: Easing.OutQuad }
        NumberAnimation { target: me; property: "squish"; to: 0; duration: 420; easing.type: Easing.OutBack }
    }
    function poke() {
        squeeze.restart()
        twitch(Math.random() < 0.5)
        pokes++
        pokeWindow.restart()
        if (pokes >= 3) { dizzy = true; dizzyOff.restart(); pokes = 0 }
        else if (pokes === 2) emote = "annoyed"
        me.poked()
    }
    SequentialAnimation {
        id: jump
        loops: 2
        NumberAnimation { target: me; property: "hop"; to: -1; duration: 160; easing.type: Easing.OutQuad }
        NumberAnimation { target: me; property: "hop"; to: 0; duration: 220; easing.type: Easing.OutBounce }
    }
    onMoodChanged: if (mood === "finished") jump.restart()

    property real bob: 0
    SequentialAnimation on bob {
        running: me.now.bounces === true && me.visible && JD.animOn
        loops: Animation.Infinite
        NumberAnimation { to: -1; duration: 320; easing.type: Easing.OutQuad }
        NumberAnimation { to: 0; duration: 420; easing.type: Easing.OutBounce }
        PauseAnimation { duration: 260 }
    }

    // ───────────── зверь ─────────────
    Item {
        id: creature
        anchors.centerIn: parent
        width: me.size
        height: me.size
        y: (me.hop + me.bob * 0.5) * me.size * 0.22 - me.stretch * me.size * 0.06
        x: me.shiver * me.size * 0.03
        rotation: (me.dizzy ? wobble.value : 0) + me.lean * 11 + (me.now.tilt || 0) * 40

        QtObject { id: wobble; property real value: 0 }
        SequentialAnimation {
            running: me.dizzy && me.visible && JD.animOn
            loops: Animation.Infinite
            NumberAnimation { target: wobble; property: "value"; to: 9; duration: 180; easing.type: Easing.InOutSine }
            NumberAnimation { target: wobble; property: "value"; to: -9; duration: 360; easing.type: Easing.InOutSine }
            NumberAnimation { target: wobble; property: "value"; to: 0; duration: 180; easing.type: Easing.InOutSine }
        }

        // ───────────── хвост ─────────────
        //
        // Растёт из бока шара и вращается вокруг своего основания — так виляние выглядит движением
        // хвоста, а не ездой картинки. Пушистый у лисы и тонкий у кота — одна фигура разной толщины.
        Item {
            id: tailRoot
            visible: (me.tail.shape || "none") !== "none"
            z: -1
            readonly property bool bushy: (me.tail.shape || "thin") === "bushy"
            width: me.size * 0.72 * (me.tail.size === undefined ? 1 : me.tail.size)
            height: me.size * (bushy ? 0.32 : 0.14)
            x: creature.width * 0.58
            y: creature.height * (bushy ? 0.56 : 0.6)
            transformOrigin: Item.Left
            rotation: -30 + me.wag * 22 + (me.now.droop ? 26 : 0)
            Behavior on rotation { enabled: JD.animOn && me.now.droop !== undefined
                                   NumberAnimation { duration: 320 } }

            Rectangle {
                anchors.fill: parent
                radius: height / 2
                color: me.tail.fill || me.body.bottom || "#ff9a3c"
                // Кончик другого цвета — то, по чему лису узнают с одного взгляда.
                Rectangle {
                    visible: !!me.tail.tip
                    width: parent.width * 0.36
                    height: parent.height
                    radius: height / 2
                    x: parent.width - width
                    color: me.tail.tip || "#ffffff"
                }
            }
        }

        // ───────────── уши ─────────────
        //
        // Позади шара, чтобы росли из головы, а не лежали на ней. Дёргаются по отдельности: оба
        // разом — это испуг, а одно — обычное «что там?».
        Repeater {
            model: (me.ears.shape || "none") === "none" ? 0 : 2
            delegate: Item {
                required property int index
                // Не `left`: у Item есть собственное финальное свойство с таким именем — линия
                // привязки. Перекрыть его нельзя, и элемент просто не создаётся. Та же ловушка
                // однажды уже съела полосу лотка на слове `right`.
                readonly property bool onLeft: index === 0
                readonly property real spread: me.ears.spread === undefined ? 0.6 : me.ears.spread
                readonly property real earSize: me.size * (me.ears.size === undefined ? 0.36 : me.ears.size)
                z: -1
                width: earSize
                height: earSize
                x: creature.width / 2 + (onLeft ? -1 : 1) * creature.width * spread / 2 - earSize / 2
                y: creature.height * 0.1 - earSize * 0.42
                transformOrigin: Item.Bottom
                rotation: (onLeft ? -1 : 1) * ((me.ears.tilt === undefined ? 18 : me.ears.tilt)
                          + (onLeft ? me.earL : me.earR) * 26)
                         + (me.now.perk ? (onLeft ? 6 : -6) : 0)
                Behavior on rotation { enabled: JD.animOn && me.now.perk !== undefined
                                       NumberAnimation { duration: 180; easing.type: Easing.OutBack } }

                Canvas {
                    anchors.fill: parent
                    antialiasing: true
                    onPaint: {
                        const x = getContext("2d")
                        x.reset()
                        const w = width, h = height
                        const round = (me.ears.shape || "triangle") === "round"
                        x.fillStyle = me.ears.fill || me.body.bottom || "#ff9a3c"
                        x.beginPath()
                        if (round) {
                            x.arc(w / 2, h * 0.55, w * 0.44, 0, Math.PI * 2)
                        } else {
                            // Треугольник с мягкими углами: острое ухо на шаре выглядит осколком.
                            x.moveTo(w * 0.5, h * 0.06)
                            x.quadraticCurveTo(w * 0.95, h * 0.5, w * 0.86, h * 0.95)
                            x.quadraticCurveTo(w * 0.5, h * 0.8, w * 0.14, h * 0.95)
                            x.quadraticCurveTo(w * 0.05, h * 0.5, w * 0.5, h * 0.06)
                        }
                        x.fill()
                        if (me.ears.inner) {
                            x.fillStyle = me.ears.inner
                            x.beginPath()
                            if (round) x.arc(w / 2, h * 0.58, w * 0.26, 0, Math.PI * 2)
                            else {
                                x.moveTo(w * 0.5, h * 0.3)
                                x.quadraticCurveTo(w * 0.78, h * 0.6, w * 0.72, h * 0.84)
                                x.quadraticCurveTo(w * 0.5, h * 0.74, w * 0.28, h * 0.84)
                                x.quadraticCurveTo(w * 0.22, h * 0.6, w * 0.5, h * 0.3)
                            }
                            x.fill()
                        }
                    }
                }
            }
        }

        // ───────────── шар ─────────────
        Rectangle {
            id: ball
            anchors.centerIn: parent
            // Мнётся по ширине и высоте врозь — это и есть «мягкое». Одинаковый масштаб по обеим
            // осям читается как «отъехало», а не как «сжалось».
            width: me.size * (1 + me.breath * 0.025 + me.squish * 0.16 - me.stretch * 0.06)
            height: me.size * (1 + me.breath * 0.02 - me.squish * 0.2 + me.stretch * 0.1)
            radius: Math.min(width, height) / 2
            gradient: Gradient {
                GradientStop { position: 0; color: me.body.top || "#ffd0a0" }
                GradientStop { position: 1; color: me.body.bottom || "#ff9a3c" }
            }

            // Блик сверху: без него шар — плоское пятно.
            Rectangle {
                width: parent.width * 0.42
                height: parent.height * 0.28
                radius: height / 2
                x: parent.width * 0.17
                y: parent.height * 0.11
                color: Qt.rgba(1, 1, 1, 0.3)
            }

            // Мордочка: светлое пятно под глазами. Оно же держит нос и рот.
            Rectangle {
                id: muzzle
                visible: !!me.face.muzzle
                width: parent.width * 0.34
                height: parent.height * 0.22
                radius: height / 2
                anchors.horizontalCenter: parent.horizontalCenter
                y: parent.height * 0.62
                color: me.face.muzzle || "#ffffff"
                opacity: 0.9
            }

            // Щёки
            Repeater {
                model: me.face.blush ? 2 : 0
                delegate: Rectangle {
                    required property int index
                    width: ball.width * 0.16
                    height: width * 0.6
                    radius: height / 2
                    y: ball.height * 0.56
                    x: index === 0 ? ball.width * 0.07 : ball.width * 0.77
                    color: me.face.blush
                    opacity: 0.55
                }
            }

            // Усы — тонкими чёрточками, по три с каждой стороны, с лёгким разлётом.
            Repeater {
                // Усы появляются, только когда зверю есть где их носить. На двадцати двух точках
                // три волоска с каждой стороны — это шум поперёк лица, а не усы.
                model: me.size >= 34 ? (me.whisk.count || 0) * 2 : 0
                delegate: Rectangle {
                    required property int index
                    readonly property int side: index % 2 === 0 ? -1 : 1
                    readonly property int row: Math.floor(index / 2)
                    width: ball.width * 0.2
                    height: Math.max(1, me.size * 0.022)
                    radius: height / 2
                    color: me.whisk.fill || "#ffffff"
                    opacity: 0.85
                    transformOrigin: side < 0 ? Item.Right : Item.Left
                    x: side < 0 ? -width * 0.45 : ball.width - width * 0.55
                    y: ball.height * (0.6 + row * 0.07)
                    rotation: side * (10 - row * 9) + (side < 0 ? me.earL : me.earR) * side * 4
                }
            }

            // Нос
            Rectangle {
                visible: !!me.face.nose
                width: ball.width * 0.1
                height: width * 0.78
                radius: width / 2
                anchors.horizontalCenter: parent.horizontalCenter
                y: ball.height * 0.63
                color: me.face.nose || "#e2707f"
            }

            // Рот — только когда говорит: лицо без рта спокойно.
            Rectangle {
                anchors.horizontalCenter: parent.horizontalCenter
                y: ball.height * 0.74
                visible: me.now.mouth === true
                width: ball.width * (0.16 + me.voice * 0.1)
                height: ball.height * (0.04 + me.voice * 0.1)
                radius: height / 2
                color: me.eyeCfg.ink || "#2b1d14"
                Behavior on width { enabled: JD.animOn; NumberAnimation { duration: 70 } }
                Behavior on height { enabled: JD.animOn; NumberAnimation { duration: 70 } }
            }

            // ───────────── глаза ─────────────
            Item {
                x: ball.width * (me.eyeCfg.x === undefined ? 0.5 : me.eyeCfg.x) + me.gazeX * me.size * 0.05
                y: ball.height * (me.eyeCfg.y === undefined ? 0.44 : me.eyeCfg.y) + me.gazeY * me.size * 0.04
                width: 1
                height: 1
                readonly property real gap: ball.width * (me.eyeCfg.spacing === undefined ? 0.3 : me.eyeCfg.spacing) / 2
                readonly property real zoom: me.size * (me.eyeCfg.scale === undefined ? 0.5 : me.eyeCfg.scale)

                MascotEye {
                    side: -1; shape: me.eyeShape; open: me.open; size: parent.zoom
                    ink: me.eyeCfg.ink || "#2b1d14"
                    anchors.centerIn: parent; anchors.horizontalCenterOffset: -parent.gap
                }
                MascotEye {
                    side: 1; shape: me.eyeShape; open: me.open; size: parent.zoom
                    ink: me.eyeCfg.ink || "#2b1d14"
                    anchors.centerIn: parent; anchors.horizontalCenterOffset: parent.gap
                }
            }
        }
    }

    // ───────────── метка ─────────────
    Item {
        id: badge
        visible: !!me.now.badge
        width: me.size * 0.42
        height: me.size * 0.42
        x: me.width * 0.74
        y: -me.size * 0.04

        Rectangle {
            anchors.fill: parent
            radius: width / 2
            color: Qt.rgba(0, 0, 0, 0.62)
            border.width: 1
            border.color: Qt.rgba(1, 1, 1, 0.16)
        }
        Row {
            anchors.centerIn: parent
            spacing: me.size * 0.045
            visible: me.now.badge === "dots"
            Repeater {
                model: 3
                delegate: Rectangle {
                    required property int index
                    width: me.size * 0.07
                    height: width
                    radius: width / 2
                    color: me.accent
                    opacity: 0.35
                    SequentialAnimation on opacity {
                        running: badge.visible && me.now.badge === "dots" && me.visible && JD.animOn
                        loops: Animation.Infinite
                        PauseAnimation { duration: index * 170 }
                        NumberAnimation { to: 1; duration: 230 }
                        NumberAnimation { to: 0.35; duration: 230 }
                        PauseAnimation { duration: 510 - index * 170 }
                    }
                }
            }
        }
        Text {
            anchors.centerIn: parent
            visible: me.now.badge === "bang" || me.now.badge === "question"
            text: me.now.badge === "bang" ? "!" : "?"
            color: me.accent
            font.family: JD.fontFamily
            font.pixelSize: me.size * 0.3
            font.weight: Font.Black
        }
        Rectangle {
            anchors.centerIn: parent
            visible: me.now.badge === "dot"
            width: me.size * 0.13
            height: width
            radius: width / 2
            color: me.accent
        }
    }

    Repeater {
        model: 3
        delegate: Text {
            required property int index
            visible: me.now.zz === true && me.visible
            text: "z"
            color: Qt.rgba(1, 1, 1, 0.55)
            font.family: JD.fontFamily
            font.pixelSize: me.size * (0.22 + index * 0.06)
            x: me.width * 0.7 + index * me.size * 0.1
            property real rise: 0
            y: -me.size * 0.1 - rise * me.size * 0.5
            opacity: 1 - rise
            SequentialAnimation on rise {
                running: me.now.zz === true && me.visible && JD.animOn
                loops: Animation.Infinite
                PauseAnimation { duration: index * 600 }
                NumberAnimation { from: 0; to: 1; duration: 1800; easing.type: Easing.OutCubic }
                PauseAnimation { duration: 1800 - index * 600 }
            }
        }
    }

    HoverHandler { cursorShape: Qt.PointingHandCursor }
    TapHandler {
        gesturePolicy: TapHandler.ReleaseWithinBounds
        onTapped: me.poke()
    }
}
