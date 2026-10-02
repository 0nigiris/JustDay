"use strict";
/**
 * JustDay Genie — minimize/restore toward JustDay dock icon rects (IconsJson).
 *
 * Same Size+Translation+Opacity recipe as stock KWin "squash", but icon targets
 * come from the JustDay dock (Plasma iconGeometry is empty without a task manager).
 *
 * Uses effects.windowMinimized / windowUnminimized when available so restore
 * (unminimize into the dock icon, then expand) is as reliable as minimize.
 * Chromium/Electron CSD apps are fine: we never touch noBorder / decorations —
 * only a visual effect transform. Do not add KWin rules that force SSD/CSD.
 */
var genie = {
    duration: animationTime(320),
    icons: {},
    loadConfig: function () {
        genie.duration = animationTime(320);
        try {
            var raw = effect.readConfig("IconsJson", "{}");
            genie.icons = JSON.parse(raw && raw.length ? raw : "{}") || {};
        } catch (e) {
            genie.icons = {};
        }
    },
    isAnimatable: function (window) {
        if (!window) return false;
        if (window.popupWindow || window.dock || window.desktop || window.splash ||
            window.toolbar || window.notification)
            return false;
        // Skip lock screen / outline / unmanaged chrome.
        try {
            if (window.lockScreen || window.outline) return false;
            if (window.managed === false) return false;
        } catch (e) {}
        return true;
    },
    targetFor: function (window) {
        var app = String(window.resourceClass || "").toLowerCase();
        var id = String(window.internalId || "");
        var hit = genie.icons[id] || genie.icons[app] || genie.icons["*"];
        if (!hit && app.indexOf(".") > 0)
            hit = genie.icons[app.split(".").pop()];
        // Also try "app:foo" keys the dock publishes.
        if (!hit && app)
            hit = genie.icons["app:" + app];
        if (!hit || !(hit.w > 0) || !(hit.h > 0))
            return null;
        return hit;
    },
    rectFrom: function (window) {
        // Prefer JustDay dock icon map — Plasma panel iconGeometry points elsewhere
        // (or to a hidden task manager) and would send the genie to the wrong place.
        var hit = genie.targetFor(window);
        if (hit && hit.w > 0 && hit.h > 0)
            return { x: hit.x, y: hit.y, width: hit.w, height: hit.h };
        var ig = window.iconGeometry;
        if (ig && ig.width > 0 && ig.height > 0)
            return { x: ig.x, y: ig.y, width: ig.width, height: ig.height };
        return null;
    },
    windowRectOf: function (window) {
        // frameGeometry includes SSD; for CSD Chromium it matches the client buffer.
        // Prefer it so Size/Translation line up with what the user sees.
        var g = window.frameGeometry || window.geometry;
        if (!g) return null;
        return { x: g.x, y: g.y, width: g.width, height: g.height };
    },
    slotWindowMinimized: function (window) {
        if (effects.hasActiveFullScreenEffect) return;
        if (!genie.isAnimatable(window)) return;
        genie.loadConfig();
        var iconRect = genie.rectFrom(window);
        if (!iconRect) return;
        var windowRect = genie.windowRectOf(window);
        if (!windowRect || !(windowRect.width > 0) || !(windowRect.height > 0)) return;
        window.setData(Effect.WindowForceBlurRole, true);
        if (window.unminimizeAnimation) {
            if (redirect(window.unminimizeAnimation, Effect.Backward)) return;
            cancel(window.unminimizeAnimation);
            delete window.unminimizeAnimation;
        }
        if (window.minimizeAnimation) {
            if (redirect(window.minimizeAnimation, Effect.Forward)) return;
            cancel(window.minimizeAnimation);
        }
        window.minimizeAnimation = animate({
            window: window,
            curve: QEasingCurve.InCubic,
            duration: genie.duration,
            keepAlive: false,
            animations: [
                { type: Effect.Size,
                  from: { value1: windowRect.width, value2: windowRect.height },
                  to: { value1: iconRect.width, value2: iconRect.height } },
                { type: Effect.Translation,
                  from: { value1: 0.0, value2: 0.0 },
                  to: {
                      value1: iconRect.x - windowRect.x - (windowRect.width - iconRect.width) / 2,
                      value2: iconRect.y - windowRect.y - (windowRect.height - iconRect.height) / 2
                  } },
                { type: Effect.Opacity, from: 1.0, to: 0.0 }
            ]
        });
    },
    slotWindowUnminimized: function (window) {
        if (effects.hasActiveFullScreenEffect) return;
        if (!genie.isAnimatable(window)) return;
        genie.loadConfig();
        var iconRect = genie.rectFrom(window);
        if (!iconRect) return;
        var windowRect = genie.windowRectOf(window);
        if (!windowRect || !(windowRect.width > 0) || !(windowRect.height > 0)) return;
        window.setData(Effect.WindowForceBlurRole, true);
        if (window.minimizeAnimation) {
            if (redirect(window.minimizeAnimation, Effect.Backward)) return;
            cancel(window.minimizeAnimation);
            delete window.minimizeAnimation;
        }
        if (window.unminimizeAnimation) {
            if (redirect(window.unminimizeAnimation, Effect.Forward)) return;
            cancel(window.unminimizeAnimation);
        }
        window.unminimizeAnimation = animate({
            window: window,
            curve: QEasingCurve.OutCubic,
            duration: genie.duration,
            keepAlive: false,
            animations: [
                { type: Effect.Size,
                  from: { value1: iconRect.width, value2: iconRect.height },
                  to: { value1: windowRect.width, value2: windowRect.height } },
                { type: Effect.Translation,
                  from: {
                      value1: iconRect.x - windowRect.x - (windowRect.width - iconRect.width) / 2,
                      value2: iconRect.y - windowRect.y - (windowRect.height - iconRect.height) / 2
                  },
                  to: { value1: 0.0, value2: 0.0 } },
                { type: Effect.Opacity, from: 0.0, to: 1.0 }
            ]
        });
    },
    slotWindowAdded: function (window) {
        // Fallback path when windowMinimized signals are missing.
        window.minimizedChanged.connect(function () {
            if (window.minimized) genie.slotWindowMinimized(window);
            else genie.slotWindowUnminimized(window);
        });
    },
    restoreForceBlurState: function (window) {
        window.setData(Effect.WindowForceBlurRole, null);
    },
    init: function () {
        effect.configChanged.connect(genie.loadConfig);
        effect.animationEnded.connect(this.restoreForceBlurState.bind(this));
        // Prefer dedicated minimize signals — correct timing for BOTH directions
        // (minimize into dock icon AND restore/unminimize from dock icon).
        var hasMin = typeof effects.windowMinimized === "object" || typeof effects.windowMinimized === "function";
        var hasUnmin = typeof effects.windowUnminimized === "object" || typeof effects.windowUnminimized === "function";
        // In KWin scripted effects these are Signal objects; connect is the tell.
        try {
            if (effects.windowMinimized && effects.windowMinimized.connect &&
                effects.windowUnminimized && effects.windowUnminimized.connect) {
                effects.windowMinimized.connect(genie.slotWindowMinimized);
                effects.windowUnminimized.connect(genie.slotWindowUnminimized);
                genie.loadConfig();
                return;
            }
        } catch (e) {}
        effects.windowAdded.connect(genie.slotWindowAdded);
        for (const window of effects.stackingOrder)
            genie.slotWindowAdded(window);
        genie.loadConfig();
    }
};
genie.init();
