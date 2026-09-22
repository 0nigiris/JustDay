"""Small read-mostly helpers that turn fuzzy names into things the desktop already knows how to launch.

Launching itself is delegated to standard tools: gtk-launch (desktop entries), steam:// URLs.
"""
from __future__ import annotations

import configparser
import difflib
import json
import os
import re
import shutil
import sqlite3
import subprocess
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import unquote, urlparse

HOME = Path.home()


# ---------------- applications ----------------
def _app_dirs() -> list[Path]:
    dirs = [HOME / ".local/share", HOME / ".local/share/flatpak/exports/share", Path("/var/lib/flatpak/exports/share")]
    dirs += [Path(d) for d in os.environ.get("XDG_DATA_DIRS", "/usr/local/share:/usr/share").split(":")]
    seen, out = set(), []
    for d in dirs:
        p = d / "applications"
        if p.is_dir() and p not in seen:
            seen.add(p)
            out.append(p)
    return out


_apps_cache: tuple[float, list[dict]] = (0.0, [])


def list_apps() -> list[dict]:
    global _apps_cache
    if time.monotonic() - _apps_cache[0] < 30:
        return _apps_cache[1]
    apps: dict[str, dict] = {}
    for d in _app_dirs():
        for f in d.rglob("*.desktop"):
            desktop_id = str(f.relative_to(d)).replace("/", "-")
            if desktop_id in apps:  # earlier dirs (user) override system ones
                continue
            cp = configparser.RawConfigParser(strict=False, interpolation=None)
            try:
                cp.read(f, encoding="utf-8")
                e = cp["Desktop Entry"]
            except Exception:
                continue
            if e.get("Type") != "Application" or e.get("NoDisplay", "").lower() == "true" or e.get("Hidden", "").lower() == "true":
                continue
            apps[desktop_id] = {
                "id": desktop_id.removesuffix(".desktop"), "name": e.get("Name", ""), "name_ru": e.get("Name[ru]", ""),
                "generic": e.get("GenericName[ru]") or e.get("GenericName", ""), "exec": e.get("Exec", ""),
                "keywords": e.get("Keywords[ru]", "") + ";" + e.get("Keywords", ""), "path": str(f),
                "categories": e.get("Categories", ""), "icon": e.get("Icon", ""),
            }
    _apps_cache = (time.monotonic(), list(apps.values()))
    return _apps_cache[1]


def find_apps(query: str, limit: int = 5) -> list[dict]:
    q = query.lower().strip()
    scored = []
    for a in list_apps():
        fields = [a["name"], a["name_ru"], a["id"], a["generic"], *a["keywords"].split(";")]
        fields = [f.lower() for f in fields if f]
        best = max((difflib.SequenceMatcher(None, q, f).ratio() for f in fields), default=0) * 0.9
        if any(q in f for f in fields):
            best = max(best, 0.8)
        if q in (a["name"].lower(), a["name_ru"].lower(), a["id"].lower()):
            best = 1.0
        scored.append((best, a))
    scored.sort(key=lambda x: -x[0])
    return [dict(a, score=round(s, 2)) for s, a in scored[:limit] if s > 0.45]


def detached(cmd: list[str]) -> list[str]:
    """Run a program in its own systemd scope, like the app launcher does — not inside justday.service,
    so restarting the assistant never takes the user's game or editor down with it."""
    if shutil.which("systemd-run"):
        return ["systemd-run", "--user", "--scope", "--collect", "--quiet", "--slice=app.slice", "--", *cmd]
    return cmd


def tray_items() -> list[dict]:
    """Apps that live in the system tray (StatusNotifierItem): Telegram and Discord usually have no window at all."""
    out: list[dict] = []
    try:
        raw = subprocess.run(["qdbus-qt6", "org.kde.StatusNotifierWatcher", "/StatusNotifierWatcher",
                              "org.kde.StatusNotifierWatcher.RegisteredStatusNotifierItems"],
                             capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return out
    for line in raw.splitlines():
        service, _, path = line.strip().partition("/")
        if not service or not path:
            continue
        path = "/" + path
        try:
            def prop(name: str, service: str = service, path: str = path) -> str:
                return subprocess.run(
                    ["qdbus-qt6", service, path, "org.freedesktop.DBus.Properties.Get", "org.kde.StatusNotifierItem", name],
                    capture_output=True, text=True, timeout=5).stdout.strip()
            out.append({"service": service, "path": path, "id": prop("Id"), "title": prop("Title")})
        except (OSError, subprocess.SubprocessError):
            continue
    return out


def tray_activate(item: dict) -> bool:
    """The same as a left click on the tray icon: the app unhides its window."""
    try:
        r = subprocess.run(["qdbus-qt6", item["service"], item["path"], "org.kde.StatusNotifierItem.Activate", "0", "0"],
                           capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return False
    return r.returncode == 0


def launch_app_id(desktop_id: str) -> None:
    subprocess.Popen(detached(["gtk-launch", desktop_id]), start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=str(HOME))


def launch_app(query: str) -> dict:
    hits = find_apps(query, 1)
    if not hits:
        raise RuntimeError(f"no application matching '{query}'")
    launch_app_id(hits[0]["id"])
    return hits[0]


# ---------------- games ----------------
def _vdf_values(text: str, key: str) -> list[str]:
    return re.findall(rf'"{key}"\s+"([^"]*)"', text)


def list_games() -> list[dict]:
    games: dict[str, dict] = {}
    roots = [HOME / ".local/share/Steam", HOME / ".steam/steam", HOME / ".var/app/com.valvesoftware.Steam/.local/share/Steam"]
    libs: set[Path] = set()
    for r in roots:
        vdf = r / "steamapps/libraryfolders.vdf"
        if vdf.exists():
            libs.add(r.resolve())
            libs.update(Path(p) for p in _vdf_values(vdf.read_text(errors="ignore"), "path"))
    flatpak_root = (HOME / ".var/app/com.valvesoftware.Steam").resolve()
    for lib in libs:
        for m in (lib / "steamapps").glob("appmanifest_*.acf"):
            t = m.read_text(errors="ignore")
            appid, name = (_vdf_values(t, "appid") or [""])[0], (_vdf_values(t, "name") or [""])[0]
            if not appid or re.search(r"Proton|Steam Linux Runtime|Steamworks Common|Redistributable", name):
                continue
            games[f"steam:{appid}"] = {"source": "steam-flatpak" if str(lib).startswith(str(flatpak_root)) else "steam",
                                       "id": appid, "name": name}
    for cfg in (HOME / ".config/heroic", HOME / ".var/app/com.heroicgameslauncher.hgl/config/heroic"):
        for f in list(cfg.glob("legendaryConfig/legendary/installed.json")) + list(cfg.glob("gog_store/installed.json")):
            try:
                data = json.loads(f.read_text())
            except Exception:
                continue
            items = data.values() if isinstance(data, dict) else data.get("installed", [])
            for g in items:
                gid = g.get("app_name") or g.get("appName")
                if gid:
                    games[f"heroic:{gid}"] = {"source": "heroic", "id": gid, "name": g.get("title") or gid}
    for app in list_apps():  # hand-made shortcuts (~/Games/*/run.sh, AppImages, launcher scripts …)
        if ("Game" in app["categories"].split(";") or "/Games/" in app["exec"]) and not any(g["name"].lower() == app["name"].lower() for g in games.values()):
            games[f"desktop:{app['id']}"] = {"source": "desktop", "id": app["id"], "name": app["name"]}
    return sorted(games.values(), key=lambda g: g["name"].lower())


_RUNTIME = re.compile(r"^(Proton|Steam.?Linux.?Runtime|Steamworks|SteamVR)", re.I)
_WINE = {"wine", "wine64", "wine-preloader", "wine64-preloader", "gamescope"}
_running_cache: tuple[float, str] = (0.0, "")


def running_game() -> str:
    """The name of the game being played right now, or "" — one pass over /proc, cached for a few seconds.

    Steam starts every game through `reaper SteamLaunch AppId=…`; Heroic and Lutris go through wine.
    Only the game's own process matches, never the launcher sitting in the tray."""
    global _running_cache
    if time.monotonic() - _running_cache[0] < 5:
        return _running_cache[1]
    name = ""
    for proc in Path("/proc").iterdir():
        if not proc.name.isdigit():
            continue
        try:
            argv = proc.joinpath("cmdline").read_bytes().decode("utf-8", "replace").split("\0")
        except OSError:
            continue
        exe = argv[0]
        appid = next((a.removeprefix("SteamLaunch AppId=") for a in argv[1:3] if a.startswith("SteamLaunch AppId=")), "")
        if appid:
            name = next((g["name"] for g in list_games() if g["id"] == appid), f"Steam {appid}")
            break
        if (m := re.search(r"steamapps/common/([^/]+)/", exe)) and not _RUNTIME.match(m.group(1)):
            name = m.group(1)
        elif not name and os.path.basename(exe) in _WINE:
            name = "Windows game"
    _running_cache = (time.monotonic(), name)
    return name


def launch_game(query: str) -> dict:
    games = list_games()
    names = {g["name"].lower(): g for g in games}
    match = next((g for n, g in names.items() if query.lower() in n), None)
    if not match:
        close = difflib.get_close_matches(query.lower(), list(names), n=1, cutoff=0.4)
        match = names[close[0]] if close else None
    if not match:
        raise RuntimeError(f"no installed game matching '{query}'")
    if match["source"] == "steam":
        cmd = ["steam", f"steam://rungameid/{match['id']}"]
    elif match["source"] == "steam-flatpak":
        cmd = ["flatpak", "run", "com.valvesoftware.Steam", f"steam://rungameid/{match['id']}"]
    elif match["source"] == "desktop":
        cmd = ["gtk-launch", match["id"]]
    else:
        cmd = ["xdg-open", f"heroic://launch/{match['id']}"]
    subprocess.Popen(detached(cmd), start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return {**match, "command": " ".join(cmd)}


# ---------------- recent activity ----------------
def recent(hours: float = 48, limit: int = 40) -> dict:
    since = time.time() - hours * 3600
    files: dict[str, dict] = {}
    db = HOME / ".local/share/kactivitymanagerd/resources/database"
    if db.exists():
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True, timeout=2)
            for agent, res, ts in con.execute(
                "SELECT initiatingAgent, targettedResource, lastUpdate FROM ResourceScoreCache "
                "WHERE lastUpdate > ? ORDER BY lastUpdate DESC LIMIT 400", (since,)):
                key = res.removeprefix("file://")
                files.setdefault(key, {"path": key, "app": agent, "ts": ts})
        except sqlite3.Error:
            pass
    xbel = HOME / ".local/share/recently-used.xbel"
    if xbel.exists():
        try:
            for b in ET.parse(xbel).getroot().iter("bookmark"):
                mod = b.get("modified") or b.get("visited") or ""
                ts = time.mktime(time.strptime(mod[:19], "%Y-%m-%dT%H:%M:%S")) if mod else 0
                if ts > since:
                    path = unquote(urlparse(b.get("href", "")).path)
                    files.setdefault(path, {"path": path, "app": "", "ts": ts})
        except Exception:
            pass
    projects = []
    for proj in (HOME / ".claude/projects").glob("*"):
        sessions = sorted(proj.glob("*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        if sessions and sessions[0].stat().st_mtime > since:
            cwd = ""
            with sessions[0].open(encoding="utf-8") as fh:
                for line in fh:
                    m = re.search(r'"cwd":"([^"]+)"', line)
                    if m:
                        cwd = m.group(1)
                        break
            projects.append({"cwd": cwd, "last_session": sessions[0].stem, "ts": sessions[0].stat().st_mtime})
    fmt = lambda ts: time.strftime("%Y-%m-%d %H:%M", time.localtime(ts))  # noqa: E731
    items = sorted(files.values(), key=lambda x: -x["ts"])[:limit]
    return {
        "files": [{**f, "ts": fmt(f["ts"])} for f in items if not f["path"].startswith("applications:")],
        "apps": [{"app": f["path"].removeprefix("applications:").removesuffix(".desktop"), "ts": fmt(f["ts"])}
                 for f in items if f["path"].startswith("applications:")],
        "claude_projects": [{**p, "ts": fmt(p["ts"])} for p in sorted(projects, key=lambda x: -x["ts"])],
    }


# ---------------- windows (KWin scripting) ----------------
_KWIN_JS = """
const q = %(query)s, action = %(action)s, tag = %(tag)s;
let n = 0;
for (const w of workspace.windowList()) {
  if (!w.normalWindow) continue;
  const hay = (w.resourceClass + " " + w.resourceName + " " + w.caption).toLowerCase();
  if (action === "active" && workspace.activeWindow !== w) continue;
  if (q && !hay.includes(q)) continue;
  n++;
  if (action === "close") w.closeWindow();
  else if (action === "focus") { w.minimized = false; workspace.activeWindow = w; }
  else if (action === "minimize") w.minimized = true;
  const g = w.frameGeometry;
  console.warn(tag + JSON.stringify({app: w.resourceClass, title: w.caption, pid: w.pid,
                                     active: workspace.activeWindow === w, minimized: w.minimized,
                                     x: Math.round(g.x), y: Math.round(g.y), w: Math.round(g.width), h: Math.round(g.height)}));
  if (action === "focus") break;
}
console.warn(tag + "END " + n);
"""


def windows(action: str = "list", query: str = "") -> list[dict]:
    """List/focus/close/minimize top-level windows through a throw-away KWin script.

    close = the same as clicking the window's close button (apps can save / ask), unlike pkill."""
    import tempfile
    import uuid

    tag = f"JustDayWIN{uuid.uuid4().hex[:8]} "
    js = _KWIN_JS % {"query": json.dumps(query.lower()), "action": json.dumps(action), "tag": json.dumps(tag)}
    with tempfile.NamedTemporaryFile("w", suffix=".js", delete=False) as f:
        f.write(js)
    name = tag.strip()
    since = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(time.time() - 1))
    q = lambda *a: subprocess.run(["qdbus-qt6", "org.kde.KWin", *a], capture_output=True, text=True, timeout=10).stdout.strip()  # noqa: E731
    sid = q("/Scripting", "org.kde.kwin.Scripting.loadScript", f.name, name)
    q(f"/Scripting/Script{sid}", "org.kde.kwin.Script.run")
    out: list[dict] = []
    for _ in range(20):
        time.sleep(0.1)
        log_ = subprocess.run(["journalctl", "--since", since, "--no-pager", "-o", "cat", "-g", tag.strip()],
                              capture_output=True, text=True, timeout=10).stdout
        if f"{tag}END" in log_:
            out = [json.loads(line.split(tag, 1)[1]) for line in log_.splitlines()
                   if tag in line and not line.split(tag, 1)[1].startswith("END")]
            break
    q("/Scripting", "org.kde.kwin.Scripting.unloadScript", name)
    os.unlink(f.name)
    return out
