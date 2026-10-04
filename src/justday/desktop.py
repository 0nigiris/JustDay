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



def qdbus_bin() -> str:
    """Имя утилиты qdbus для Plasma 6.

    В Debian/Fedora это `qdbus-qt6`, в openSUSE — `qdbus6`, иногда лежит в libexec Qt.
    Без неё backend() ошибочно падает в X11 на живом Wayland-сеансе KDE, и док не узнаёт
    ни окон, ни полного экрана.
    """
    for name in ("qdbus-qt6", "qdbus6", "qdbus"):
        if shutil.which(name):
            return name
    for cand in ("/usr/lib64/qt6/bin/qdbus", "/usr/lib/qt6/bin/qdbus"):
        if os.path.isfile(cand) and os.access(cand, os.X_OK):
            return cand
    return ""


def tray_items() -> list[dict]:
    """Apps that live in the system tray (StatusNotifierItem): Telegram and Discord usually have no window at all."""
    out: list[dict] = []
    try:
        bin = qdbus_bin()
        if not bin:
            return out
        raw = subprocess.run([bin, "org.kde.StatusNotifierWatcher", "/StatusNotifierWatcher",
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
                    [bin, service, path, "org.freedesktop.DBus.Properties.Get", "org.kde.StatusNotifierItem", name],
                    capture_output=True, text=True, timeout=5).stdout.strip()
            out.append({"service": service, "path": path, "id": prop("Id"), "title": prop("Title")})
        except (OSError, subprocess.SubprocessError):
            continue
    return out


def tray_activate(item: dict) -> bool:
    """The same as a left click on the tray icon: the app unhides its window."""
    try:
        bin = qdbus_bin()
        if not bin:
            return False
        r = subprocess.run([bin, item["service"], item["path"], "org.kde.StatusNotifierItem.Activate", "0", "0"],
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
// Значок в лотке и его окно зовутся по-разному: "TelegramDesktop" против "org.telegram.desktop".
// Поэтому для wake сравниваем имена, выкинув всё, кроме букв и цифр.
const squash = s => String(s).toLowerCase().replace(/[^a-z0-9]/g, "");
let n = 0;
for (const w of workspace.windowList()) {
  if (!w.normalWindow) continue;
  const hay = (w.resourceClass + " " + w.resourceName + " " + w.caption).toLowerCase();
  if (action === "active" && workspace.activeWindow !== w) continue;
  if (wid && String(w.internalId) !== wid) continue;
  if (q && !(action === "wake" ? squash(hay).includes(squash(q)) : hay.includes(q))) continue;
  // wake поднимает только свёрнутое. Программа, которая щелчком по значку сама спрятала окно,
  // не должна получить его обратно нашими руками — это был бы значок, который не умеет прятать.
  if (action === "wake" && !w.minimized) continue;
  n++;
  if (action === "close") w.closeWindow();
  else if (action === "focus" || action === "wake") { w.minimized = false; workspace.activeWindow = w; }
  else if (action === "minimize") w.minimized = true;
  const g = w.frameGeometry;
  console.warn(tag + JSON.stringify({id: String(w.internalId), app: w.resourceClass, title: w.caption, pid: w.pid,
                                     active: workspace.activeWindow === w, minimized: w.minimized,
                                     full: !!w.fullScreen && !w.minimized,
                                     x: Math.round(g.x), y: Math.round(g.y), w: Math.round(g.width), h: Math.round(g.height)}));
  if (action === "focus" || action === "wake") break;
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
// Debounce + skip-unchanged: frameGeometryChanged fires many times per drag/animation.
// Emitting a multi-KB journal line each time made the dock stutter and burned CPU in qs+daemon.
var _last = "";
var _timer = null;
function build() {
  const out = [];
  for (const w of workspace.windowList()) {
    if (!w.normalWindow || w.skipTaskbar) continue;
    const g = w.frameGeometry;
    let screen = "", ox = 0, oy = 0, ow = 0, oh = 0;
    try {
      const o = w.output;
      if (o) {
        screen = String(o.name || "");
        const og = o.geometry;
        ox = Math.round(og.x); oy = Math.round(og.y);
        ow = Math.round(og.width); oh = Math.round(og.height);
      }
    } catch (e) {}
    out.push({id: String(w.internalId), app: w.resourceClass, title: w.caption, pid: w.pid,
              active: workspace.activeWindow === w, minimized: !!w.minimized,
              full: !w.minimized && !!w.fullScreen,
              x: Math.round(g.x), y: Math.round(g.y), w: Math.round(g.width), h: Math.round(g.height),
              screen: screen, ox: ox, oy: oy, ow: ow, oh: oh});
  }
  return JSON.stringify(out);
}
function flush() {
  const payload = build();
  if (payload === _last) return;
  _last = payload;
  console.warn(tag + payload);
}
function armTimer() {
  if (_timer) return;
  try {
    _timer = new QTimer();
    _timer.interval = 200;
    _timer.singleShot = true;
    _timer.timeout.connect(function () { _timer = null; flush(); });
  } catch (e) {
    // Old KWin without QTimer — emit immediately (still skip-unchanged).
    _timer = null;
    flush();
    return;
  }
  _timer.start();
}
function snap() {
  // Coalesce geometry spam: one journal line ~200ms after the last event.
  if (_timer) {
    try { _timer.stop(); _timer.start(); } catch (e) { _timer = null; armTimer(); }
    return;
  }
  armTimer();
}
function snapNow() {
  if (_timer) {
    try { _timer.stop(); } catch (e) {}
    _timer = null;
  }
  flush();
}
function hook(w) {
  if (!w) return;
  try { if (w.minimizedChanged) w.minimizedChanged.connect(snap); } catch (e) {}
  try { if (w.fullScreenChanged) w.fullScreenChanged.connect(snap); } catch (e) {}
  try { if (w.maximizedChanged) w.maximizedChanged.connect(snap); } catch (e) {}
  // Borderless resize / drag to edges — without this, dock only learns on focus change.
  try { if (w.frameGeometryChanged) w.frameGeometryChanged.connect(snap); } catch (e) {}
}
workspace.windowAdded.connect(function (w) { hook(w); snap(); });
workspace.windowRemoved.connect(snap);
workspace.windowActivated.connect(snap);
for (const w of workspace.windowList()) hook(w);
snapNow();
"""


def _kwin(*args: str) -> str:
    bin = qdbus_bin()
    if not bin:
        return ""
    try:
        return subprocess.run([bin, "org.kde.KWin", *args],
                              capture_output=True, text=True, timeout=10).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def watch_start() -> bool:
    """Поселить в KWin скрипт, который сам рассказывает об окнах. Идемпотентно."""
    if backend() != "kwin":
        return False
    try:
        ensure_genie_effect()
        ensure_blur_effect()
    except Exception:
        pass
    watch_stop()
    path = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "justday-kwin-windows.js"
    try:
        path.write_text(_WATCH_JS, encoding="utf-8")
    except OSError:
        return False
    sid = _kwin("/Scripting", "org.kde.kwin.Scripting.loadScript", str(path), WATCH_NAME)
    if not sid:
        return False
    # Script.run on some KWin builds is a no-op until Scripting.start() pumps pending scripts
    # (openSUSE Tumbleweed / KWin 6: load+run alone never emits console.warn).
    _kwin(f"/Scripting/Script{sid}", "org.kde.kwin.Script.run")
    _kwin("/Scripting", "org.kde.kwin.Scripting.start")
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
        if kde and qdbus_bin():
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
        full = False
        try:
            st = subprocess.run(["xprop", "-id", wid, "_NET_WM_STATE"],
                                capture_output=True, text=True, timeout=2).stdout
            full = "_NET_WM_STATE_FULLSCREEN" in st
        except (OSError, subprocess.SubprocessError):
            pass
        out.append({"app": app, "title": title, "pid": int(pid) if pid.isdigit() else 0,
                    "active": int(wid, 16) == active, "minimized": False, "full": full,
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
    bin = qdbus_bin()
    if not bin:
        return []
    q = lambda *a: subprocess.run([bin, "org.kde.KWin", *a], capture_output=True, text=True, timeout=10).stdout.strip()  # noqa: E731
    sid = q("/Scripting", "org.kde.kwin.Scripting.loadScript", f.name, name)
    q(f"/Scripting/Script{sid}", "org.kde.kwin.Script.run")
    q("/Scripting", "org.kde.kwin.Scripting.start")
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


def layout_switch() -> None:
    """Переключить на следующую. Какая вышла — спрашивать отдельно и не сразу: плазме нужен миг."""
    _kwin_keyboard("switchToNextLayout")


def _kwin_keyboard(method: str, literal: bool = False) -> str:
    bin = qdbus_bin()
    if not bin:
        return ""
    args = [bin] + (["--literal"] if literal else []) + ["org.kde.keyboard", "/Layouts", method]
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=5).stdout
    except (OSError, subprocess.SubprocessError):
        return ""


_thumb_lock = None


def _get_thumb_lock():
    global _thumb_lock
    if _thumb_lock is None:
        import threading
        _thumb_lock = threading.Lock()
    return _thumb_lock


def capture_screen(png: str) -> None:
    """Снять весь экран в PNG. Один путь для всех: и CLI, и подсказки дока.

    Долго считалось, что снимать нечем, и Джарвис отвечал «нечем снять экран»:
      * grim хочет wlr-screencopy — KWin такого протокола не говорит;
      * `org.kde.KWin.ScreenShot2` отвечает NoAuthorized: KWin пускает туда
        только программы, у которых в .desktop стоит
        X-KDE-DBUS-Restricted-Interfaces (spectacle, plasmashell, портал);
      * spectacle пишет файл и падает в KCrash — на каждое наведение в доке
        получался coredump, поэтому его здесь не зовут даже если он на PATH.
    Выход — портал рабочего стола: ему KWin снимать разрешает, а он снимает
    молча, без диалога, за треть секунды. Разговор с ним живёт в
    portal_shot.py и идёт системным питоном: GLib стоит пакетом под него, а не
    под наш venv.
    """
    import shutil
    from pathlib import Path

    errors: list[str] = []
    tools: list[tuple[str, list[str]]] = []
    if shutil.which("grim"):
        tools.append(("grim", ["grim", png]))
    py = "/usr/bin/python3" if os.path.exists("/usr/bin/python3") else shutil.which("python3")
    if py:
        tools.append(("portal", [py, str(Path(__file__).with_name("portal_shot.py")), png]))
    # X11-style grabbers only off Wayland (maim/scrot/import are fine there).
    if not os.environ.get("WAYLAND_DISPLAY"):
        for exe, cmd in (
            ("maim", ["maim", png]),
            ("scrot", ["scrot", "-o", png]),
            ("import", ["import", "-window", "root", png]),
        ):
            if shutil.which(exe):
                tools.append((exe, cmd))
    if not tools:
        raise RuntimeError("no_safe_capture")
    for exe, cmd in tools:
        try:
            r = subprocess.run(cmd, check=False, capture_output=True, timeout=20)
            if r.returncode == 0 and Path(png).exists() and Path(png).stat().st_size > 0:
                return
            err = (r.stderr or b"").decode("utf-8", "replace").strip()[:120]
            errors.append(f"{exe}: rc={r.returncode} {err}")
        except (OSError, subprocess.SubprocessError) as e:
            errors.append(f"{exe}: {e}")
    raise RuntimeError("no_safe_capture: " + "; ".join(errors)[:200])


def window_thumb(wid: str, *, max_edge: int = 280) -> dict:
    """Crop a small JPEG of one window for dock hover previews.

    Снимаем весь экран (capture_screen) и вырезаем окно по его геометрии:
    отдельного снимка одного окна у нас нет. Свёрнутые и пропавшие — ok=False.
    Serialized: parallel hover requests must not stampede capture tools.
    """
    import shutil
    import time
    from pathlib import Path

    wid = str(wid or "")
    if not wid:
        return {"ok": False, "error": "empty id"}
    wins = windows("list")
    hit = next((w for w in wins if str(w.get("id")) == wid), None)
    if not hit:
        return {"ok": False, "error": "window gone"}
    if hit.get("minimized"):
        return {"ok": False, "error": "minimized", "minimized": True}
    ww, wh = int(hit.get("w") or 0), int(hit.get("h") or 0)
    ox, oy = int(hit.get("x") or 0), int(hit.get("y") or 0)
    if ww < 16 or wh < 16:
        return {"ok": False, "error": "tiny geometry"}

    cache = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "justday-thumbs"
    cache.mkdir(parents=True, exist_ok=True)
    safe = "".join(c if c.isalnum() else "_" for c in wid)[:80]
    out = cache / f"{safe}.jpg"
    # Reuse a fresh-enough cache (4s) so hovering along the tip does not re-shoot.
    try:
        if out.exists() and time.time() - out.stat().st_mtime < 4.0 and out.stat().st_size > 400:
            return {"ok": True, "path": str(out), "id": wid, "cached": True}
    except OSError:
        pass

    png = str(cache / f"{safe}-full.png")
    with _get_thumb_lock():
        # Re-check cache inside the lock (another request may have just finished).
        try:
            if out.exists() and time.time() - out.stat().st_mtime < 4.0 and out.stat().st_size > 400:
                return {"ok": True, "path": str(out), "id": wid, "cached": True}
        except OSError:
            pass
        try:
            capture_screen(png)
        except Exception as e:
            err = str(e)[:200]
            permanent = "no_safe_capture" in err
            return {"ok": False, "error": err, "permanent": permanent}
        if not shutil.which("magick"):
            return {"ok": False, "error": "magick missing"}
        try:
            # Clamp crop to image bounds; multi-monitor: geometry is already absolute.
            subprocess.run(
                ["magick", png, "-crop", f"{ww}x{wh}+{max(0, ox)}+{max(0, oy)}", "+repage",
                 "-resize", f"{int(max_edge)}x{int(max_edge)}>", "-quality", "80", str(out)],
                check=True, timeout=12, capture_output=True)
        except (OSError, subprocess.SubprocessError) as e:
            return {"ok": False, "error": str(e)[:200]}
        try:
            Path(png).unlink(missing_ok=True)
        except OSError:
            pass
        if not out.exists() or out.stat().st_size < 200:
            return {"ok": False, "error": "empty thumb"}
        return {"ok": True, "path": str(out), "id": wid, "cached": False}


_last_icons_json = ""
_last_icons_reconfigure = 0.0
_last_icons_applied = ""     # карта, которую эффект уже получил: повторять её ему незачем


def publish_dock_icons(icons: dict, replace: bool = True, reconfigure: bool | None = None) -> dict:
    """Write dock icon screen rects for the JustDay genie KWin effect.

    replace=True (default): the dock's full map replaces the file.
    replace=False: merge a partial patch into the existing map.

    Writing kwinrc + reconfigureEffect on every hover/magnify tick made Plasma hitch
    and briefly blanked dock icons. We always update the JSON file; kwinrc is updated
    only when the payload changes, and reconfigureEffect is debounced (~1.2s) unless
    reconfigure=True (e.g. right before a genie minimize).
    """
    import json
    import time
    from pathlib import Path

    global _last_icons_json, _last_icons_reconfigure, _last_icons_applied

    path = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "justday-dock-icons.json"
    merged: dict = {}
    if not replace:
        try:
            if path.exists():
                prev = json.loads(path.read_text(encoding="utf-8"))
                if isinstance(prev, dict):
                    merged.update(prev)
        except (OSError, ValueError):
            pass
    if isinstance(icons, dict):
        merged.update(icons)
    try:
        path.write_text(json.dumps(merged, ensure_ascii=False), encoding="utf-8")
        icons = merged
    except OSError as e:
        return {"ok": False, "error": str(e)}
    try:
        raw = json.dumps(icons or {}, ensure_ascii=False, separators=(",", ":"))
        if len(raw) >= 12000 or not shutil.which("kwriteconfig6"):
            return {"ok": True, "path": str(path), "n": len(icons or {})}
        if raw == _last_icons_json and reconfigure is not True:
            return {"ok": True, "path": str(path), "n": len(icons or {}), "skipped": True}
        # Эффект уже знает ровно эту карту — повторять ему то же самое нечего, даже когда просят
        # «наверняка». Раньше каждое сворачивание значком писало kwinrc и дёргало KWin по dbus, и
        # оба вызова стояли в очереди перед самим сворачиванием: окно уезжало с задержкой, а при
        # быстрых нажатиях задержки складывались и док переставал поспевать за рукой.
        if raw == _last_icons_applied:
            return {"ok": True, "path": str(path), "n": len(icons or {}), "skipped": True}
        _last_icons_json = raw
        subprocess.run(
            ["kwriteconfig6", "--file", "kwinrc", "--group", "Effect-justday_genie",
             "--key", "IconsJson", raw],
            timeout=5, check=False, capture_output=True)
        now = time.monotonic()
        force = reconfigure is True
        if force or (reconfigure is not False and now - _last_icons_reconfigure >= 1.2):
            if qdbus_bin():
                _kwin("/Effects", "org.kde.kwin.Effects.reconfigureEffect", "justday_genie")
            _last_icons_reconfigure = now
            _last_icons_applied = raw
    except (OSError, subprocess.SubprocessError, ValueError):
        pass
    return {"ok": True, "path": str(path), "n": len(icons or {})}



def ensure_blur_effect() -> dict:
    """Enable a KWin blur effect so Quickshell BackgroundEffect can frost dock/tray.

    Prefers better_blur_dx (force-blur / BackgroundEffect protocol) when installed;
    falls back to stock blur. Stock blur stays off when better_blur is available
    (they conflict). Idempotent — only writes/loads when not already active.
    """
    import shutil

    if not shutil.which("kwriteconfig6") and not shutil.which("kwriteconfig5"):
        return {"ok": False, "error": "no kwriteconfig"}
    kw = shutil.which("kwriteconfig6") or shutil.which("kwriteconfig5")
    prefer = "better_blur_dx"
    stock = "blur"
    chosen = None
    try:
        # Probe which plugins KWin knows.
        listed = ""
        if backend() == "kwin" and qdbus_bin():
            listed = _kwin("/Effects", "org.kde.kwin.Effects.listOfEffects") or ""
        has_better = prefer in listed.replace(",", " ").split() if listed else True
        # If list failed, still try better first then stock.
        for name, enable_key, disable_other in (
            (prefer, "better_blur_dxEnabled", "blurEnabled") if has_better else (None, None, None),
            (stock, "blurEnabled", "better_blur_dxEnabled"),
        ):
            if not name:
                continue
            subprocess.run([kw, "--file", "kwinrc", "--group", "Plugins",
                            "--key", enable_key, "true"], timeout=5, check=False, capture_output=True)
            if disable_other:
                subprocess.run([kw, "--file", "kwinrc", "--group", "Plugins",
                                "--key", disable_other, "false"], timeout=5, check=False, capture_output=True)
            if backend() == "kwin" and qdbus_bin():
                loaded_list = _kwin("/Effects", "org.kde.kwin.Effects.loadedEffects") or ""
                if name in loaded_list.replace(",", " ").split():
                    chosen = name
                    break
                # Load it.
                if name == prefer:
                    _kwin("/Effects", "org.kde.kwin.Effects.unloadEffect", stock)
                loaded = _kwin("/Effects", "org.kde.kwin.Effects.loadEffect", name)
                if str(loaded).lower() in ("true", "1", ""):
                    chosen = name
                    break
            else:
                chosen = name
                break
        if chosen:
            return {"ok": True, "effect": chosen}
        return {"ok": False, "error": "no blur effect loaded"}
    except (OSError, subprocess.SubprocessError) as e:
        return {"ok": False, "error": str(e)}


def ensure_genie_effect() -> dict:
    """Install/enable the JustDay genie minimize effect (squash-compatible exclusive group).

    Idempotent: skip copy+reload when installed sources already match. Reloading the
    effect on every window-watch start briefly blanked Plasma/dock chrome.
    """
    import filecmp
    import shutil
    from pathlib import Path

    src = Path(__file__).resolve().parents[2] / "island" / "kwin-effects" / "justday_genie"
    dst = Path.home() / ".local/share/kwin/effects/justday_genie"
    if not src.is_dir():
        return {"ok": False, "error": "effect sources missing"}
    need_install = True
    try:
        dst.parent.mkdir(parents=True, exist_ok=True)
        marker = "contents/code/main.js"
        if (dst.is_dir() and (dst / marker).is_file() and (src / marker).is_file()
                and filecmp.cmp(src / marker, dst / marker, shallow=False)):
            need_install = False
        if need_install:
            if dst.exists():
                shutil.rmtree(dst)
            shutil.copytree(src, dst)
    except OSError as e:
        return {"ok": False, "error": str(e)}
    # Prefer our genie over stock squash (same exclusive minimize group).
    try:
        if shutil.which("kwriteconfig6"):
            subprocess.run(["kwriteconfig6", "--file", "kwinrc", "--group", "Plugins",
                            "--key", "justday_genieEnabled", "true"], timeout=5, check=False)
            subprocess.run(["kwriteconfig6", "--file", "kwinrc", "--group", "Plugins",
                            "--key", "squashEnabled", "false"], timeout=5, check=False)
        if backend() == "kwin" and qdbus_bin():
            # Only unload/load when we actually replaced files — otherwise Plasma flickers.
            if need_install:
                _kwin("/Effects", "org.kde.kwin.Effects.unloadEffect", "squash")
                loaded = _kwin("/Effects", "org.kde.kwin.Effects.loadEffect", "justday_genie")
                return {"ok": True, "loaded": loaded.lower() in ("true", "1", ""), "installed": True}
            return {"ok": True, "loaded": True, "installed": False}
    except (OSError, subprocess.SubprocessError):
        pass
    return {"ok": True, "loaded": False, "installed": need_install}
