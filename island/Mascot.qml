// Маскот из скина: нарисованное тело и наши глаза поверх него.
//
// Разделение труда здесь главное. Тело — настоящая картинка, и выглядит оно ровно настолько хорошо,
// насколько нарисовано: хоть рукой, хоть сгенерировано, хоть взято готовым. Глаза — код, и умеют
// всё: тринадцать форм, взгляд за курсором, неровное моргание, спираль, когда дурно.
//
// Почему не нарисовать и глаза. Потому что тогда каждое состояние и каждая анимация безделья — это
// новые кадры, и их надо нарисовать сотни. Никто этого не сделает, и персонаж навсегда останется с
// двумя позами. А так: одна картинка тела — и у зверя сразу есть всё поведение, какое мы напишем.
//
// Скин может пойти и дальше: дать состоянию свой файл (анимированный WebP или GIF), и тогда играется
// он. Так формат растёт от «одна картинка» до «нарисовано всё», и ни на одном шаге ничего не ломает.
import QtQuick

Item {
    id: me

    property var skin: null          // описание от демона; пусто — показывать нечего
    property real size: 26
    property string mood: "idle"
    property string emote: ""
    property real voice: 0
    property real lookX: -99999
    property real lookY: -99999
    signal poked()

    readonly property bool ready: !!skin && !!skin.body
    readonly property var eyes: (skin && skin.eyes) || ({})
    readonly property var motion: (skin && skin.motion) || ({})
    readonly property bool showEyes: eyes.show !== false

    implicitWidth: size
    implicitHeight: size

    // ───────────── состояния ─────────────
    //
    // Та же таблица, что у нарисованного кодом приятеля, — но от неё берутся только глаза и повадки:
    // цвет у зверя свой, нарисованный, и перекрашивать его в оранжевый ради «просит доступ» значило
    // бы испортить рисунок. Поэтому состояние показывается глазами, меткой и движением.
    readonly property var states: ({
        "idle":      { eye: "pill",   badge: "",         breathes: true },
        "working":   { eye: "pill",   badge: "dots",     tint: JD.accentBlue },
        "thinking":  { eye: "pill",   badge: "dots",     tint: JD.accentPurple, look: [0.55, -0.55] },
        "searching": { eye: "pill",   badge: "dots",     tint: "#6366f1",       scans: true },
        "listening": { eye: "wide",   badge: "",         tint: JD.accentCyan },
        "talking":   { eye: "pill",   badge: "",         tint: JD.accentBlue },
        "approval":  { eye: "wide",   badge: "bang",     tint: JD.accentOrange, bounces: true },
        "question":  { eye: "pill",   badge: "question", tint: JD.accentCyan,   tilt: 0.17 },
        "error":     { eye: "flat",   badge: "dot",      tint: JD.accentRed },
        "finished":  { eye: "happy",  badge: "dot",      tint: JD.accentGreen },
        "ratelimit": { eye: "tired",  badge: "dot",      tint: "#fb923c" },
        "sleeping":  { eye: "closed", badge: "",         breathes: true, zz: true },
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

    // Кадровая анимация, если скин её дал для этого состояния.
    readonly property string frames: {
        const byState = (skin && skin.states) || ({})
        return byState[mood] || ""
    }

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
    Behavior on gazeX { enabled: JD.animOn; NumberAnimation { duration: 320; easing.type: Easing.OutCubic } }
    Behavior on gazeY { enabled: JD.animOn; NumberAnimation { duration: 320; easing.type: Easing.OutCubic } }
    onWantXChanged: gazeX = wantX
    onWantYChanged: gazeY = wantY
    Component.onCompleted: { gazeX = wantX; gazeY = wantY }

    // ───────────── движение ─────────────
    property real breath: 0
    SequentialAnimation on breath {
        running: me.awake && me.visible && JD.animOn
        loops: Animation.Infinite
        NumberAnimation { to: 1; duration: 2100; easing.type: Easing.InOutSine }
        NumberAnimation { to: 0; duration: 2400; easing.type: Easing.InOutSine }
    }
    property real bob: 0
    SequentialAnimation on bob {
        running: me.now.bounces === true && me.visible && JD.animOn
        loops: Animation.Infinite
        NumberAnimation { to: -1; duration: 320; easing.type: Easing.OutQuad }
        NumberAnimation { to: 0; duration: 420; easing.type: Easing.OutBounce }
        PauseAnimation { duration: 260 }
    }
    property real open: 1
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

    property real squish: 0
    property bool dizzy: false
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
        pokes++
        pokeWindow.restart()
        if (pokes >= 3) { dizzy = true; dizzyOff.restart(); pokes = 0 }
        else if (pokes === 2) emote = "annoyed"
        me.poked()
    }
    property real hop: 0
    SequentialAnimation {
        id: jump
        loops: 2
        NumberAnimation { target: me; property: "hop"; to: -1; duration: 160; easing.type: Easing.OutQuad }
        NumberAnimation { target: me; property: "hop"; to: 0; duration: 220; easing.type: Easing.OutBounce }
    }
    onMoodChanged: if (mood === "finished") jump.restart()

    // ───────────── тело ─────────────
    Item {
        id: body
        anchors.centerIn: parent
        width: me.size
        height: me.size
        y: (me.hop + me.bob * 0.5) * me.size * 0.22 * (me.motion.bob === undefined ? 1 : me.motion.bob)
        rotation: (me.dizzy ? wobble.value : 0)
                  + (me.now.tilt || 0) * 40 * (me.motion.tilt === undefined ? 1 : me.motion.tilt)
        // Дышит и мнётся само тело, а не только картинка: иначе глаза живут отдельно от зверя.
        scale: 1 + me.breath * 0.025 * (me.motion.breathe === undefined ? 1 : me.motion.breathe)

        QtObject { id: wobble; property real value: 0 }
        SequentialAnimation {
            running: me.dizzy && me.visible && JD.animOn
            loops: Animation.Infinite
            NumberAnimation { target: wobble; property: "value"; to: 9; duration: 180; easing.type: Easing.InOutSine }
            NumberAnimation { target: wobble; property: "value"; to: -9; duration: 360; easing.type: Easing.InOutSine }
            NumberAnimation { target: wobble; property: "value"; to: 0; duration: 180; easing.type: Easing.InOutSine }
        }

        Item {
            id: art
            anchors.centerIn: parent
            // Сминается по ширине и высоте врозь — это и есть «мягкое». Одинаковый масштаб по обеим
            // осям читается как «отъехало», а не как «сжалось».
            width: me.size * (1 + me.squish * 0.16 * (me.motion.squish === undefined ? 1 : me.motion.squish))
            height: me.size * (1 - me.squish * 0.2 * (me.motion.squish === undefined ? 1 : me.motion.squish))

            Image {
                id: still
                anchors.fill: parent
                visible: me.frames === ""
                source: me.ready ? "file://" + me.skin.body : ""
                // Растр просят с запасом: маскот вырастает, когда остров раскрывается, и
                // нарисованный по своему размеру он там расплывается.
                sourceSize: Qt.size(me.size * 3, me.size * 3)
                fillMode: Image.PreserveAspectFit
                mipmap: true
                smooth: true
                asynchronous: true
            }
            AnimatedImage {
                anchors.fill: parent
                visible: me.frames !== ""
                source: me.frames !== "" ? "file://" + me.frames : ""
                // Кадры крутятся, только пока их видно: невидимая анимация шевелит сцену каждый
                // кадр, и оболочка рисует шестьдесят кадров в секунду в пустоту.
                playing: visible && me.visible && JD.animOn
                paused: !playing
                fillMode: Image.PreserveAspectFit
                cache: false
                smooth: true
            }

            // ───────────── глаза поверх тела ─────────────
            Item {
                visible: me.showEyes
                x: parent.width * (me.eyes.x === undefined ? 0.5 : me.eyes.x) + me.gazeX * me.size * 0.05
                y: parent.height * (me.eyes.y === undefined ? 0.42 : me.eyes.y) + me.gazeY * me.size * 0.04
                width: 1
                height: 1
                readonly property real gap: parent.width * (me.eyes.spacing === undefined ? 0.2 : me.eyes.spacing) / 2
                readonly property real zoom: me.size * (me.eyes.scale === undefined ? 1 : me.eyes.scale)

                MascotEye {
                    side: -1
                    shape: me.eyeShape
                    open: me.open
                    size: parent.zoom
                    ink: me.eyes.ink || "#1a1412"
                    anchors.centerIn: parent
                    anchors.horizontalCenterOffset: -parent.gap
                }
                MascotEye {
                    side: 1
                    shape: me.eyeShape
                    open: me.open
                    size: parent.zoom
                    ink: me.eyes.ink || "#1a1412"
                    anchors.centerIn: parent
                    anchors.horizontalCenterOffset: parent.gap
                }
            }
        }
    }

    // ───────────── метка ─────────────
    //
    // У зверя она важнее, чем у шарика: цвет тела нарисован и состояние им не показать, поэтому род
    // занятия сообщает только метка. Три точки — работает, «!» — ждёт ответа, «?» — спрашивает.
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

    // Спит — буковки «z».
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
