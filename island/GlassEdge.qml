// Кромка «жидкого стекла» (Р3-17). Кладётся в карточку панели и видна, только когда выбран
// материал «Стекло»; у матового и сплошного её нет.
//
// Дважды выходило Aero (8 и 9 нояб., «ещё больше Aero»): ровная рамка плюс блестящая полоса
// сверху — это и есть глянец Windows 7. У Liquid Glass свет живёт в толще края: мягкое
// свечение внутрь на несколько пикселей, собранное у одного угла, и слабый ответный отсвет у
// противоположного. Горизонтальной полосы нет вовсе.
//
// «Жидким» (его слово, 9 нояб.) стекло делает свет, который плывёт за курсором с запаздыванием,
// как блик в толще воды. Без курсора он возвращается в верхний левый угол — тот вид, что ему
// понравился. Canvas, потому что Rectangle не умеет ни радиальный свет по рамке, ни мягкий спад
// внутрь; рисует в своём потоке, чтобы перерисовка за курсором не трогала остальной интерфейс.
pragma ComponentBehavior: Bound
import QtQuick

Canvas {
    id: edge
    property real radius: 0
    visible: JD.glassOn
    anchors.fill: parent
    renderStrategy: Canvas.Threaded

    // Где сейчас свет. Курсор ловит обработчик на самой карточке (родителе): у кромки под
    // значками наведения не было бы — его забирают их MouseArea.
    property var hov: null
    readonly property bool lit: hov !== null && hov.hovered
    property real lx: lit ? hov.point.position.x : 0
    property real ly: lit ? hov.point.position.y : 0
    Behavior on lx { enabled: JD.animOn; SmoothedAnimation { velocity: 900; easing.type: Easing.OutCubic } }
    Behavior on ly { enabled: JD.animOn; SmoothedAnimation { velocity: 900; easing.type: Easing.OutCubic } }
    onLxChanged: requestPaint()
    onLyChanged: requestPaint()
    Component {
        id: hovComp
        HoverHandler { enabled: edge.visible }
    }
    Component.onCompleted: hov = hovComp.createObject(edge.parent)

    onWidthChanged: requestPaint()
    onHeightChanged: requestPaint()
    onRadiusChanged: requestPaint()
    onVisibleChanged: if (visible) requestPaint()

    // [отступ внутрь, толщина, яркость]: тонкая яркая кромка и три всё более широких и тусклых
    // слоя под ней — так и получается свечение толщи, а не нарисованная рамка.
    readonly property var layers: [[0, 1, 0.9], [1, 2, 0.16], [3, 4, 0.06], [7, 6, 0.025]]

    onPaint: {
        const ctx = getContext("2d")
        ctx.reset()
        const w = width, h = height
        // Пятно света — в полторы-две высоты карточки: на широком доке иначе светился бы весь верх.
        const R = Math.max(h * 2, 140)
        const spots = [[lx, ly, 1], [w - lx, h - ly, 0.55]]   // блик и ответный отсвет напротив
        for (const [inset, lw, a] of layers) {
            const o = inset + lw / 2
            const r = Math.max(0, radius - o)
            for (const [sx, sy, k] of spots) {
                const g = ctx.createRadialGradient(sx, sy, 0, sx, sy, R)
                g.addColorStop(0, Qt.rgba(1, 1, 1, a * k))
                g.addColorStop(0.45, Qt.rgba(1, 1, 1, a * k * 0.2))
                g.addColorStop(1, Qt.rgba(1, 1, 1, a * 0.05))
                ctx.beginPath()
                ctx.roundedRect(o, o, w - 2 * o, h - 2 * o, r, r)
                ctx.lineWidth = lw
                ctx.strokeStyle = g
                ctx.stroke()
            }
        }
    }
}
