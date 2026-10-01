// Приятель: живое существо в островке.
//
// Зачем он вообще. Островок умеет говорить словами — «думаю», «слушаю», «нужно разрешение», — и
// слова эти надо прочитать. Существо сообщает то же самое раньше слов: по тому, куда оно смотрит,
// какой у него глаз и в какой он позе, состояние считывается боковым зрением, не отрываясь от
// работы. Та же мысль, что у кошки в доке, только про ассистента, а не про процессор.
//
// ───────────── откуда это взято ─────────────
//
// Словарь состояний и форм глаза перенесён из Coucou (Louis Raillé, MIT): одиннадцать состояний,
// тринадцать форм глаза, семь коротких выражений и повадки при них — качается, рыщет, дышит, спит,
// потеет. Это хорошо продуманная система, и выдумывать её заново значило бы выдумать хуже.
//
// Что НЕ взято и взято быть не может: сам персонаж, его имя, его значок и звуки — они у Coucou под
// отдельной лицензией и остаются его автору. Поэтому здесь своё существо: круглая галька нашего
// цвета, без рта, с нашим набором акцентов. Их же авторы прямо пишут, что форк приветствуется, если
// у него своё имя, свой значок, свой персонаж и свои звуки. Так и сделано.
//
// ───────────── правило, выученное дорого ─────────────
//
// Всё, что шевелится, спрашивает `visible`. Анимация в скрытом виде шевелит сцену каждый кадр, окно
// считается изменившимся, и оболочка рисует шестьдесят кадров в секунду в пустоту. Один раз это уже
// стоило трети процессорного ядра круглые сутки.
import QtQuick

Item {
    id: me

    property real size: 26
    // Куда смотреть: точка в координатах сцены. Меньше -9000 — смотреть некуда, глаза гуляют сами.
    property real lookX: -99999
    property real lookY: -99999
    // Состояние приходит снаружи: островок знает про ассистента больше, чем нарисованное лицо.
    property string mood: "idle"
    // Короткое выражение поверх состояния: любовь, удивление, гордость, подмигнуть, зевнуть,
    // радость, недовольство. Живёт полторы секунды и само снимается.
    property string emote: ""
    property real voice: 0           // громкость голоса, 0…1 — ею шевелится рот
    signal poked()

    implicitWidth: size
    implicitHeight: size

    // ───────────── таблица состояний ─────────────
    //
    // Одна таблица на всё: цвет, форма глаза, значок-метка и повадки. Разложить это по условиям в
    // десяти местах — верный способ получить состояние, которое красит тело, но забывает глаза.
    readonly property var states: ({
        "idle":      { tint: JD.text2,        eye: "pill",   badge: "",         breathes: true },
        "working":   { tint: JD.accentBlue,   eye: "pill",   badge: "dots" },
        "thinking":  { tint: JD.accentPurple, eye: "pill",   badge: "dots",     look: [0.55, -0.55] },
        "searching": { tint: "#6366f1",       eye: "pill",   badge: "dots",     scans: true },
        "listening": { tint: JD.accentCyan,   eye: "wide",   badge: "" },
        "talking":   { tint: JD.accentBlue,   eye: "pill",   badge: "",         mouth: true },
        "approval":  { tint: JD.accentOrange, eye: "wide",   badge: "bang",     bounces: true },
        "question":  { tint: JD.accentCyan,   eye: "pill",   badge: "question", tilt: 0.17 },
        "error":     { tint: JD.accentRed,    eye: "flat",   badge: "dot" },
        "finished":  { tint: JD.accentGreen,  eye: "happy",  badge: "dot" },
        "ratelimit": { tint: "#fb923c",       eye: "tired",  badge: "dot",      sweat: true },
        "sleeping":  { tint: "#94a3b8",       eye: "closed", badge: "",         breathes: true, zz: true },
        "dizzy":     { tint: JD.accentPink,   eye: "spiral", badge: "" }
    })
    readonly property var emotes: ({
        "love": "heart", "surprised": "dot", "proud": "star", "wink": "wink",
        "yawn": "tired", "happy": "happy", "annoyed": "line"
    })

    readonly property var now: states[dizzy ? "dizzy" : mood] || states["idle"]
    readonly property color skin: now.tint
    readonly property string eyeShape: emote !== "" && emotes[emote] ? emotes[emote] : now.eye
    readonly property bool awake: visible && mood !== "sleeping"

    // Выражение снимается само: оно короткое по смыслу, и оставлять его висеть — значит сделать из
    // него второе состояние, которого никто не просил.
    onEmoteChanged: if (emote !== "") emoteOff.restart()
    Timer { id: emoteOff; interval: 1500; onTriggered: me.emote = "" }

    // ───────────── куда смотрят глаза ─────────────
    //
    // На вейланде чужого курсора не видно: положение указателя клиенту дают, только пока он над его
    // окном. Окно островка — полоса во всю ширину экрана у верхнего края, и этого хватает: пока
    // человек рядом, глаза следят; как только ушёл — гуляют сами, а не замирают в последней точке.
    // Замерший взгляд выглядит сломанным, блуждающий — задумчивым.
    property real gazeX: 0
    property real gazeY: 0
    readonly property bool watching: lookX > -9000 && !now.look && !now.scans

    property real wanderX: 0
    property real wanderY: 0
    Timer {
        interval: 1500 + Math.random() * 2500
        running: me.awake && !me.watching && !me.now.scans && JD.animOn && me.visible
        repeat: true
        onTriggered: {
            interval = 1500 + Math.random() * 2500
            me.wanderX = (Math.random() - 0.5) * 1.3
            me.wanderY = (Math.random() - 0.5) * 0.9
        }
    }

    // Рыщет: глаза ходят из стороны в сторону ровно, как при поиске. Это единственное движение
    // взгляда, которое должно быть равномерным, — оно и значит «перебираю, а не думаю».
    property real scan: 0
    SequentialAnimation on scan {
        running: me.now.scans === true && me.visible && JD.animOn
        loops: Animation.Infinite
        NumberAnimation { to: 1; duration: 700; easing.type: Easing.InOutSine }
        NumberAnimation { to: -1; duration: 1400; easing.type: Easing.InOutSine }
        NumberAnimation { to: 0; duration: 700; easing.type: Easing.InOutSine }
    }

    readonly property real wantX: now.scans ? scan
        : now.look ? now.look[0]
        : mood === "sleeping" ? 0
        : (watching ? aim(lookX, false) : wanderX)
    readonly property real wantY: now.look ? now.look[1]
        : mood === "sleeping" ? 0.9
        : (watching ? aim(lookY, true) : wanderY)
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

    // ───────────── дыхание, качание, моргание ─────────────
    property real breath: 0
    SequentialAnimation on breath {
        running: me.awake && me.visible && JD.animOn
        loops: Animation.Infinite
        NumberAnimation { to: 1; duration: 2100; easing.type: Easing.InOutSine }
        NumberAnimation { to: 0; duration: 2400; easing.type: Easing.InOutSine }
    }

    // Качается — когда ждёт ответа от человека. Движение в сторону человека и есть просьба.
    property real bob: 0
    SequentialAnimation on bob {
        running: me.now.bounces === true && me.visible && JD.animOn
        loops: Animation.Infinite
        NumberAnimation { to: -1; duration: 320; easing.type: Easing.OutQuad }
        NumberAnimation { to: 0; duration: 420; easing.type: Easing.OutBounce }
        PauseAnimation { duration: 260 }
    }

    // Моргает неровно: ровное мигание читается как индикатор, а не как глаза.
    property real open: 1           // 1 — глаз открыт, 0 — закрыт
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

    // ───────────── тычок ─────────────
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
        y: (me.hop + me.bob * 0.5) * me.size * 0.22
        rotation: (me.dizzy ? wobble.value : 0) + (me.now.tilt || 0) * 40

        QtObject { id: wobble; property real value: 0 }
        SequentialAnimation {
            running: me.dizzy && me.visible && JD.animOn
            loops: Animation.Infinite
            NumberAnimation { target: wobble; property: "value"; to: 9; duration: 180; easing.type: Easing.InOutSine }
            NumberAnimation { target: wobble; property: "value"; to: -9; duration: 360; easing.type: Easing.InOutSine }
            NumberAnimation { target: wobble; property: "value"; to: 0; duration: 180; easing.type: Easing.InOutSine }
        }

        Rectangle {
            id: skin
            anchors.centerIn: parent
            width: me.size * (1 + me.breath * 0.025 + me.squish * 0.16)
            height: me.size * (1 + me.breath * 0.02 - me.squish * 0.2)
            radius: Math.min(width, height) / 2
            gradient: Gradient {
                GradientStop { position: 0; color: Qt.lighter(me.skin, 1.25) }
                GradientStop { position: 1; color: me.skin }
            }

            Rectangle {
                width: parent.width * 0.44
                height: parent.height * 0.3
                radius: height / 2
                x: parent.width * 0.16
                y: parent.height * 0.12
                color: Qt.rgba(1, 1, 1, 0.3)
            }

            // ───────────── глаза ─────────────
            // Глаза стоят по тем же долям, что и в перенесённой таблице: ширина 0,25 от тела,
            // высота 0,27, между центрами 0,37. Ряд с отступом эти доли не держит — холст шире
            // самого глаза, — поэтому каждый глаз ставится по своей середине.
            Item {
                anchors.centerIn: parent
                anchors.verticalCenterOffset: parent.height * 0.04 + me.gazeY * me.size * 0.07
                anchors.horizontalCenterOffset: me.gazeX * me.size * 0.09
                width: 1
                height: 1
                MascotEye {
                    side: -1; shape: me.eyeShape; open: me.open; size: me.size
                    anchors.centerIn: parent; anchors.horizontalCenterOffset: -me.size * 0.185
                }
                MascotEye {
                    side: 1; shape: me.eyeShape; open: me.open; size: me.size
                    anchors.centerIn: parent; anchors.horizontalCenterOffset: me.size * 0.185
                }
            }

            // ───────────── рот ─────────────
            //
            // Рта нет почти всегда. Лицо без рта спокойно; рот появляется тогда, когда им есть что
            // сказать: говорит — шевелится по громкости.
            Rectangle {
                anchors.horizontalCenter: parent.horizontalCenter
                y: parent.height * 0.68
                visible: me.now.mouth === true
                width: me.size * (0.26 + me.voice * 0.1)
                height: me.size * (0.05 + me.voice * 0.13)
                radius: height / 2
                color: "#0d0d12"
                Behavior on width { enabled: JD.animOn; NumberAnimation { duration: 70 } }
                Behavior on height { enabled: JD.animOn; NumberAnimation { duration: 70 } }
            }

            // Капля пота: не спешит и не капает — просто висит, пока неловко.
            Rectangle {
                visible: me.now.sweat === true
                width: me.size * 0.1
                height: me.size * 0.14
                radius: width / 2
                color: Qt.rgba(0.6, 0.85, 1, 0.9)
                x: parent.width * 0.78
                y: parent.height * 0.18 + me.breath * me.size * 0.04
            }
        }
    }

    // ───────────── метка ─────────────
    //
    // Маленький значок у виска: три точки — работает, восклицательный знак — ждёт ответа, вопрос —
    // спрашивает, точка — коротко о результате. Она сообщает **род** занятия, когда само занятие
    // по лицу уже понятно; без неё «работает» и «думает» выглядят одинаково.
    Item {
        id: badge
        visible: !!me.now.badge
        width: me.size * 0.42
        height: me.size * 0.42
        x: me.width * 0.72
        y: -me.size * 0.06

        Rectangle {
            anchors.fill: parent
            radius: width / 2
            color: Qt.rgba(0, 0, 0, 0.55)
            border.width: 1
            border.color: Qt.rgba(1, 1, 1, 0.14)
        }
        // Три точки бегут по очереди — это самое понятное «идёт работа» из всех придуманных.
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
                    color: me.skin
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
            color: me.skin
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
            color: me.skin
        }
    }

    // ───────────── сон ─────────────
    //
    // Буковки «z» поднимаются и тают. Их три, и они разной величины: одинаковые читались бы как
    // индикатор загрузки.
    Repeater {
        model: 3
        delegate: Text {
            required property int index
            visible: me.now.zz === true && me.visible
            text: "z"
            color: Qt.rgba(1, 1, 1, 0.55)
            font.family: JD.fontFamily
            font.pixelSize: me.size * (0.22 + index * 0.06)
            x: me.width * 0.68 + index * me.size * 0.1
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

    // ───────────── один глаз ─────────────
    //
    // Формы перенесены из Coucou один в один: та же геометрия, те же доли от размера. Холст
    // перерисовывается только когда форма действительно поменялась, а не каждый кадр: спираль и
    // звезда крутятся сами и просят перерисовку, пока крутятся, — остальные тринадцать стоят.
}
