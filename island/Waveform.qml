// Вынесено из shell.qml (Р-80).
import QtQuick

// Одна плавная линия, как у Siri: размах — от уровня микрофона (JD.level уже сглажен), в тишине — лёгкое
// дыхание, чтобы было видно, что слушаем. Без анимаций (JD.animOn) — неподвижная точка (Р2-37).
Item {
    id: wave
    property real t: 0
    FrameAnimation {
        running: wave.visible && JD.animOn
        onTriggered: { wave.t += frameTime; JD.level *= Math.pow(0.9, frameTime * 60); cv.requestPaint() }
    }
    Canvas {
        id: cv
        anchors.fill: parent
        onPaint: {
            const ctx = getContext("2d")
            ctx.reset()
            ctx.fillStyle = ctx.strokeStyle = JD.accentCyan
            const w = width, h = height, mid = h / 2
            if (!JD.animOn) { ctx.beginPath(); ctx.arc(w / 2, mid, 3, 0, 2 * Math.PI); ctx.fill(); return }
            const amp = (1.5 + 1.5 * (0.5 + 0.5 * Math.sin(wave.t * 3)) + (mid - 3) * Math.min(1, JD.level))
            ctx.lineWidth = 2.5
            ctx.lineCap = "round"
            ctx.beginPath()
            for (let x = 0; x <= w; x += 2) {
                const edge = Math.sin(Math.PI * x / w)        // концы сходятся в ноль
                const y = mid + amp * edge * Math.sin(x / w * 7 - wave.t * 9)
                x === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)
            }
            ctx.stroke()
        }
    }
}
