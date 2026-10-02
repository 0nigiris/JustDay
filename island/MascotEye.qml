// Один глаз маскота: тринадцать форм, нарисованных кодом.
//
// Отдельным файлом, потому что глаза носят оба: и наш нарисованный кодом шарик, и живой зверь из
// скина. Тело скина — настоящая картинка, и нарисовать для неё одиннадцать состояний и десяток
// анимаций безделья картинками никто никогда не возьмётся. Глаза же кодом умеют всё и ничего не
// стоят: тело даёт красоту, глаза — жизнь.
//
// Формы перенесены из Coucou (MIT) один в один: та же геометрия, те же доли от размера.
//
// Холст перерисовывается только когда форма действительно поменялась. Спираль и звезда крутятся
// сами и просят перерисовку, пока крутятся; остальные одиннадцать стоят неподвижно.
import QtQuick

Canvas {
    id: eye
    property int side: 1                     // -1 левый, +1 правый
    property string shape: "pill"            // одна из тринадцати форм
    property real open: 1                    // 1 — открыт, 0 — закрыт: моргание
    property real size: 26                   // размер тела, от которого считаются все доли
    property color ink: "#1a1412"
    readonly property real w: size * 0.25
    readonly property real h: size * 0.27
    readonly property bool spinning: shape === "spiral" || shape === "star"
    property real spin: 0

    width: size * 0.5
    height: size * 0.5
    antialiasing: true

    // Spin follows display refresh (~170 Hz on DP-2) instead of a fixed ~30 fps timer.
    FrameAnimation {
        running: eye.spinning && visible && JD.animOn
        onTriggered: {
            eye.spin += 0.1 * Math.max(0.5, Math.min(3.0, frameTime * 60))
            eye.requestPaint()
        }
    }
    Connections {
        target: me
        function onEyeShapeChanged() { eye.requestPaint() }
        function onOpenChanged() { eye.requestPaint() }
    }

    onPaint: {
        const x = getContext("2d")
        const ink = eye.ink
        const sd = eye.side
        const w = eye.w, h = eye.h
        x.reset()
        x.save()
        x.translate(width / 2, height / 2)
        x.fillStyle = ink
        x.strokeStyle = ink

        const pill = (pw, ph) => {
            const hh = Math.max(ph * open, pw * 0.3)
            const r = Math.min(pw / 2, hh / 2)
            x.beginPath()
            x.moveTo(-pw / 2 + r, -hh / 2)
            x.arcTo(pw / 2, -hh / 2, pw / 2, hh / 2, r)
            x.arcTo(pw / 2, hh / 2, -pw / 2, hh / 2, r)
            x.arcTo(-pw / 2, hh / 2, -pw / 2, -hh / 2, r)
            x.arcTo(-pw / 2, -hh / 2, pw / 2, -hh / 2, r)
            x.closePath()
            x.fill()
        }
        const bar = (bw, bh, rot) => {
            if (rot) x.rotate(rot)
            x.beginPath()
            const r = bh / 2
            x.moveTo(-bw / 2 + r, -bh / 2)
            x.arcTo(bw / 2, -bh / 2, bw / 2, bh / 2, r)
            x.arcTo(bw / 2, bh / 2, -bw / 2, bh / 2, r)
            x.arcTo(-bw / 2, bh / 2, -bw / 2, -bh / 2, r)
            x.arcTo(-bw / 2, -bh / 2, bw / 2, -bh / 2, r)
            x.closePath()
            x.fill()
            if (rot) x.rotate(-rot)
        }
        const smile = () => {
            x.lineWidth = w * 0.5
            x.lineCap = "round"
            x.beginPath()
            x.arc(0, h * 0.18, w * 0.82, Math.PI * 1.12, Math.PI * 1.88)
            x.stroke()
        }

        switch (shape) {
        case "wide": pill(w * 1.16, h * 1.12); break
        case "pill": pill(w, h); break
        case "dot":
            x.beginPath(); x.arc(0, 0, w * 0.45, 0, Math.PI * 2); x.fill(); break
        case "line": bar(w * 1.56, w * 0.42, -sd * 0.2); break
        case "flat": bar(w * 1.44, w * 0.4, 0); break
        case "happy": smile(); break
        case "closed":
            x.lineWidth = w * 0.36
            x.lineCap = "round"
            x.beginPath()
            x.arc(0, -h * 0.08, w * 0.78, Math.PI * 0.15, Math.PI * 0.85)
            x.stroke()
            break
        case "spiral":
            x.lineWidth = w * 0.22
            x.lineCap = "round"
            x.beginPath()
            for (let a = 0; a < 4.4 * Math.PI; a += 0.2) {
                const r = w * 0.06 + a * w * 0.058
                const aa = a + eye.spin * 9 * sd
                const px = Math.cos(aa) * r, py = Math.sin(aa) * r
                if (a === 0) x.moveTo(px, py); else x.lineTo(px, py)
            }
            x.stroke()
            break
        case "heart":
            x.fillStyle = "#ff4d6d"
            x.beginPath()
            {
                const s = w * 1.2
                x.moveTo(0, s * 0.35)
                x.bezierCurveTo(-s * 0.9, -s * 0.25, -s * 0.35, -s * 0.85, 0, -s * 0.3)
                x.bezierCurveTo(s * 0.35, -s * 0.85, s * 0.9, -s * 0.25, 0, s * 0.35)
            }
            x.fill()
            break
        case "star":
            x.fillStyle = "#f7b32b"
            x.rotate(eye.spin * 1.5 * sd)
            x.beginPath()
            for (let i = 0; i < 10; i++) {
                const r = i % 2 ? w * 0.46 : w * 1.05
                const a = -Math.PI / 2 + i * Math.PI / 5
                const px = Math.cos(a) * r, py = Math.sin(a) * r
                if (i === 0) x.moveTo(px, py); else x.lineTo(px, py)
            }
            x.closePath()
            x.fill()
            break
        case "tired":
            bar(w, h * 0.38, 0)
            x.translate(0, -h * 0.16)
            bar(w * 1.24, w * 0.22, 0)
            break
        case "wink":
            if (sd < 0) pill(w, h); else smile()
            break
        default: pill(w, h)
        }
        x.restore()
    }
}
