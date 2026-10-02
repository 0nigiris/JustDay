// Pure helpers twin of EdgeReveal.qml / JD.dockCoveredOn.
// Quickshell's qs-module intercept often fails on ".js" imports, so the live UI
// inlines the controller in EdgeReveal.qml and overlap checks in JD.qml.
// Keep this file in sync when changing edge/overlap math.
// Shared helpers for edge reveal / autohide (dock, tray, island peek).
.pragma library

function defaultZone() { return 28 }
function defaultFlick() { return 900 }
function defaultHideMs() { return 600 }
function slideMs() { return 220 }
function fadeMs() { return 0 }  // slide only — opacity fade caused tray/dock flicker

function islandPeekHeight(hoverReveal) {
    return hoverReveal !== false ? 3 : 0
}

function edgeWants(point, edge, zoneSize, flickSpeed) {
    const zone = Math.max(2, zoneSize === undefined || zoneSize === null ? defaultZone() : zoneSize)
    const flick = Math.max(0, flickSpeed === undefined || flickSpeed === null ? defaultFlick() : flickSpeed)
    if (flick <= 0) return true
    if (edge === "bottom" || edge === "top") {
        const v = point.velocity.y
        if (edge === "top" ? v < -flick : v > flick) return true
        const at = point.position.y
        return edge === "top" ? at <= 3 : at >= zone - 3
    }
    const v = point.velocity.x
    if (edge === "left" ? v < -flick : v > flick) return true
    const at = point.position.x
    return edge === "left" ? at <= 3 : at >= zone - 3
}

var COVER_IGNORE = ["quickshell", "plasmashell", "org.kde.plasmashell",
                    "kwin_wayland", "ksplashqml", "xwaylandvideobridge",
                    "xdg-desktop-portal-kde"]

function coversDockStrip(w, screen, stripPx, atTop, skipList, islandX, islandW) {
    if (!w || !screen || w.minimized) return false
    const app = String(w.app || "").toLowerCase()
    if (app && (COVER_IGNORE.indexOf(app) >= 0
                || (skipList && skipList.indexOf(app) >= 0)))
        return false

    const sx = (w.ow > 0 ? (w.ox || 0) : screen.x)
    const sy = (w.ow > 0 ? (w.oy || 0) : screen.y)
    const sw = (w.ow > 0 ? w.ow : screen.width)
    const sh = (w.oh > 0 ? w.oh : screen.height)
    if (sw <= 0 || sh <= 0) return false

    if (w.full === true) {
        if (w.screen && screen.name)
            return w.screen === screen.name
        if (w.ow > 0)
            return Math.abs((w.ox || 0) - screen.x) <= 4 && Math.abs((w.oy || 0) - screen.y) <= 4
        return false
    }

    const strip = Math.max(24, stripPx || 60)
    let onScreen = false
    if (w.screen && screen.name && w.screen === screen.name) onScreen = true
    else if (w.ow > 0 && w.oh > 0
             && Math.abs((w.ox || 0) - screen.x) <= 4 && Math.abs((w.oy || 0) - screen.y) <= 4)
        onScreen = true
    else {
        const ww0 = w.w || 0, wh0 = w.h || 0
        if (ww0 <= 0 || wh0 <= 0) return false
        const wx0 = w.x || 0, wy0 = w.y || 0
        onScreen = wx0 < sx + sw && wx0 + ww0 > sx && wy0 < sy + sh && wy0 + wh0 > sy
    }
    if (!onScreen) return false

    const ww = w.w || 0, wh = w.h || 0
    if (ww <= 0 || wh <= 0) return false
    const wx = w.x || 0, wy = w.y || 0
    if (wx >= sx + sw || wx + ww <= sx) return false

    if (Math.abs(wy - sy) <= 8 && Math.abs(wh - sh) <= 8
        && Math.abs(wx - sx) <= 8 && Math.abs(ww - sw) <= 8)
        return true

    // Real dock island (icons+padding). Without it, refuse full-width-strip false positives.
    const iw = Number(islandW) || 0
    if (iw <= 0) return false
    const il = sx + (Number(islandX) || 0)
    const ir = il + iw
    if (wx >= ir || wx + ww <= il) return false

    const minBite = Math.min(20, Math.max(8, Math.round(strip * 0.35)))
    let overlapY = 0
    if (atTop) {
        const stripBottom = sy + strip
        overlapY = Math.min(wy + wh, stripBottom) - Math.max(wy, sy)
    } else {
        const stripTop = sy + sh - strip
        overlapY = Math.min(wy + wh, sy + sh) - Math.max(wy, stripTop)
    }
    if (overlapY < minBite) return false

    const overlapX = Math.min(wx + ww, ir) - Math.max(wx, il)
    const minX = Math.min(24, Math.max(8, Math.round(iw * 0.08)))
    return overlapX >= minX
}

function anyCoversDockStrip(windows, screen, stripPx, atTop, skipList, islandX, islandW) {
    if (!windows || !windows.length || !screen) return false
    for (let i = 0; i < windows.length; i++) {
        if (coversDockStrip(windows[i], screen, stripPx, atTop, skipList, islandX, islandW))
            return true
    }
    return false
}
