// Shared edge-reveal / autohide controller for dock, tray, and similar strips.
// Overlap/fullscreen hide still allows edge hover reveal (caller sets overlapHide).
import QtQuick

Item {
    id: er

    property bool autohide: false
    // Raw overlap from geometry — debounced into overlapHide.
    property bool overlapRaw: false
    property bool overlapHide: false
    property bool keepVisible: false
    property int hideDelay: 700
    property int overlapDebounceMs: 180
    property real revealZone: 28
    property real flickSpeed: 900
    // "bottom" | "top" | "left" | "right"
    property string edge: "bottom"
    // Dock: flick / hard-edge only. Tray: any hover on the panel window reveals.
    property bool edgeOnly: true

    property bool hovering: !(autohide || overlapHide)
    // True while the pointer is over the strip body (not just the edge peek).
    // Distinct from `hovering`: reveal() sets hovering, but the pointer may already
    // have left — or still be here when the reveal lock expires.
    property bool bodyHovered: false
    // After a reveal, ignore hide for one slide — otherwise mask/hover flicker
    // (edge → body → lost hover mid-animation) snaps the strip back out.
    property bool revealLocked: false

    readonly property bool needHide: autohide || overlapHide
    readonly property bool shown: hovering || keepVisible || !needHide || revealLocked

    readonly property int slideMs: 220
    // Opacity fade on layer-shell panels flash-composites with blur; slide only.
    readonly property int fadeMs: 0

    onAutohideChanged: syncHover()
    onOverlapRawChanged: overlapDebounce.restart()
    onOverlapHideChanged: {
        if (overlapHide) {
            if (!revealLocked)
                hovering = false
        } else {
            syncHover()
        }
    }

    function syncHover() {
        hovering = !needHide
    }

    function reveal() {
        hideTimer.stop()
        hovering = true
        revealLocked = true
        lockTimer.restart()
    }

    function scheduleHide() {
        if (revealLocked)
            return
        if (needHide)
            hideTimer.restart()
    }

    function cancelHide() {
        hideTimer.stop()
    }

    function wants(point, zoneSize) {
        const zone = Math.max(2, zoneSize === undefined || zoneSize === null ? revealZone : zoneSize)
        const flick = Math.max(0, flickSpeed)
        if (flick <= 0)
            return true
        if (edge === "bottom" || edge === "top") {
            const v = point.velocity.y
            if (edge === "top" ? v < -flick : v > flick)
                return true
            const at = point.position.y
            return edge === "top" ? at <= 3 : at >= zone - 3
        }
        const v = point.velocity.x
        if (edge === "left" ? v < -flick : v > flick)
            return true
        const at = point.position.x
        return edge === "left" ? at <= 3 : at >= zone - 3
    }

    function onEdgePoint(point, zoneSize) {
        if (needHide && wants(point, zoneSize))
            reveal()
    }

    function onEdgeEntered() {
        if (needHide)
            reveal()
    }

    function onBodyHover(hovered) {
        bodyHovered = !!hovered
        if (!needHide)
            return
        if (hovered) {
            cancelHide()
            if (!edgeOnly)
                reveal()
            else if (!hovering)
                hovering = true
        } else {
            scheduleHide()
        }
    }

    Timer {
        id: hideTimer
        interval: er.hideDelay
        onTriggered: {
            if (er.revealLocked) return
            if (er.needHide) er.hovering = false
        }
    }
    Timer {
        id: lockTimer
        interval: er.slideMs + 80
        onTriggered: {
            er.revealLocked = false
            // Only start the hide clock if the pointer already left during the lock.
            // Scheduling hide while bodyHovered is still true made the strip vanish
            // ~1–2s into an unbroken hover (lock + hideDelay) — tray and dock both.
            if (er.needHide && !er.keepVisible && !er.bodyHovered)
                er.scheduleHide()
        }
    }
    // Сторож: полоса иногда забывала спрятаться совсем. Весь уход за край держится на том, что
    // придёт событие «курсор ушёл с полосы», а оно приходит не всегда — курсор может уйти в чужое
    // окно, поверхность может пересоздаться, маска измениться. Тогда bodyHovered остаётся true
    // навсегда, прятать некому, и док с лотком висят на экране до перезапуска оболочки.
    // Поэтому раз в полсекунды проверяем само положение курсора, а не память о событиях.
    Timer {
        id: watchdog
        interval: 500
        running: er.needHide && er.hovering && !er.keepVisible
        repeat: true
        onTriggered: {
            if (er.revealLocked || er.bodyHovered) return
            if (!hideTimer.running) hideTimer.restart()
        }
    }
    Timer {
        id: overlapDebounce
        interval: er.overlapDebounceMs
        onTriggered: er.overlapHide = er.overlapRaw
    }

    Component.onCompleted: overlapHide = overlapRaw
}
