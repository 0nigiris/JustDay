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
    // Главный значок Джарвиса: состояние берётся из демона, а голос человека надувает шар.
    property bool main: false
    property real voice: 0                    // 0..1; шар раздувается, точки расходятся
    property real pump: 0                     // сглаженный voice: без сглаживания шар дёргался бы на каждый кадр
    readonly property string mainState: JD.dstate === "listening" ? "listening"
        : JD.searchingNow ? "searching" : JD.workers > 0 ? "working"
        : (JD.dstate === "thinking" || JD.dstate === "speaking") ? "solving" : "working"
    property real size: 20
    readonly property var resolved: Orbs.Orbs.resolvePreset(orb.orbState, orb.size < 32 ? 20 : 64)
    property real clock: 1.0
    implicitWidth: size
    implicitHeight: size
    readonly property bool live: visible && JD.animOn

    Timer {
        interval: (orb.main && JD.dstate === "idle") ? 66 : 33; repeat: true; running: orb.live
        onTriggered: {
            orb.clock += 0.033
            const want = orb.main ? (JD.dstate === "listening" ? JD.level : 0) : orb.voice
            orb.pump += (Math.min(1, want * 1.6) - orb.pump) * 0.35
            cv.requestPaint()
        }
    }
    onOrbStateChanged: cv.requestPaint()
    onMainStateChanged: if (main) orbState = mainState
    Component.onCompleted: if (main) orbState = mainState
    onLiveChanged: cv.requestPaint()

    Canvas {
        id: cv
        // Холст втрое больше шара: раздутый шар выходит за свои 20 px, а раскладку не двигает.
        anchors.centerIn: parent
        width: orb.size * 3; height: orb.size * 3
        renderTarget: Canvas.FramebufferObject
        onPaint: {
            const ctx = getContext("2d")
            ctx.reset()
            const r = orb.resolved
            const frame = Orbs.Orbs.MODE_FRAMES[r.mode](orb.size, orb.clock * r.speed, r.opts)
            const c = orb.size / 2, off = orb.size, k = 1 + orb.pump * 0.9   // до +90% при громкой речи
            const X = (x) => off + c + (x - c) * k, Y = (y) => off + c + (y - c) * k
            for (const l of frame.lines) {
                const g = Math.round((1 - Math.min(1, Math.max(0, l.white))) * 255)
                ctx.strokeStyle = "rgba(" + g + "," + g + "," + g + "," + (l.a === undefined ? 1 : l.a) + ")"
                ctx.lineWidth = l.w
                ctx.beginPath(); ctx.moveTo(X(l.x1), Y(l.y1)); ctx.lineTo(X(l.x2), Y(l.y2)); ctx.stroke()
            }
            for (const d of frame.dots) {
                const g = Math.round((1 - Math.min(1, Math.max(0, d.white))) * 255)
                ctx.fillStyle = "rgba(" + g + "," + g + "," + g + "," + (d.a === undefined ? 1 : d.a) + ")"
                ctx.beginPath(); ctx.arc(X(d.x), Y(d.y), d.r * (1 + orb.pump * 0.35), 0, Math.PI * 2); ctx.fill()
            }
        }
    }
}
