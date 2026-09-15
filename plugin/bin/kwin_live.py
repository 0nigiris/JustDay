"""kwin-mcp, pre-connected to the live desktop, plus two batch tools that cut model round-trips.

`look` returns the screenshot itself (one turn instead of "screenshot → Read") and remembers how the
image maps onto the screen; `act` runs a whole sequence of clicks/keys/typing/drags in *image*
coordinates of the last look and returns a fresh look — so the model never does coordinate math and
a GUI step costs one turn instead of three or four.
"""
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Annotated

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))  # relmouse.py next to this file
from kwin_mcp import server
from mcp.server.mcpserver.utilities.types import Image
from pydantic import Field

try:
    server._engine.session_connect()
except Exception as e:
    print(f"kwin_live: auto-connect failed: {e}", file=sys.stderr)

JustDay = str(Path.home() / ".local/bin/justday")
FONT = "/usr/share/fonts/dejavu-sans-fonts/DejaVuSans-Bold.ttf"
CLICKABLE = {"button", "push button", "toggle button", "menu item", "list item", "link", "check box",
             "radio button", "page tab", "combo box", "entry", "text", "tree item", "table cell", "slider",
             "spin button", "icon"}
TERMINALS = {"kitty", "org.kde.konsole", "konsole", "alacritty", "foot", "org.wezfurlong.wezterm", "com.mitchellh.ghostty"}
_map = {"origin_x": 0, "origin_y": 0, "scale": 1.0, "app": ""}
_marks: dict[int, tuple[int, int]] = {}


def _justday(*args: str, timeout: float = 20) -> str:
    return subprocess.run([JustDay, *args], capture_output=True, text=True, timeout=timeout).stdout


def _elements(app: str, x0: int, y0: int, w: int, h: int) -> list[dict]:
    """Visible actionable accessibility elements of the active app (Qt/GTK apps; Electron usually has none)."""
    if not app:
        return []
    req = json.dumps({"op": "find", "query": "", "app_name": app.split(".")[-1], "states": ["showing", "visible"]})
    try:
        out = subprocess.run([sys.executable, "-m", "kwin_mcp.accessibility"], input=req, capture_output=True,
                             text=True, timeout=2.5, env=server._engine._session_env()).stdout
        found = json.loads(out).get("result") or []
    except Exception:
        return []
    seen, res = set(), []
    for el in found:
        cx, cy = el["x"] + el["width"] / 2, el["y"] + el["height"] / 2
        if (el["width"] < 4 or el["height"] < 4 or not (x0 <= cx < x0 + w and y0 <= cy < y0 + h)
                or (el["role"] not in CLICKABLE and not el["actions"]) or el["role"] in ("frame", "application")):
            continue
        key = (el["x"], el["y"], el["width"], el["height"])
        if key not in seen:
            seen.add(key)
            res.append(el)
    return res[:150]


def _annotate(data: bytes, els: list[dict]) -> tuple[bytes, str]:
    import io

    from PIL import Image as PILImage, ImageDraw, ImageFont

    img = PILImage.open(io.BytesIO(data)).convert("RGB")
    draw, font = ImageDraw.Draw(img), ImageFont.truetype(FONT, 12)
    s, ox, oy = _map["scale"], _map["origin_x"], _map["origin_y"]
    _marks.clear()
    legend = []
    for n, el in enumerate(els, 1):
        x, y = (el["x"] - ox) * s, (el["y"] - oy) * s
        x2, y2 = x + el["width"] * s, y + el["height"] * s
        draw.rectangle([x, y, x2, y2], outline=(255, 0, 170), width=1)
        tw = draw.textlength(str(n), font=font)
        draw.rectangle([x, y, x + tw + 4, y + 14], fill=(255, 0, 170))
        draw.text((x + 2, y), str(n), fill="white", font=font)
        _marks[n] = (round(el["x"] + el["width"] / 2), round(el["y"] + el["height"] / 2))
        legend.append(f"#{n} {el['role']} \"{el['name'][:40]}\"")
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue(), "\n".join(legend)


def _look(window: str = "", whole_screen: bool = False) -> list:
    if window:
        _justday("windows", "focus", window)
        time.sleep(0.25)
    info = json.loads(_justday("screenshot", *(["--all"] if whole_screen else [])))
    _map.update(origin_x=info["origin_x"], origin_y=info["origin_y"], scale=info["scale"], app=info.get("app", ""))
    data = Path(info["path"]).read_bytes()
    Path(info["path"]).unlink(missing_ok=True)
    note = (f"{info['window']} · coordinates for act = pixels of THIS image "
            f"(origin {info['origin_x']},{info['origin_y']} scale {info['scale']})")
    els = [] if whole_screen else _elements(info.get("app", ""), info["origin_x"], info["origin_y"],
                                            info.get("width", 0), info.get("height", 0))
    _marks.clear()
    if els:
        data, legend = _annotate(data, els)
        note += "\nMarked elements (prefer `click #N` — exact, no pixel guessing):\n" + legend
    return [note, Image(data=data, format="jpeg")]


def _type(text: str) -> None:
    """Type any text exactly once. KWin has no virtual-keyboard protocol (wtype fails), and kwin-mcp's clipboard
    fallback presses Ctrl+Shift+V *and* Ctrl+V plus two Enters — Chromium/Electron apps paste twice and chats send.
    Here: one paste with the right shortcut, no Enter, and the user's clipboard is restored afterwards."""
    env = server._engine._session_env()
    types = subprocess.run(["wl-paste", "--list-types"], capture_output=True, text=True, env=env, timeout=3).stdout
    saved = None
    if "text/plain" in types:
        saved = subprocess.run(["wl-paste", "--no-newline"], capture_output=True, env=env, timeout=3).stdout
    subprocess.run(["wl-copy", "--", text], env=env, timeout=3, stdin=subprocess.DEVNULL,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.12)
    terminal = _map.get("app", "").lower() in TERMINALS
    server._engine.keyboard_key("ctrl+shift+v" if terminal else "ctrl+v")
    time.sleep(0.25)
    if saved is not None:
        subprocess.Popen(["wl-copy"], stdin=subprocess.PIPE, env=env, stdout=subprocess.DEVNULL,
                         stderr=subprocess.DEVNULL).communicate(saved, timeout=3)


def _pt(x: str, y: str, screen: bool) -> tuple[int, int]:
    if x.startswith("#"):
        return _marks[int(x[1:])]
    if screen:
        return int(float(x)), int(float(y))
    return (round(_map["origin_x"] + float(x) / _map["scale"]),
            round(_map["origin_y"] + float(y) / _map["scale"]))


@server.mcp.tool()
async def look(
    window: Annotated[str, Field(description="Optional app/window name to focus first (e.g. \"discord\").")] = "",
    whole_screen: Annotated[bool, Field(description="All monitors instead of the active window.")] = False,
) -> list:
    """See the screen: returns an image of the active window (or all monitors). Use this instead of
    `screenshot`/`justday screenshot` + Read. Coordinates you pass to `act` are pixels of this image."""
    return _look(window, whole_screen)


@server.mcp.tool()
async def act(
    steps: Annotated[list[str], Field(description=(
        "Actions, executed in order. Coordinates are pixels of the last `look` image, or #N for a marked element. "
        "click X Y | click #N | double X Y | right X Y | move X Y | scroll X Y N (N<0 = up) | "
        "drag X1 Y1 X2 Y2 [X3 Y3 ...] (path, e.g. drawing) | type TEXT (any language) | "
        "key COMBO (Return, ctrl+k, alt+Tab…) | hold KEY | release KEY | wait MS | "
        "games: turn DX DY [MS] (relative mouse = camera) | press KEY MS (hold a key for MS) | mouse down|up [left|right]"))],
    look_after: Annotated[bool, Field(description="Return a fresh look after the steps (default true).")] = True,
    settle_ms: Annotated[int, Field(description="Pause before the final look.")] = 450,
    screen_coords: Annotated[bool, Field(description="Coordinates are absolute screen pixels, not image pixels.")] = False,
) -> list:
    """Do several GUI actions in ONE call (click, type, keys, drag paths, scroll, waits) and get the
    result image back. Batch everything you can predict from the current image into one call."""
    eng, log = server._engine, []
    for raw in steps:
        op, _, rest = raw.strip().partition(" ")
        op, a = op.lower(), rest.split()
        try:
            if op in ("click", "double", "right"):
                x, y = _pt(a[0], a[1] if len(a) > 1 else "", screen_coords)
                eng.mouse_click(x, y, button="right" if op == "right" else "left", double=op == "double")
            elif op == "move":
                eng.mouse_move(*_pt(a[0], a[1] if len(a) > 1 else "", screen_coords))
            elif op == "scroll":
                x, y = _pt(a[0], a[1], screen_coords)
                eng.mouse_scroll(x, y, delta=int(a[2]) if len(a) > 2 else 3)
            elif op == "drag":
                pts = [_pt(a[i], a[i + 1], screen_coords) for i in range(0, len(a) - 1, 2)]
                (x1, y1), (x2, y2) = pts[0], pts[-1]
                eng.mouse_drag(x1, y1, x2, y2, waypoints=[[x, y, 15] for x, y in pts[1:-1]] or None)
            elif op == "type":
                _type(rest)
            elif op == "key":
                eng.keyboard_key(rest.strip())
            elif op == "hold":
                eng.keyboard_key_down(rest.strip())
            elif op == "release":
                eng.keyboard_key_up(rest.strip())
            elif op == "turn":  # games: relative mouse (camera). turn DX DY [MS]
                import relmouse

                relmouse.move(float(a[0]), float(a[1]), duration=(int(a[2]) / 1000) if len(a) > 2 else 0.0)
            elif op == "press":  # press KEY MS — hold a key for a while (walk, charge a jump)
                eng.keyboard_key_down(a[0])
                time.sleep(min(10.0, int(a[1]) / 1000) if len(a) > 1 else 0.1)
                eng.keyboard_key_up(a[0])
            elif op == "mouse":  # mouse down|up [left|right] — hold a button (aim, drag in games)
                import relmouse

                relmouse.button(a[1] if len(a) > 1 else "left", a[0] == "down")
            elif op == "wait":
                time.sleep(min(10.0, int(a[0]) / 1000))
            else:
                log.append(f"{raw}: unknown action")
                continue
            log.append(f"ok {raw}")
            time.sleep(0.06)
        except Exception as e:  # report and stop: later steps depend on earlier ones
            log.append(f"FAILED {raw}: {e}")
            break
    if not look_after:
        return ["\n".join(log)]
    time.sleep(max(0, settle_ms) / 1000)
    return ["\n".join(log), *_look()]


sys.argv.append("--default-live-session")
server.main()
