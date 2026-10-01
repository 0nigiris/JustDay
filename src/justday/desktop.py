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
                # Чем ловить открытое окно: вейланд называет его appId, и это почти всегда либо
                # StartupWMClass, либо идентификатор файла. Без этого док не знает, что запущенное
                # окно — та самая закреплённая программа, и рисует её вторым значком.
                "wmclass": e.get("StartupWMClass", ""),
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


def launch_app_id(desktop_id: str, files: list[str] | None = None) -> None:
    """Запустить программу, при желании отдав ей файлы.

    gtk-launch принимает пути следом за именем — и это правильный путь: он читает .desktop и
    подставляет файлы туда, куда программа просила (%f, %U), вместо того чтобы угадывать за неё.
    """
    args = ["gtk-launch", desktop_id, *[str(f) for f in (files or []) if str(f).strip()]]
    subprocess.Popen(detached(args), start_new_session=True,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=str(HOME))


def launch_app(query: str) -> dict:
    """Открыть программу по имени. Спрятавшуюся в лоток — вернуть, а не запускать заново.

    Телеграм и дискорд при закрытии окна прячутся в лоток и остаются работать. Повторный запуск им
    ничего не делает: они видят, что уже запущены, и молчат, — а со стороны это выглядит сломанной
    командой. Возвращает окно щелчок по значку в лотке, и его-то мы и делаем первым.
    """
    hits = find_apps(query, 1)
    if not hits:
        raise RuntimeError(f"no application matching '{query}'")
    flat = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())  # noqa: E731
    parts = [p for p in hits[0]["id"].split(".") if p.lower() not in ("org", "com", "io", "net", "desktop", "app")]
    keys = [k for k in (*map(flat, parts), flat(hits[0].get("name", ""))) if len(k) > 3]
    for item in tray_items():
        hay = flat(item["id"]) + " " + flat(item["title"])
        if any(k in hay for k in keys) and tray_activate(item):
            return hits[0]
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
const q = %(query)s, action = %(action)s, tag = %(tag)s, wid = %(wid)s;
let n = 0;
for (const w of workspace.windowList()) {
  if (!w.normalWindow) continue;
  const hay = (w.resourceClass + " " + w.resourceName + " " + w.caption).toLowerCase();
  if (action === "active" && workspace.activeWindow !== w) continue;
  if (wid && String(w.internalId) !== wid) continue;
  if (q && !hay.includes(q)) continue;
  n++;
  if (action === "close") w.closeWindow();
  else if (action === "focus") { w.minimized = false; workspace.activeWindow = w; }
  else if (action === "minimize") w.minimized = true;
  const g = w.frameGeometry;
  console.warn(tag + JSON.stringify({id: String(w.internalId), app: w.resourceClass, title: w.caption, pid: w.pid,
                                     active: workspace.activeWindow === w, minimized: w.minimized,
                                     x: Math.round(g.x), y: Math.round(g.y), w: Math.round(g.width), h: Math.round(g.height)}));
  if (action === "focus") break;
}
console.warn(tag + "END " + n);
"""


# Живой список окон. KWin не отдаёт его обычным клиентам вовсе: ни wlr-foreign-toplevel, ни
# org_kde_plasma_window_management в реестре вейланда нет — их видит только плазма. Поэтому список
# берётся у самого KWin, но не опросом: постоянный скрипт сидит внутри него, просыпается на событиях
# окон и пишет строку в журнал. Опрос раз в секунду стоил бы десятой доли ядра круглые сутки — ровно
# того, что мы только что убрали из памяти.
WATCH_TAG = "JustDayDOCK "
WATCH_NAME = "justday-windows"
_WATCH_JS = """
const tag = "JustDayDOCK ";
function snap() {
  const out = [];
  for (const w of workspace.windowList()) {
    if (!w.normalWindow || w.skipTaskbar) continue;
    out.push({id: String(w.internalId), app: w.resourceClass, title: w.caption, pid: w.pid,
              active: workspace.activeWindow === w, minimized: w.minimized,
              full: !!w.fullScreen && !w.minimized});
  }
  console.warn(tag + JSON.stringify(out));
}
function hook(w) {
  if (!w) return;
  if (w.minimizedChanged) w.minimizedChanged.connect(snap);
  // Игра вошла в полный экран — док обязан уйти с дороги, и узнать об этом надо сразу, а не
  // когда в следующий раз кто-нибудь откроет окно.
  if (w.fullScreenChanged) w.fullScreenChanged.connect(snap);
}
workspace.windowAdded.connect(function (w) { hook(w); snap(); });
workspace.windowRemoved.connect(snap);
workspace.windowActivated.connect(snap);
for (const w of workspace.windowList()) hook(w);
snap();
"""


def _kwin(*args: str) -> str:
    try:
        return subprocess.run(["qdbus-qt6", "org.kde.KWin", *args],
                              capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def watch_start() -> bool:
    """Поселить в KWin скрипт, который сам рассказывает об окнах. Идемпотентно."""
    if backend() != "kwin":
        return False
    watch_stop()
    path = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "justday-kwin-windows.js"
    try:
        path.write_text(_WATCH_JS, encoding="utf-8")
    except OSError:
        return False
    sid = _kwin("/Scripting", "org.kde.kwin.Scripting.loadScript", str(path), WATCH_NAME)
    if not sid:
        return False
    _kwin(f"/Scripting/Script{sid}", "org.kde.kwin.Script.run")
    return True


def watch_stop() -> None:
    if backend() == "kwin":
        _kwin("/Scripting", "org.kde.kwin.Scripting.unloadScript", WATCH_NAME)


def backend() -> str:
    """Чем управлять окнами: "kwin" (скрипты KWin 6), "x11" (wmctrl/xdotool) или "" — нечем.

    Одна проверка на всё: на Plasma 6 работает родной путь, на X11 и Plasma 5 — стандартные
    утилиты иксов, и тогда «закрой дискорд», сцены и «я ушёл» тоже работают."""
    global _BACKEND
    if _BACKEND is None:
        kde = "KDE" in os.environ.get("XDG_CURRENT_DESKTOP", "")
        if kde and shutil.which("qdbus-qt6"):
            _BACKEND = "kwin"
        elif os.environ.get("DISPLAY") and shutil.which("wmctrl"):
            _BACKEND = "x11"
        else:
            _BACKEND = ""
    return _BACKEND


_BACKEND: str | None = None


def pointer(x: int, y: int, button: int = 1, double: bool = False) -> dict:
    """Щёлкнуть в точке экрана — там, где это в принципе возможно.

    На X11 щелчок делает `xdotool`: ассистент умеет нажимать кнопки в чужих окнах и без KWin,
    лишь бы знал координаты (их даёт `justday screenshot` активного окна). На Wayland синтетические
    события запрещены самим протоколом: там щелчки идут только через композитор, то есть через
    kwin-mcp на KWin 6.

    Решает тип сеанса, а не рабочий стол: KDE бывает и на X11, и там backend() отвечает «kwin»
    (скрипты KWin работают и в иксах) — а вот щёлкать надо всё равно через xdotool."""
    from . import face

    if face.session() == "x11" and shutil.which("xdotool"):
        cmd = ["xdotool", "mousemove", "--sync", str(int(x)), str(int(y)), "click"]
        if double:
            cmd += ["--repeat", "2", "--delay", "80"]
        cmd.append(str(int(button)))
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
        return {"ok": p.returncode == 0, "x": int(x), "y": int(y), "button": int(button),
                "double": double, "how": "xdotool", "error": (p.stderr or "").strip()[:200]}
    if backend() == "kwin":
        return {"ok": False, "error": "на Wayland щелчки идут через kwin-mcp: инструменты look/act, "
                                      "а не эта команда"}
    return {"ok": False, "error": "щёлкать нечем: нужен xdotool на X11 или KWin 6 на Wayland"}


def keys(combo: str) -> dict:
    """Нажать сочетание клавиш: «ctrl+s», «Return», «alt+Tab». X11 — xdotool, иначе нечем.

    Как и щелчок, решается типом сеанса: KDE на X11 — это иксы, чем бы ни управлялись окна."""
    from . import face

    if face.session() == "x11" and shutil.which("xdotool"):
        p = subprocess.run(["xdotool", "key", "--clearmodifiers", combo], capture_output=True, text=True, timeout=10)
        return {"ok": p.returncode == 0, "keys": combo, "how": "xdotool", "error": (p.stderr or "").strip()[:200]}
    if backend() == "kwin":
        return {"ok": False, "error": "на Wayland нажатия идут через kwin-mcp (инструмент act)"}
    return {"ok": False, "error": "нажимать нечем: нужен xdotool на X11 или KWin 6 на Wayland"}


def _x11_active_id() -> int:
    """Какое окно сейчас активно (_NET_ACTIVE_WINDOW)."""
    try:
        out = subprocess.run(["xprop", "-root", "_NET_ACTIVE_WINDOW"], capture_output=True, text=True, timeout=3).stdout
        m = re.search(r"(0x[0-9a-fA-F]+)", out)
        return int(m.group(1), 16) if m else 0
    except (OSError, subprocess.SubprocessError, ValueError):
        return 0


def _x11_windows(action: str, query: str) -> list[dict]:
    """То же, что KWin-путь, но через wmctrl: список, фокус, закрытие, сворачивание."""
    try:
        raw = subprocess.run(["wmctrl", "-l", "-x", "-p", "-G"], capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return []
    active = _x11_active_id()
    out: list[dict] = []
    for line in raw.splitlines():
        parts = line.split(None, 9)
        if len(parts) < 10:
            continue
        wid, desk, pid, x, y, w, h, cls, _host, title = parts
        if desk == "-1":          # панели, док, рабочий стол — не окна программ
            continue
        app = cls.split(".")[-1] or cls
        if action == "active" and int(wid, 16) != active:
            continue
        if query and query.lower() not in f"{cls} {title}".lower():
            continue
        if action == "close":
            subprocess.run(["wmctrl", "-i", "-c", wid], timeout=5, check=False)
        elif action == "focus":
            subprocess.run(["wmctrl", "-i", "-a", wid], timeout=5, check=False)
        elif action == "minimize" and shutil.which("xdotool"):
            subprocess.run(["xdotool", "windowminimize", wid], timeout=5, check=False)
        out.append({"app": app, "title": title, "pid": int(pid) if pid.isdigit() else 0,
                    "active": int(wid, 16) == active, "minimized": False,
                    "x": int(x), "y": int(y), "w": int(w), "h": int(h)})
        if action == "focus":
            break
    return out


def windows(action: str = "list", query: str = "", wid: str = "") -> list[dict]:
    """List/focus/close/minimize top-level windows through a throw-away KWin script.

    close = the same as clicking the window's close button (apps can save / ask), unlike pkill.
    Вне KWin 6 то же самое делается утилитами иксов (wmctrl/xdotool)."""
    import tempfile
    import uuid

    if backend() != "kwin":
        return _x11_windows(action, query) if backend() == "x11" else []

    tag = f"JustDayWIN{uuid.uuid4().hex[:8]} "
    js = _KWIN_JS % {"query": json.dumps(query.lower()), "action": json.dumps(action), "tag": json.dumps(tag),
                     "wid": json.dumps(wid)}
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


# ───────────── раскладка клавиатуры ─────────────
#
# Плазма держит её на шине: org.kde.keyboard /Layouts. Спрашивать её опросом было бы расточительно
# — у неё есть сигнал layoutChanged, по которому демон и узнаёт о смене.
def layout_now() -> dict:
    """Какая раскладка сейчас и какие есть. Пусто — плазмы нет или она ещё не ответила."""
    if backend() != "kwin":
        return {}
    raw = _kwin_keyboard("getLayoutsList", literal=True)
    names: list[dict] = []
    for short, variant, full in re.findall(r'\(sss\) "([^"]*)", "([^"]*)", "([^"]*)"', raw):
        names.append({"id": short, "variant": variant, "name": full})
    if not names:
        return {}
    try:
        at = int(_kwin_keyboard("getLayout").strip() or 0)
    except ValueError:
        at = 0
    at = max(0, min(len(names) - 1, at))
    return {"at": at, "id": names[at]["id"], "name": names[at]["name"], "all": names}


def layout_next() -> dict:
    """Переключить на следующую. Возвращает уже новую — чтобы не гадать, что получилось."""
    _kwin_keyboard("switchToNextLayout")
    return layout_now()


def _kwin_keyboard(method: str, literal: bool = False) -> str:
    args = ["qdbus-qt6"] + (["--literal"] if literal else []) + ["org.kde.keyboard", "/Layouts", method]
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return ""
