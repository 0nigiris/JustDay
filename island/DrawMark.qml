// Рисуемые значки с короткой анимацией: галочка, крестик, Face ID.
//
// Не Lottie и не Rive: .riv и .json в qs играть нечем, а плавающая картинка весит больше, чем
// пять отрезков. Контур дорисовывается по `p` от 0 до 1; пока значок не виден, ничего не
// анимируется и не перерисовывается (та же беда, что у Ring.qml). При выключенных анимациях
// рисуется сразу готовым.
import QtQuick

Item {
    id: mark
    property string kind: "check"          // check | cross | faceid
    property color tint: JD.accentGreen
    property real size: 22
    property real p: JD.animOn ? 0 : 1
    property real stroke: Math.max(1.6, size / 11)
    implicitWidth: size
    implicitHeight: size

    // Длительности: быстрые значки — 240 мс, Face ID дольше, у него три шага.
    NumberAnimation on p {
        id: draw
        running: false
        from: 0; to: 1
        duration: mark.kind === "faceid" ? 900 : 260
        easing.type: Easing.OutCubic
    }
    function replay() { if (JD.animOn) { p = 0; draw.restart() } else p = 1 }
    onVisibleChanged: if (visible) replay()
    Component.onCompleted: if (visible) replay()
    onPChanged: cv.requestPaint()
    onTintChanged: cv.requestPaint()

    Canvas {
        id: cv
        anchors.fill: parent
        onPaint: {
            const c = getContext("2d"), s = width, p = mark.p
            c.reset()
            c.lineCap = "round"; c.lineJoin = "round"
            c.strokeStyle = mark.tint; c.lineWidth = mark.stroke
            // Рисует ломаную до доли t её общей длины.
            function poly(pts, t, from) {
                let total = 0; const seg = []
                for (let i = 1; i < pts.length; i++) { const d = Math.hypot(pts[i][0] - pts[i-1][0], pts[i][1] - pts[i-1][1]); seg.push(d); total += d }
                let left = Math.max(0, Math.min(1, t)) * total
                if (left <= 0) return
                c.beginPath(); c.moveTo(pts[0][0] * s, pts[0][1] * s)
                for (let i = 1; i < pts.length; i++) {
                    if (left >= seg[i-1]) { c.lineTo(pts[i][0] * s, pts[i][1] * s); left -= seg[i-1] }
                    else { const k = left / seg[i-1]; c.lineTo((pts[i-1][0] + (pts[i][0] - pts[i-1][0]) * k) * s, (pts[i-1][1] + (pts[i][1] - pts[i-1][1]) * k) * s); break }
                }
                c.stroke()
            }
            const part = (a, b) => Math.max(0, Math.min(1, (p - a) / (b - a)))
            if (mark.kind === "check") {
                poly([[0.22, 0.54], [0.43, 0.74], [0.80, 0.30]], p, 0)
            } else if (mark.kind === "cross") {
                poly([[0.28, 0.28], [0.72, 0.72]], part(0, 0.55), 0)
                poly([[0.72, 0.28], [0.28, 0.72]], part(0.35, 1), 0)
            } else {
                // Face ID: уголки рамки → лицо → галочка. Рамка чуть «вдыхает» в начале.
                const f = part(0, 0.3), r = 0.14
                c.globalAlpha = f
                const o = 0.12 + (1 - f) * 0.05
                for (const [x, y, dx, dy] of [[o, o, 1, 1], [1 - o, o, -1, 1], [o, 1 - o, 1, -1], [1 - o, 1 - o, -1, -1]])
                    poly([[x, y + dy * r], [x, y], [x + dx * r, y]], 1, 0)
                c.globalAlpha = 1
                const face = part(0.25, 0.6) * (1 - part(0.72, 0.8))
                c.globalAlpha = face
                poly([[0.36, 0.38], [0.36, 0.46]], 1, 0); poly([[0.64, 0.38], [0.64, 0.46]], 1, 0)
                poly([[0.5, 0.40], [0.5, 0.56], [0.46, 0.56]], 1, 0)
                poly([[0.36, 0.67], [0.43, 0.72], [0.57, 0.72], [0.64, 0.67]], 1, 0)
                c.globalAlpha = part(0.72, 0.8)
                poly([[0.30, 0.52], [0.45, 0.67], [0.72, 0.36]], part(0.75, 1), 0)
            }
        }
    }
}
