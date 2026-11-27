import QtQuick
import QtQuick.Shapes

// Первое знакомство начинается с маскота: шарик падает сверху (или выныривает снизу), здоровается
// и сам становится островком с вопросником. Первое, что человек видит после установки, — это он,
// а не окно и не терминал.
//
// 27 нояб.: раньше шарик после падения секунды две оглядывался и моргал, и только потом пускал
// к вопросам — «не хочу заставлять человека ждать». Теперь вместо оглядывания он здоровается:
// растягивается в пилюлю «^^ Привет!», подпрыгивает и сразу растёт в вопросник; всё, что ещё
// нужно скачать, качается в это время в фоне (WelcomeView). До вопросов ~1,6 с вместо ~3,5.
// Превью: scripts/preview/greet.qml.
Item {
    id: intro
    // Капсула островка во время вступления стоит под шариком невидимой, того же размера и на том же
    // месте (shell.qml берёт width/height отсюда). В конце она проявляется в один кадр и растёт в
    // знакомство сама, шарик исчезает, а глаза остаются лицом карточки. Раньше островок вырастал
    // отдельно из нуля: на глаз это был монтажный стык, а не превращение. У полосы и выреза формы не
    // совпадают, там шарик щурится и гаснет.
    readonly property bool morph: JD.islandStyle === "island"
    visible: JD.introOn
    readonly property real size: 44
    readonly property real helloW: Math.max(150, hello.implicitWidth + 86)
    readonly property real restY: JD.atTop ? (JD.islandStyle === "island" ? JD.topMargin : 6) : parent.height - size - 8
    width: size; height: size
    x: (parent.width - width) / 2
    y: -size - 20
    property real eyeH: 9
    property real squash: 1
    property real hop: 0
    // 0 — круглые глаза, 1 — радостный прищур «^^»
    property real happy: 0
    // 0 — глаза посередине шарика, 1 — сдвинуты влево, справа «Привет!»
    property real side: 0
    Rectangle {
        id: ball
        anchors.fill: parent
        radius: height / 2
        color: JD.ink
        border.width: 1; border.color: Qt.rgba(1, 1, 1, 0.10)
        clip: true
        // Приплюснуть при ударе о край: так шарик кажется мягким и живым, а не нарисованной точкой.
        transform: [
            Scale { origin.x: ball.width / 2; origin.y: ball.height; yScale: intro.squash; xScale: 2 - intro.squash },
            Translate { y: -intro.hop }
        ]
        Row {
            anchors.verticalCenter: parent.verticalCenter
            anchors.verticalCenterOffset: -1
            x: (intro.size - width) / 2 + intro.side * (12 - (intro.size - width) / 2) + (1 - intro.side) * (ball.width - intro.size) / 2
            spacing: 9
            Eye { h: intro.eyeH; happy: intro.happy }
            Eye { h: intro.eyeH; happy: intro.happy }
        }
        Text {
            id: hello
            x: 54
            anchors.verticalCenter: parent.verticalCenter
            opacity: intro.side
            text: JD.tr("Привет!")
            font.family: JD.fontFamily; font.pixelSize: 15; font.weight: Font.DemiBold
            color: JD.text1
        }
    }
    // Глаз: круглый или радостный «^». Отдельным компонентом, а не Repeater: делегату qmllint не даёт
    // смотреть на intro.
    component Eye: Item {
        id: eye
        property real h: 9
        property real happy: 0
        width: 6; height: 9
        Rectangle {
            width: 6; height: eye.h; radius: 3; color: "white"
            anchors.centerIn: eye
            opacity: 1 - eye.happy
        }
        Shape {
            anchors.centerIn: eye
            width: 10; height: 6
            opacity: eye.happy
            preferredRendererType: Shape.CurveRenderer
            ShapePath {
                strokeColor: "white"; strokeWidth: 2.6; fillColor: "transparent"; capStyle: ShapePath.RoundCap
                startX: 1; startY: 5
                PathArc { x: 9; y: 5; radiusX: 4.4; radiusY: 4.4 }
            }
        }
    }
    component Ease: NumberAnimation { easing.type: Easing.OutCubic }
    SequentialAnimation {
        running: JD.introOn
        ScriptAction { script: { intro.width = intro.size; intro.height = intro.size; intro.y = JD.atTop ? -intro.size - 20 : intro.parent.height + 20; intro.eyeH = 9; intro.squash = 1; intro.hop = 0; intro.happy = 0; intro.side = 0; intro.opacity = 1 } }
        PauseAnimation { duration: 150 }
        // Падение с лёгким перелётом вместо трёх отскоков: отскоки ели почти секунду.
        Ease { target: intro; property: "y"; to: intro.restY; duration: 480; easing.type: Easing.OutBack; easing.overshoot: 1.6 }
        SequentialAnimation {
            Ease { target: intro; property: "squash"; to: 0.82; duration: 90; easing.type: Easing.OutQuad }
            Ease { target: intro; property: "squash"; to: 1; duration: 260; easing.type: Easing.OutBack; easing.overshoot: 2.5 }
        }
        // Поздороваться: пилюля «^^ Привет!» и два подскока.
        ParallelAnimation {
            Ease { target: intro; property: "width"; to: intro.helloW; duration: 380; easing.type: Easing.OutBack; easing.overshoot: 1.4 }
            Ease { target: intro; property: "side"; to: 1; duration: 320 }
            SequentialAnimation {
                PauseAnimation { duration: 140 }
                Ease { target: intro; property: "happy"; to: 1; duration: 140 }
            }
        }
        Ease { target: intro; property: "hop"; to: 5; duration: 110; easing.type: Easing.OutQuad }
        Ease { target: intro; property: "hop"; to: 0; duration: 150; easing.type: Easing.InQuad }
        Ease { target: intro; property: "hop"; to: 3; duration: 90; easing.type: Easing.OutQuad }
        Ease { target: intro; property: "hop"; to: 0; duration: 120; easing.type: Easing.InQuad }
        PauseAnimation { duration: 180 }
        // Глаза обратно посередине: там их подхватит лицо карточки (shell.qml, welcomeFace).
        ParallelAnimation {
            Ease { target: intro; property: "happy"; to: 0; duration: 160 }
            Ease { target: intro; property: "side"; to: 0; duration: 220; easing.type: Easing.InOutCubic }
            // Полоса и вырез не превращаются: шарик растягивается вширь, будто это и есть островок.
            Ease { target: intro; property: "width"; to: intro.morph ? intro.helloW : 220; duration: 220; easing.type: Easing.InOutCubic }
        }
        ScriptAction { script: JD.openTools("welcome") }
        // Капсула: глаза уже нарисованы в островке на том же месте, шарик просто исчезает.
        // Полоса и вырез: глаза щурятся и гаснут.
        ParallelAnimation {
            Ease { target: intro; property: "eyeH"; to: intro.morph ? 9 : 2; duration: intro.morph ? 0 : 180 }
            Ease { target: intro; property: "opacity"; to: 0; duration: intro.morph ? 0 : 240 }
        }
        // Пока карточка растёт, вступление ещё идёт: по нему островок берёт медленную пружину.
        PauseAnimation { duration: 450 }
        ScriptAction { script: JD.introOn = false }
    }
}
