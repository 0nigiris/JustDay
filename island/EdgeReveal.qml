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
        if (!needHide)
            return
        if (hovered) {
            cancelHide()
            if (!edgeOnly)
                reveal()
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
            // If pointer already left, start the normal hide clock.
            if (er.needHide && !er.keepVisible)
                er.scheduleHide()
        }
    }
    Timer {
        id: overlapDebounce
        interval: er.overlapDebounceMs
        onTriggered: er.overlapHide = er.overlapRaw
    }

    Component.onCompleted: overlapHide = overlapRaw
}
