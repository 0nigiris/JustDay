// Шар состояния: слушаю / думаю / ищу / работаю (движок thinking-orbs, island/orbs.js, MIT).
//
// Кольцо Ring остаётся запасным видом: шар рисуется только пока он виден, анимация включена и
// настройка island.orbs не выключена. Без анимации (режим игры, «без анимаций») показывается
// один застывший кадр, а не пустое место. Кадры считаются на 30 в секунду, не на 60: шар 20 px,
// глазу этого хватает, а острову нельзя ради кружка держать процессор занятым (Р-67).
import QtQuick
import "orbs.js" as Orbs

Item {
    id: orb
    property string orbState: "solving"       // working | searching | solving | listening
    property real size: 20
    readonly property var resolved: Orbs.Orbs.resolvePreset(orb.orbState, orb.size < 32 ? 20 : 64)
    property real clock: 1.0
    implicitWidth: size
    implicitHeight: size
    readonly property bool live: visible && JD.animOn

    Timer {
        interval: 33; repeat: true; running: orb.live
        onTriggered: { orb.clock += 0.033; cv.requestPaint() }
    }
    onOrbStateChanged: cv.requestPaint()
    onLiveChanged: cv.requestPaint()

    Canvas {
        id: cv
        anchors.fill: parent
        renderTarget: Canvas.FramebufferObject
        onPaint: {
            const ctx = getContext("2d")
            ctx.reset()
            const r = orb.resolved
            const frame = Orbs.Orbs.MODE_FRAMES[r.mode](orb.size, orb.clock * r.speed, r.opts)
            for (const l of frame.lines) {
                const g = Math.round((1 - Math.min(1, Math.max(0, l.white))) * 255)
                ctx.strokeStyle = "rgba(" + g + "," + g + "," + g + "," + (l.a === undefined ? 1 : l.a) + ")"
                ctx.lineWidth = l.w
                ctx.beginPath(); ctx.moveTo(l.x1, l.y1); ctx.lineTo(l.x2, l.y2); ctx.stroke()
            }
            for (const d of frame.dots) {
                const g = Math.round((1 - Math.min(1, Math.max(0, d.white))) * 255)
                ctx.fillStyle = "rgba(" + g + "," + g + "," + g + "," + (d.a === undefined ? 1 : d.a) + ")"
                ctx.beginPath(); ctx.arc(d.x, d.y, d.r, 0, Math.PI * 2); ctx.fill()
            }
        }
    }
}
