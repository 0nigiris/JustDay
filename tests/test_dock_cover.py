"""Dock island overlap rules (mirror of JD.windowCoversDockStrip / EdgeReveal.js)."""
from __future__ import annotations

IGNORE = {"quickshell", "plasmashell", "org.kde.plasmashell", "kwin_wayland",
          "ksplashqml", "xwaylandvideobridge", "xdg-desktop-portal-kde"}


def covers(w, screen, strip_px=60, at_top=False, skip=(), island_x=None, island_w=None):
    if not w or not screen or w.get("minimized"):
        return False
    app = str(w.get("app") or "").lower()
    if app and (app in IGNORE or app in skip):
        return False
    sx = w["ox"] if w.get("ow", 0) > 0 else screen["x"]
    sy = w["oy"] if w.get("ow", 0) > 0 else screen["y"]
    sw = w["ow"] if w.get("ow", 0) > 0 else screen["width"]
    sh = w["oh"] if w.get("oh", 0) > 0 else screen["height"]
    if sw <= 0 or sh <= 0:
        return False
    if w.get("full") is True:
        if w.get("screen") and screen.get("name"):
            return w["screen"] == screen["name"]
        if w.get("ow", 0) > 0:
            return abs(w.get("ox", 0) - screen["x"]) <= 4 and abs(w.get("oy", 0) - screen["y"]) <= 4
        return False
    strip = max(24, strip_px)
    on = False
    if (w.get("screen") and screen.get("name") and w["screen"] == screen["name"]) or (w.get("ow", 0) > 0 and abs(w.get("ox", 0) - screen["x"]) <= 4 and abs(w.get("oy", 0) - screen["y"]) <= 4):
        on = True
    else:
        ww, wh = w.get("w", 0), w.get("h", 0)
        if ww <= 0 or wh <= 0:
            return False
        wx, wy = w.get("x", 0), w.get("y", 0)
        on = wx < sx + sw and wx + ww > sx and wy < sy + sh and wy + wh > sy
    if not on:
        return False
    ww, wh = w.get("w", 0), w.get("h", 0)
    if ww <= 0 or wh <= 0:
        return False
    wx, wy = w.get("x", 0), w.get("y", 0)
    if wx >= sx + sw or wx + ww <= sx:
        return False
    if (abs(wy - sy) <= 8 and abs(wh - sh) <= 8 and abs(wx - sx) <= 8 and abs(ww - sw) <= 8):
        return True
    iw = int(island_w or 0)
    if iw <= 0:
        return False
    il = sx + int(island_x or 0)
    ir = il + iw
    if wx >= ir or wx + ww <= il:
        return False
    min_bite = min(20, max(8, round(strip * 0.35)))
    if at_top:
        overlap_y = min(wy + wh, sy + strip) - max(wy, sy)
    else:
        strip_top = sy + sh - strip
        overlap_y = min(wy + wh, sy + sh) - max(wy, strip_top)
    if overlap_y < min_bite:
        return False
    overlap_x = min(wx + ww, ir) - max(wx, il)
    min_x = min(24, max(8, round(iw * 0.08)))
    return overlap_x >= min_x


SCR = {"name": "DP-2", "x": 0, "y": 0, "width": 2560, "height": 1440}
# Centered dock island ~700px (icons+padding) on a 2560 output.
ISL_X, ISL_W = 930, 700


def test_empty_desktop_never_covers():
    assert covers(None, SCR, island_x=ISL_X, island_w=ISL_W) is False


def test_quickshell_layer_ignored():
    w = {"app": "quickshell", "minimized": False, "full": False,
         "x": 0, "y": 1097, "w": 2560, "h": 343,
         "screen": "DP-2", "ox": 0, "oy": 0, "ow": 2560, "oh": 1440}
    assert covers(w, SCR, island_x=ISL_X, island_w=ISL_W) is False


def test_one_pixel_graze_ignored():
    # Bottom edge at 1384 → only 4px into a 60px strip (minBite ≈ 20).
    w = {"app": "kitty", "minimized": False, "full": False,
         "x": 1000, "y": 1200, "w": 400, "h": 184,
         "screen": "DP-2", "ox": 0, "oy": 0, "ow": 2560, "oh": 1440}
    assert covers(w, SCR, island_x=ISL_X, island_w=ISL_W) is False


def test_real_island_overlap_hides():
    w = {"app": "discord", "minimized": False, "full": False,
         "x": 1000, "y": 1200, "w": 800, "h": 240,
         "screen": "DP-2", "ox": 0, "oy": 0, "ow": 2560, "oh": 1440}
    assert covers(w, SCR, island_x=ISL_X, island_w=ISL_W) is True


def test_bottom_edge_beside_island_does_not_hide():
    # Window sits on the bottom strip but only on the left — clear of the centered island.
    w = {"app": "kitty", "minimized": False, "full": False,
         "x": 40, "y": 1200, "w": 500, "h": 240,
         "screen": "DP-2", "ox": 0, "oy": 0, "ow": 2560, "oh": 1440}
    assert covers(w, SCR, island_x=ISL_X, island_w=ISL_W) is False


def test_bottom_edge_right_of_island_does_not_hide():
    w = {"app": "firefox", "minimized": False, "full": False,
         "x": 1800, "y": 1200, "w": 600, "h": 240,
         "screen": "DP-2", "ox": 0, "oy": 0, "ow": 2560, "oh": 1440}
    assert covers(w, SCR, island_x=ISL_X, island_w=ISL_W) is False


def test_unknown_island_refuses_full_strip_false_positive():
    # Without island width, must not treat the whole bottom edge as the dock.
    w = {"app": "discord", "minimized": False, "full": False,
         "x": 40, "y": 1200, "w": 800, "h": 240,
         "screen": "DP-2", "ox": 0, "oy": 0, "ow": 2560, "oh": 1440}
    assert covers(w, SCR) is False


def test_fullscreen_other_screen_ignored():
    w = {"app": "mpv", "minimized": False, "full": True,
         "x": 2560, "y": 360, "w": 1920, "h": 1080,
         "screen": "HDMI-A-1", "ox": 2560, "oy": 360, "ow": 1920, "oh": 1080}
    assert covers(w, SCR, island_x=ISL_X, island_w=ISL_W) is False


def test_fullscreen_same_screen_hides():
    w = {"app": "mpv", "minimized": False, "full": True,
         "x": 0, "y": 0, "w": 2560, "h": 1440,
         "screen": "DP-2", "ox": 0, "oy": 0, "ow": 2560, "oh": 1440}
    assert covers(w, SCR, island_x=ISL_X, island_w=ISL_W) is True


def test_minimized_ignored_even_if_geometry_fills():
    w = {"app": "helium", "minimized": True, "full": False,
         "x": 0, "y": 0, "w": 2560, "h": 1440,
         "screen": "DP-2", "ox": 0, "oy": 0, "ow": 2560, "oh": 1440}
    assert covers(w, SCR, island_x=ISL_X, island_w=ISL_W) is False


def test_tiny_corner_clip_ignored():
    w = {"app": "float", "minimized": False, "full": False,
         "x": 2500, "y": 1300, "w": 40, "h": 140,  # only 40px wide at edge
         "screen": "DP-2", "ox": 0, "oy": 0, "ow": 2560, "oh": 1440}
    assert covers(w, SCR, island_x=ISL_X, island_w=ISL_W) is False


def test_dragging_a_window_did_not_rebuild_the_dock() -> None:
    """Пока окно тянули за угол, список окон приходил с новой геометрией ~5 раз в секунду, и док каждый раз
    пересоздавал все ячейки (Р-40). Теперь `windows` — состав и состояние (док собирается по нему) — меняется
    только когда что-то открыли, закрыли, свернули; геометрия живёт отдельно в `windowRects`, для тех, кто
    смотрит, накрыло ли окно док. Функции берутся из настоящего JD.qml и выполняются в node."""
    import json
    import re
    import shutil
    import subprocess
    from pathlib import Path

    import pytest

    node = shutil.which("node")
    if not node:
        pytest.skip("нет node, чтобы выполнить функции островка")
    jd = Path("island/JD.qml").read_text(encoding="utf-8")
    src = "\n".join(re.search(r"(    function " + name + r"\(.+?\n    \})", jd, re.S).group(1) for name in ("windowShape", "setWindows"))
    win = {"id": "1", "app": "kate", "title": "a", "minimized": False, "active": True, "x": 0, "y": 0, "w": 800, "h": 600}
    js = """
const S = { windows: [], windowRects: [], _windowShape: "" }
const { setWindows } = new Function("S", "with (S) { " + SRC + "; return { setWindows } }")(S)
const out = {}
setWindows([WIN])
const first = S.windows
setWindows([MOVED])
out.moved_kept_windows = S.windows === first
out.moved_updated_rects = S.windowRects[0].x === 40 && S.windowRects[0].w === 900
setWindows([MINIMIZED])
out.minimized_rebuilt = S.windows !== first && S.windows[0].minimized === true
setWindows([])
out.closed_rebuilt = S.windows.length === 0
console.log(JSON.stringify(out))
"""
    for key, val in (("SRC", json.dumps(src)), ("WIN", json.dumps(win)), ("MOVED", json.dumps({**win, "x": 40, "w": 900})),
                     ("MINIMIZED", json.dumps({**win, "minimized": True, "x": 40, "w": 900}))):
        js = js.replace(key, val)
    got = json.loads(subprocess.run([node, "-e", js], capture_output=True, text=True, check=True).stdout)
    assert got == {"moved_kept_windows": True, "moved_updated_rects": True, "minimized_rebuilt": True, "closed_rebuilt": True}
