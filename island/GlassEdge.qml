// Кромка «жидкого стекла» (Р3-17). Кладётся в карточку панели и видна, только когда выбран
// материал «Стекло»; у матового и сплошного её нет.
//
// Дважды выходило Aero (8 и 9 нояб., «ещё больше Aero»): ровная рамка плюс блестящая полоса
// сверху — это и есть глянец Windows 7. У Liquid Glass свет живёт в толще края: мягкое
// свечение по всему кругу внутрь на несколько пикселей, ярче по диагонали — у верхнего левого
// угла, слабее у нижнего правого, почти нет у двух других. Горизонтальной полосы нет вовсе.
// Canvas, потому что Rectangle не умеет ни диагональный градиент рамки, ни мягкий спад внутрь;
// перерисовывается только при смене размера.
import QtQuick

Canvas {
    id: edge
    property real radius: 0
    visible: JD.glassOn
    anchors.fill: parent
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
        for (const [inset, lw, a] of layers) {
            // Свет собран в два угла: по оси от верхнего левого к нижнему правому, но длиной в
            // высоту карточки с каждой стороны, иначе на широком доке светился бы весь верх.
            const g = ctx.createLinearGradient(0, 0, w, h)
            const k = Math.min(0.45, h / (w + h))
            g.addColorStop(0, Qt.rgba(1, 1, 1, a))
            g.addColorStop(k, Qt.rgba(1, 1, 1, a * 0.12))
            g.addColorStop(1 - k, Qt.rgba(1, 1, 1, a * 0.08))
            g.addColorStop(1, Qt.rgba(1, 1, 1, a * 0.55))
            const o = inset + lw / 2
            const r = Math.max(0, radius - o)
            ctx.beginPath()
            ctx.roundedRect(o, o, w - 2 * o, h - 2 * o, r, r)
            ctx.lineWidth = lw
            ctx.strokeStyle = g
            ctx.stroke()
        }
    }
}
