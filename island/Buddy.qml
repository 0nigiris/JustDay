// Приятель: живое существо в островке.
//
// Зачем он вообще. Островок умеет говорить словами — «думаю», «слушаю», «нужно разрешение», — и
// слова эти надо прочитать. Существо сообщает то же самое раньше слов: по тому, куда оно смотрит,
// как дышит и в какой оно позе, состояние считывается боковым зрением, не отрываясь от работы. Это
// та же мысль, что у кошки в доке, только про ассистента, а не про процессор.
//
// Что здесь наше. Всё: форма, глаза, цвета, повадки. Идея «существо в вырезе экрана» чужой не
// бывает, а вот чужого персонажа брать нельзя — у тех, кто это придумал раньше, он свой и под своей
// лицензией. Поэтому здесь не чужой зверь в наших цветах, а своё существо: круглая галька с
// большими глазами и без рта. Рот появляется, только когда есть что им сказать.
//
// Правило, выученное дорого: всё, что шевелится, спрашивает `visible`. Анимация в скрытом виде
// шевелит сцену каждый кадр, окно считается изменившимся, и оболочка рисует шестьдесят кадров в
// секунду в пустоту. Один раз это уже стоило трети процессорного ядра круглые сутки.
import QtQuick

Item {
    id: me

    property real size: 26
    // Куда смотреть: точка в координатах сцены. Меньше -9000 — смотреть некуда, глаза гуляют сами.
    property real lookX: -99999
    property real lookY: -99999
    // Настроение приходит снаружи: островок знает про ассистента больше, чем существо.
    property string mood: "idle"     // idle | think | listen | talk | ask | done | sleep
    property real voice: 0           // громкость голоса, 0…1 — ею шевелится рот
    signal poked()

    implicitWidth: size
    implicitHeight: size

    readonly property bool awake: visible && mood !== "sleep"
    readonly property color skin: mood === "ask" ? JD.accentOrange
        : mood === "done" ? JD.accentGreen
        : mood === "listen" ? JD.accentCyan
        : mood === "talk" ? JD.accentBlue
        : JD.accentPurple

    // ───────────── куда смотрят глаза ─────────────
    //
    // На вейланде чужого курсора не видно: положение указателя клиенту дают, только пока он над его
    // окном. Окно островка — полоса во всю ширину экрана у верхнего края, и этого хватает: пока
    // человек рядом, глаза следят; как только ушёл — гуляют сами, а не замирают в последней точке.
    // Замерший взгляд выглядит сломанным, блуждающий — задумчивым.
    property real gazeX: 0
    property real gazeY: 0
    readonly property bool watching: lookX > -9000

    // Своя прогулка взгляда, когда следить не за кем.
    property real wanderX: 0
    property real wanderY: 0
    Timer {
        interval: 1500 + Math.random() * 2500
        running: me.awake && !me.watching && JD.animOn
        repeat: true
        onTriggered: {
            interval = 1500 + Math.random() * 2500
            me.wanderX = (Math.random() - 0.5) * 1.3
            me.wanderY = (Math.random() - 0.5) * 0.9
        }
    }

    // Думает — смотрит вверх и в сторону, как смотрят, когда вспоминают. Спит — вниз.
    readonly property real wantX: mood === "think" ? 0.75 : mood === "sleep" ? 0 : (watching ? clampLook(lookX, me.width) : wanderX)
    readonly property real wantY: mood === "think" ? -0.6 : mood === "sleep" ? 0.9 : (watching ? clampLook(lookY, me.height, true) : wanderY)
    function clampLook(at, span, vertical) {
        const c = me.mapToItem(null, me.width / 2, me.height / 2)
        const d = (vertical ? (at - c.y) : (at - c.x)) / (me.size * 4)
        return Math.max(-1, Math.min(1, d))
    }
    Behavior on gazeX { enabled: JD.animOn; NumberAnimation { duration: 320; easing.type: Easing.OutCubic } }
    Behavior on gazeY { enabled: JD.animOn; NumberAnimation { duration: 320; easing.type: Easing.OutCubic } }
    onWantXChanged: gazeX = wantX
    onWantYChanged: gazeY = wantY
    Component.onCompleted: { gazeX = wantX; gazeY = wantY }

    // ───────────── дыхание ─────────────
    property real breath: 0
    SequentialAnimation on breath {
        running: me.awake && JD.animOn && me.visible
        loops: Animation.Infinite
        NumberAnimation { to: 1; duration: 2100; easing.type: Easing.InOutSine }
        NumberAnimation { to: 0; duration: 2400; easing.type: Easing.InOutSine }
    }

    // ───────────── моргание ─────────────
    //
    // Не по таймеру ровно: живое моргает неровно, и равномерное мигание читается как индикатор, а
    // не как глаза.
    // 0 — открыт, 1 — закрыт. Спящий закрыт почти совсем: спящее существо с открытыми глазами —
    // это не спящее существо, а то же самое другого цвета, и в прошлой отрисовке «спит» и «спокоен»
    // отличались только оттенком.
    property real lid: 0
    readonly property real lidNow: Math.max(lid, mood === "sleep" ? 0.88 : 0)
    Timer {
        id: blinkWait
        interval: 2600 + Math.random() * 3800
        running: me.awake && me.visible && JD.animOn
        repeat: true
        onTriggered: { interval = 2600 + Math.random() * 3800; blink.restart() }
    }
    SequentialAnimation {
        id: blink
        NumberAnimation { target: me; property: "lid"; to: 1; duration: 70; easing.type: Easing.InQuad }
        NumberAnimation { target: me; property: "lid"; to: 0; duration: 110; easing.type: Easing.OutQuad }
    }

    // ───────────── тычок ─────────────
    //
    // Сжимается, а потом возвращается с перелётом: так ведёт себя мягкое. Три тычка подряд — и
    // существу дурно; это не шутка ради шутки, а ответ на то, что человек делает: если по чему-то
    // тычут трижды, оно обязано как-то на это отозваться.
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
        me.poked()
    }

    // Обрадовался: короткий подскок. Коротко — радость, которая длится, это уже не радость.
    property real hop: 0
    SequentialAnimation {
        id: jump
        loops: 2
        NumberAnimation { target: me; property: "hop"; to: -1; duration: 160; easing.type: Easing.OutQuad }
        NumberAnimation { target: me; property: "hop"; to: 0; duration: 220; easing.type: Easing.OutBounce }
    }
    onMoodChanged: if (mood === "done") jump.restart()

    // ───────────── тело ─────────────
    Item {
        id: body
        anchors.centerIn: parent
        width: me.size
        height: me.size
        y: me.hop * me.size * 0.22
        rotation: me.dizzy ? wobble.value : 0

        QtObject { id: wobble; property real value: 0 }
        SequentialAnimation {
            running: me.dizzy && JD.animOn
            loops: Animation.Infinite
            NumberAnimation { target: wobble; property: "value"; to: 9; duration: 180; easing.type: Easing.InOutSine }
            NumberAnimation { target: wobble; property: "value"; to: -9; duration: 360; easing.type: Easing.InOutSine }
            NumberAnimation { target: wobble; property: "value"; to: 0; duration: 180; easing.type: Easing.InOutSine }
        }

        // Галька: круглая, чуть приплюснутая дыханием и сильно — тычком.
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
            Behavior on gradient { enabled: false }

            // Блик сверху: без него галька выглядит плоским пятном, а не чем-то округлым.
            Rectangle {
                width: parent.width * 0.44
                height: parent.height * 0.3
                radius: height / 2
                x: parent.width * 0.16
                y: parent.height * 0.12
                color: Qt.rgba(1, 1, 1, 0.3)
            }

            // ───────────── глаза ─────────────
            //
            // Зрачок ходит внутри глаза по кругу, а не по квадрату: по квадрату взгляд «залипает» в
            // углах и перестаёт быть взглядом.
            Row {
                anchors.centerIn: parent
                anchors.verticalCenterOffset: parent.height * 0.04
                spacing: me.size * 0.16

                Repeater {
                    model: 2
                    delegate: Item {
                        required property int index
                        width: me.size * 0.3
                        height: me.size * 0.3 * (1 - me.lidNow * 0.94)
                        clip: true

                        Rectangle {
                            id: white
                            anchors.horizontalCenter: parent.horizontalCenter
                            y: -(me.size * 0.3 - parent.height) / 2
                            width: me.size * 0.3
                            height: me.size * 0.3
                            radius: width / 2
                            color: "#0d0d12"

                            // Зрачок — светлая точка на тёмном глазу: так читается даже в шесть
                            // пикселей, а тёмный зрачок на тёмном глазу не читается никак.
                            Rectangle {
                                width: parent.width * (me.mood === "listen" ? 0.5 : 0.42)
                                height: width
                                radius: width / 2
                                color: "#ffffff"
                                x: parent.width / 2 - width / 2 + me.gazeX * parent.width * 0.21
                                y: parent.height / 2 - height / 2 + me.gazeY * parent.height * 0.21
                                Behavior on width { enabled: JD.animOn; NumberAnimation { duration: 160 } }
                            }
                        }

                        // Дурно — глаза крестиками. Проще спирали и читается мгновенно.
                        Item {
                            anchors.fill: parent
                            visible: me.dizzy
                            Rectangle { anchors.centerIn: parent; width: parent.width * 0.9; height: 1.6
                                        radius: 1; color: "#0d0d12"; rotation: 45 }
                            Rectangle { anchors.centerIn: parent; width: parent.width * 0.9; height: 1.6
                                        radius: 1; color: "#0d0d12"; rotation: -45 }
                        }
                    }
                }
            }

            // Брови — только когда просят разрешения. Вопрос отличается от спокойствия не цветом,
            // а бровями: без них оранжевое лицо означает просто «оранжевый».
            Row {
                visible: me.mood === "ask"
                anchors.horizontalCenter: parent.horizontalCenter
                anchors.verticalCenter: parent.verticalCenter
                anchors.verticalCenterOffset: -parent.height * 0.26
                spacing: me.size * 0.16
                Repeater {
                    model: 2
                    delegate: Rectangle {
                        required property int index
                        width: me.size * 0.22
                        height: Math.max(1.4, me.size * 0.045)
                        radius: height / 2
                        color: "#0d0d12"
                        rotation: index === 0 ? -16 : 16
                    }
                }
            }

            // ───────────── рот ─────────────
            //
            // Рта нет почти всегда. Лицо без рта спокойно; рот появляется тогда, когда им есть что
            // сказать: говорит — шевелится по громкости, обрадовался — улыбается, просит
            // разрешения — ровная черта, потому что это вопрос, а не радость.
            Rectangle {
                id: mouth
                anchors.horizontalCenter: parent.horizontalCenter
                y: parent.height * 0.66
                visible: me.mood === "talk" || me.mood === "ask"
                // Говорит — рот шире, чем выше: круглый рот это «о», а не речь.
                width: me.mood === "talk" ? me.size * (0.26 + me.voice * 0.1) : me.size * 0.2
                height: me.mood === "talk" ? me.size * (0.05 + me.voice * 0.13) : me.size * 0.045
                radius: height / 2
                color: "#0d0d12"
                Behavior on width { enabled: JD.animOn; NumberAnimation { duration: 70 } }
                Behavior on height { enabled: JD.animOn; NumberAnimation { duration: 70 } }
            }

            // Улыбка — дуга, а не чёрточка. Прямая палка внизу лица читается как «ровно», а не как
            // «рад»; разница между ними ровно в кривизне, другого способа её показать нет.
            Canvas {
                visible: me.mood === "done"
                anchors.horizontalCenter: parent.horizontalCenter
                y: parent.height * 0.6
                width: me.size * 0.34
                height: me.size * 0.18
                onPaint: {
                    const ctx = getContext("2d")
                    ctx.reset()
                    ctx.strokeStyle = "#0d0d12"
                    ctx.lineWidth = Math.max(1.5, me.size * 0.055)
                    ctx.lineCap = "round"
                    ctx.beginPath()
                    ctx.arc(width / 2, 0, width / 2 - ctx.lineWidth / 2, 0.15 * Math.PI, 0.85 * Math.PI)
                    ctx.stroke()
                }
            }
        }
    }

    // Тычок принимает всё тело.
    HoverHandler { id: petting; cursorShape: Qt.PointingHandCursor }
    TapHandler {
        gesturePolicy: TapHandler.ReleaseWithinBounds
        onTapped: me.poke()
    }
}
