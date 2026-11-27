// Превью установки на Windows (27 нояб.): кадр — функция времени t, поэтому видео выходит ровным
// 60 к/с при любой скорости рендера. Здесь показывается задумка ДО кода установщика: двойной
// щелчок по exe → капля падает сверху → растягивается в капсулу с ходом установки → сжимается в
// шарик маскота → вырастает в знакомство. Ни одного окна, кроме самого островка.
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

    // ── островок: одно тело от капли до карточки ──
    // Ход установки: быстрый старт, раздумье на ярлыках, ровный финиш — ровная полоска врёт.
    readonly property real p: 0.62 * oCubic(seg(0.75, 2.2)) + 0.38 * ioCubic(seg(2.45, 3.75))
    readonly property real drop: oBack(seg(0.0, 0.55), 2.2)
    readonly property real squash: Math.sin(Math.PI * seg(0.5, 0.72))
    readonly property real stretch: oBack(seg(0.62, 1.2), 1.15)
    readonly property real shrink: ioBack(seg(3.95, 4.6), 1.1)
    readonly property real grow: ioBack(seg(6.05, 6.77), 0.7)
    readonly property real breathe: (seg(1.2, 3.9) > 0 && seg(1.2, 3.9) < 1) ? Math.sin((tt - 1.2) * 2.6) * 1.5 : 0

    Rectangle {
        id: body
        visible: root.tt > 0
        readonly property real w: root.tt < 3.95 ? root.lerp(16 + 6 * root.squash, 300, root.stretch) + root.breathe
                                 : root.tt < 6.05 ? root.lerp(300, 44, root.shrink) : root.lerp(44, 1000, root.grow)
        readonly property real h: root.tt < 3.95 ? root.lerp(16 - 5 * root.squash, 42, root.stretch)
                                 : root.tt < 6.05 ? root.lerp(42, 44, root.shrink) : root.lerp(44, 560, root.grow)
        width: Math.max(4, w); height: Math.max(4, h)
        x: (root.width - width) / 2
        y: root.lerp(-40, 12, root.drop)
        radius: root.tt < 6.05 ? height / 2 : root.lerp(22, 30, root.grow)
        color: root.ink
        border.width: 1; border.color: Qt.rgba(1, 1, 1, 0.08)
        clip: true

        // ход установки: мягкая заливка с ярким краем
        Rectangle {
            readonly property real o: root.seg(0.9, 1.2) * (1 - root.seg(3.8, 4.0))
            opacity: o
            width: Math.max(body.height, body.width * root.p); height: body.height; radius: height / 2
            color: Qt.rgba(1, 1, 1, 0.075)
            Rectangle { anchors.right: parent.right; width: 28; height: parent.height; radius: height / 2
                gradient: Gradient { orientation: Gradient.Horizontal
                    GradientStop { position: 0; color: Qt.rgba(1, 1, 1, 0) }
                    GradientStop { position: 1; color: Qt.rgba(1, 1, 1, 0.13) } } }
        }

        // подпись этапа: сменяется прокруткой вверх
        Item {
            x: 36; width: 190; height: body.height
            opacity: root.seg(0.95, 1.25) * (1 - root.seg(3.75, 3.95))
            clip: true
            Repeater {
                model: [["Распаковываю", 0.0], ["Ярлык в «Пуске»", 0.55], ["Почти готово", 0.86]]
                Text {
                    required property var modelData
                    required property int index
                    readonly property var next: [0.55, 0.86, 9][index]
                    readonly property real inK: root.oCubic(root.c01((root.p - modelData[1]) / 0.06))
                    readonly property real outK: root.oCubic(root.c01((root.p - next) / 0.06))
                    y: (body.height - height) / 2 + 16 * (1 - inK) - 16 * outK
                    opacity: index === 0 ? 1 - outK : inK - outK
                    text: modelData[0]; color: root.text1; font.family: root.font; font.pixelSize: 13; font.weight: Font.DemiBold
                }
            }
        }
        Text {
            anchors.right: parent.right; anchors.rightMargin: 18; anchors.verticalCenter: parent.verticalCenter
            opacity: root.seg(1.0, 1.3) * (1 - root.seg(3.75, 3.95))
            text: Math.round(root.p * 100) + "%"; color: root.text2
            font.family: root.font; font.pixelSize: 13; font.features: { "tnum": 1 }
        }

        // Синяя точка — та же, что над J в знаке. В конце она съезжает в середину, белеет и делится
        // на два глаза: установщик не закрывается, он и есть маскот.
        Item {
            id: face
            readonly property real toMid: root.ioCubic(root.seg(3.7, 4.45))
            readonly property real split: root.oBack(root.seg(4.3, 4.75), 2.0)
            readonly property real lookX: root.tt < 6.05 ? -6 * (root.ioCubic(root.seg(4.8, 5.05)) - root.ioCubic(root.seg(5.25, 5.5)))
                                                       + 6 * (root.ioCubic(root.seg(5.25, 5.5)) - root.ioCubic(root.seg(5.75, 5.95)))
                                         : root.lerp(0, -7, root.ioCubic(root.seg(7.35, 7.6)))
            readonly property real lookY: root.lerp(0, 4, root.ioCubic(root.seg(7.35, 7.6)))
            readonly property real nod: [7.85, 8.02, 8.19].reduce((a, s) => a + 2.5 * Math.sin(Math.PI * root.seg(s, s + 0.16)), 0)
            readonly property real blink: Math.sin(Math.PI * root.seg(5.98, 6.16))
            readonly property real pulse: root.tt > 1.0 && root.tt < 3.7 ? 1 + 0.18 * Math.max(0, Math.sin((root.tt - 1.0) * 5)) : 1
            x: root.lerp(20, body.width / 2, toMid) + lookX
            y: (root.tt < 6.05 ? body.height / 2 : 22) - 1 + lookY + nod
            Repeater {
                model: 2
                Rectangle {
                    required property int index
                    readonly property real eh: root.lerp(8, 9, face.split) * (1 - 0.88 * face.blink)
                    width: root.lerp(8, 6, face.split) * face.pulse; height: eh * face.pulse
                    radius: Math.min(width, height) / 2
                    x: -width / 2 + (index ? 1 : -1) * 7.5 * face.split
                    y: -height / 2
                    color: Qt.tint(root.blue, Qt.rgba(1, 1, 1, face.split))
                }
            }
        }

        // знакомство: строки всплывают по очереди, когда карточка почти выросла
        Column {
            x: 40; y: 120; width: 920; spacing: 14
            Repeater {
                model: 4
                Item {
                    required property int index
                    readonly property real k: root.oCubic(root.seg(6.55 + index * 0.08, 7.05 + index * 0.08))
                    width: 920; height: [34, 20, 56, 56][index]
                    opacity: k
                    transform: Translate { y: 18 * (1 - k) }
                    Text { visible: index === 0; text: "Привет! Давайте познакомимся"; color: root.text1; font.family: root.font; font.pixelSize: 28; font.weight: Font.DemiBold }
                    Text { visible: index === 1; text: "Это займёт минуту. Всё можно поменять потом в настройках."; color: root.text2; font.family: root.font; font.pixelSize: 15 }
                    Rectangle {
                        visible: index >= 2; anchors.fill: parent; radius: 14; color: Qt.rgba(1, 1, 1, 0.08)
                        border.width: 1; border.color: index === 2 && root.tt > 7.45 ? root.blue : "transparent"
                        Text { x: 16; y: 8; text: index === 2 ? "Как вас зовут" : "Как звать ассистента"; color: root.text2; font.family: root.font; font.pixelSize: 11 }
                        Text { x: 16; y: 25; font.family: root.font; font.pixelSize: 17; color: root.text1
                               text: index === 3 ? "JustDay" : (root.tt > 8.19 ? "Аня" : root.tt > 8.02 ? "Ан" : root.tt > 7.85 ? "А" : "") }
                    }
                }
            }
        }
        Item {
            id: navRow
            x: 40; y: 480; width: 920; height: 44
            readonly property real k: root.oCubic(root.seg(6.9, 7.4))
            opacity: k
            transform: Translate { y: 14 * (1 - navRow.k) }
            Row { anchors.verticalCenter: parent.verticalCenter; spacing: 6
                Repeater { model: 5; Rectangle { required property int index; width: index ? 7 : 20; height: 7; radius: 3.5; color: index ? Qt.rgba(1, 1, 1, 0.14) : root.blue } } }
            Rectangle { anchors.right: parent.right; width: 124; height: 42; radius: 21; color: root.blue
                Text { anchors.centerIn: parent; text: "Дальше"; color: "white"; font.family: root.font; font.pixelSize: 15; font.weight: Font.DemiBold } }
        }
    }
}
