// Превью первого запуска, вариант 2 (27 нояб.): ждать установки нельзя. Шарик падает, глазки
// здороваются («Привет!», радостный прищур, подскок), и островок сразу вырастает в вопросник.
// Голос и речь в это время качаются в фоне — это видно в углу карточки, но не мешает.
// Кадр — функция времени t, как в install.qml.
import QtQuick
import QtQuick.Shapes

Item {
    id: root
    width: 1920; height: 1080
    property real t: 0
    readonly property real tt: t - 0.9          // своё время островка: до него — щелчок по значку

    readonly property color ink: "#000000"
    readonly property color blue: "#0060df"
    readonly property color text1: "#f5f5f7"
    readonly property color text2: Qt.rgba(235/255, 235/255, 245/255, 0.62)
    readonly property string font: "Inter"

    function c01(x) { return Math.max(0, Math.min(1, x)) }
    function seg(a, b) { return c01((tt - a) / (b - a)) }
    function segT(a, b) { return c01((t - a) / (b - a)) }
    function lerp(a, b, k) { return a + (b - a) * k }
    function oCubic(x) { return 1 - Math.pow(1 - x, 3) }
    function ioCubic(x) { return x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2 }
    function oBack(x, s) { s = s === undefined ? 1.70158 : s; const c3 = s + 1; return 1 + c3 * Math.pow(x - 1, 3) + s * Math.pow(x - 1, 2) }
    function ioBack(x, s) { const c2 = s * 1.525; return x < 0.5 ? (Math.pow(2 * x, 2) * ((c2 + 1) * 2 * x - c2)) / 2
                                                      : (Math.pow(2 * x - 2, 2) * ((c2 + 1) * (x * 2 - 2) + c2) + 2) / 2 }

    // ── рабочий стол ──
    Image { anchors.fill: parent; source: "file:///usr/share/wallpapers/Next/contents/images/5120x2880.png"; fillMode: Image.PreserveAspectCrop; sourceSize: Qt.size(1920, 1080) }
    Rectangle { anchors.fill: parent; color: Qt.rgba(0, 0, 0, 0.18) }

    // Значок установщика на столе и двойной щелчок по нему.
    Item {
        x: 400; y: 250; width: 96; height: 110
        readonly property real hit: segT(0.55, 0.62) - segT(0.85, 1.2)
        Rectangle { anchors.fill: parent; radius: 6; color: Qt.rgba(1, 1, 1, 0.16 * parent.hit) }
        Image { x: 16; y: 8; width: 64; height: 64; source: "justday-icon.svg"; sourceSize: Qt.size(128, 128)
                scale: 1 - 0.06 * (root.segT(0.55, 0.6) - root.segT(0.62, 0.75)) }
        Text { anchors.horizontalCenter: parent.horizontalCenter; y: 78; text: "JustDay.exe"; color: "white"; font.family: root.font; font.pixelSize: 12
               style: Text.Raised; styleColor: Qt.rgba(0, 0, 0, 0.5) }
    }
    // Курсор: подлетает к значку, щёлкает дважды и уходит в сторону, чтобы не заслонять островок.
    Shape {
        readonly property real k: oCubic(segT(0.0, 0.5))
        readonly property real away: ioCubic(segT(1.1, 1.8))
        x: lerp(lerp(1300, 446, k), 760, away); y: lerp(lerp(660, 290, k), 600, away)
        scale: 1 - 0.12 * (segT(0.55, 0.58) - segT(0.6, 0.63) + segT(0.66, 0.69) - segT(0.71, 0.74))
        transformOrigin: Item.TopLeft
        ShapePath {
            fillColor: "white"; strokeColor: "black"; strokeWidth: 1.2
            startX: 0; startY: 0
            PathLine { x: 0; y: 22 } PathLine { x: 6; y: 16.5 } PathLine { x: 10; y: 25 } PathLine { x: 13.5; y: 23.5 }
            PathLine { x: 9.8; y: 15.2 } PathLine { x: 17; y: 15.2 } PathLine { x: 0; y: 0 }
        }
    }

    // ── островок ──
    readonly property real drop: oBack(seg(0.0, 0.5), 1.8)
    readonly property real squash: Math.sin(Math.PI * seg(0.42, 0.62))
    readonly property real hello: oBack(seg(0.55, 0.95), 1.4) * (1 - ioCubic(seg(1.5, 1.75)))
    readonly property real happy: ioCubic(seg(0.72, 0.86)) * (1 - ioCubic(seg(1.3, 1.45)))
    readonly property real hop: 5 * (Math.sin(Math.PI * seg(0.92, 1.1)) + 0.6 * Math.sin(Math.PI * seg(1.1, 1.24)))
    readonly property real grow: ioBack(seg(1.55, 2.27), 0.7)
    readonly property real pillW: lerp(44, 176, hello)

    Rectangle {
        id: body
        visible: root.tt > 0
        width: root.tt < 1.55 ? root.pillW + 8 * root.squash : root.lerp(root.pillW, 1000, root.grow)
        height: root.tt < 1.55 ? 44 - 7 * root.squash : root.lerp(44, 560, root.grow)
        x: (root.width - width) / 2
        y: root.lerp(-60, 12, root.drop) + 7 * root.squash - root.hop
        radius: root.tt < 1.55 ? height / 2 : Math.min(height / 2, root.lerp(22, 30, root.grow))
        color: root.ink
        border.width: 1; border.color: Qt.rgba(1, 1, 1, 0.08)
        clip: true

        Text {
            x: 62; anchors.verticalCenter: parent.verticalCenter
            opacity: root.c01(root.hello * 1.6 - 0.6) * (1 - root.seg(1.4, 1.55))
            transform: Translate { x: 10 * (1 - root.hello) }
            text: "Привет!"; color: root.text1; font.family: root.font; font.pixelSize: 15; font.weight: Font.DemiBold
        }

        // Глаза: слева от «Привет!», потом в середину верха карточки.
        Item {
            id: face
            readonly property real toTop: root.ioCubic(root.seg(1.5, 2.1))
            readonly property real blink: Math.sin(Math.PI * root.seg(3.0, 3.16))
            readonly property real lookX: root.lerp(0, -7, root.ioCubic(root.seg(2.9, 3.15)))
            readonly property real lookY: root.lerp(0, 4, root.ioCubic(root.seg(2.9, 3.15)))
            readonly property real nod: [3.4, 3.57, 3.74].reduce((a, s) => a + 2.5 * Math.sin(Math.PI * root.seg(s, s + 0.16)), 0)
            x: root.lerp(root.lerp(body.width / 2, 34, root.hello), body.width / 2, toTop) + lookX
            y: (root.tt < 1.55 ? body.height / 2 : 22) - 1 + lookY + nod
            Repeater {
                model: 2
                Item {
                    required property int index
                    x: (index ? 1 : -1) * 7.5
                    // обычный глаз
                    Rectangle {
                        width: 6; height: 9 * (1 - 0.88 * face.blink); radius: 3; x: -3; y: -height / 2
                        color: "white"; opacity: 1 - root.happy
                    }
                    // радостный прищур «^»
                    Shape {
                        opacity: root.happy
                        y: 2 - 2 * root.happy
                        preferredRendererType: Shape.CurveRenderer
                        ShapePath {
                            strokeColor: "white"; strokeWidth: 2.6; fillColor: "transparent"; capStyle: ShapePath.RoundCap
                            startX: -4; startY: 1.5
                            PathArc { x: 4; y: 1.5; radiusX: 4.4; radiusY: 4.4 }
                        }
                    }
                }
            }
        }

        // Докачка в фоне: тихий значок в углу карточки, вопросник от неё не ждёт.
        Row {
            anchors.right: parent.right; anchors.rightMargin: 40; y: 34
            spacing: 8
            opacity: root.oCubic(root.seg(2.6, 3.0))
            Item {
                width: 14; height: 14; anchors.verticalCenter: parent.verticalCenter
                Rectangle { anchors.fill: parent; radius: 7; color: "transparent"; border.width: 2; border.color: Qt.rgba(1, 1, 1, 0.12) }
                Shape {
                    anchors.fill: parent
                    rotation: root.tt * 300
                    preferredRendererType: Shape.CurveRenderer
                    ShapePath {
                        strokeColor: root.blue; strokeWidth: 2; fillColor: "transparent"; capStyle: ShapePath.RoundCap
                        PathAngleArc { centerX: 7; centerY: 7; radiusX: 6; radiusY: 6; startAngle: 0; sweepAngle: 100 }
                    }
                }
            }
            Text { text: "Голос и речь качаются в фоне"; color: root.text2; font.family: root.font; font.pixelSize: 12; anchors.verticalCenter: parent.verticalCenter }
        }

        Column {
            x: 40; y: 120; width: 920; spacing: 14
            Repeater {
                model: 4
                Item {
                    required property int index
                    readonly property real k: root.oCubic(root.seg(2.05 + index * 0.08, 2.55 + index * 0.08))
                    width: 920; height: [34, 20, 56, 56][index]
                    opacity: k
                    transform: Translate { y: 18 * (1 - k) }
                    Text { visible: index === 0; text: "Давайте познакомимся"; color: root.text1; font.family: root.font; font.pixelSize: 28; font.weight: Font.DemiBold }
                    Text { visible: index === 1; text: "Это займёт минуту. Всё можно поменять потом в настройках."; color: root.text2; font.family: root.font; font.pixelSize: 15 }
                    Rectangle {
                        visible: index >= 2; anchors.fill: parent; radius: 14; color: Qt.rgba(1, 1, 1, 0.08)
                        border.width: 1; border.color: index === 2 && root.tt > 2.95 ? root.blue : "transparent"
                        Text { x: 16; y: 8; text: index === 2 ? "Как вас зовут" : "Как звать ассистента"; color: root.text2; font.family: root.font; font.pixelSize: 11 }
                        Text { x: 16; y: 25; font.family: root.font; font.pixelSize: 17; color: root.text1
                               text: index === 3 ? "JustDay" : (root.tt > 3.74 ? "Аня" : root.tt > 3.57 ? "Ан" : root.tt > 3.4 ? "А" : "") }
                    }
                }
            }
        }
        Item {
            id: navRow
            x: 40; y: 480; width: 920; height: 44
            readonly property real k: root.oCubic(root.seg(2.4, 2.9))
            opacity: k
            transform: Translate { y: 14 * (1 - navRow.k) }
            Row { anchors.verticalCenter: parent.verticalCenter; spacing: 6
                Repeater { model: 5; Rectangle { required property int index; width: index ? 7 : 20; height: 7; radius: 3.5; color: index ? Qt.rgba(1, 1, 1, 0.14) : root.blue } } }
            Rectangle { anchors.right: parent.right; width: 124; height: 42; radius: 21; color: root.blue
                Text { anchors.centerIn: parent; text: "Дальше"; color: "white"; font.family: root.font; font.pixelSize: 15; font.weight: Font.DemiBold } }
        }
    }
}
