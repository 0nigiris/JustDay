"""Док: полоса программ у края экрана — то же, что у макоси снизу.

Зачем он вообще нужен рядом с меню приложений. Меню — это «найти что-нибудь»; док — «то, чем я
пользуюсь всегда», и его ценность в том, что до него не надо ничего нажимать. Поэтому в доке нет
поиска и нет разделов: только закреплённое, только открытое и один значок, из которого достаётся
меню.

Здесь лежит то, чего QML не знает сам: какие программы установлены, как их зовут по-русски и чем
ловить открытое окно. Окна док берёт у вейланда напрямую (ToplevelManager), а сопоставление
«appId окна → программа» делает по таблице match, которую собирает эта половина.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess

from . import config, desktop, kde, launcher

PIN_FILE = config.STATE_DIR / "dock.json"
CATALOG_FILE = config.STATE_DIR / "dock-catalog.json"
PIN_MAX = 32

# Чем док заполняется в первый запуск. Пустой док — это не «чистый лист», а сломанная полоса: по
# ней нечего нажать и непонятно, зачем она. Берём по одной вещи каждого рода из того, что реально
# установлено, — ровно как на новой макоси.
SEED: tuple[tuple[str, ...], ...] = (
    ("WebBrowser",),
    ("FileManager",),
    ("TerminalEmulator",),
    ("Email",),
    ("InstantMessaging", "Chat", "IRCClient"),
    ("AudioVideo", "Audio", "Player"),
    ("TextEditor", "IDE"),
)

# Окна, которых в доке быть не должно: служебные поверхности, а не программы. Мост xwayland живёт
# невидимым окном постоянно, и без этого списка он висит в доке как полноправный значок.
SKIP: tuple[str, ...] = ("xwaylandvideobridge", "quickshell", "plasmashell", "org.kde.plasmashell",
                         "kwin_wayland", "ksplashqml", "xdg-desktop-portal-kde",
                         # Spectacle's interactive capture UI is fullscreen chrome, not a dock app;
                         # listing it also churns the dock while PrintScreen is open.
                         "spectacle", "org.kde.spectacle")

# Soft alias only: give child WM_CLASS the parent's name/icon, but DO NOT merge
# them into one dock key. Anti-detect browsers (Octo/octium, etc.) need each
# profile window separately switchable — hard-merging hid every profile under one icon.
ALIAS_CLASSES: dict[str, str] = {
    "octium": "octobrowser",
}
# Running windows with these classes get one dock slot per window (not per app).
SEPARATE_INSTANCES: frozenset[str] = frozenset({"octium"})

_FLATPAK = re.compile(r"\b([A-Za-z][\w-]*(?:\.[\w-]+){2,})\b")


def _exec_key(line: str) -> str:
    """Имя двоичного файла из строки Exec — последняя надежда сопоставления.

    У flatpak-обёрток это `flatpak`, одинаковый у всех, поэтому оттуда берём идентификатор
    приложения: `flatpak run --branch=stable com.discordapp.Discord` → com.discordapp.Discord.
    """
    words = [w for w in str(line or "").split() if not w.startswith("%")]
    if not words:
        return ""
    # `env VAR=1 /path/App.AppImage` — настоящее имя после переменных окружения.
    i = 0
    if words[0] == "env":
        i = 1
        while i < len(words) and "=" in words[i] and not words[i].startswith("/"):
            i += 1
    if i >= len(words):
        return ""
    head = words[i].rsplit("/", 1)[-1]
    if head in ("flatpak", "flatpak-spawn"):
        for word in words[i + 1:]:
            if _FLATPAK.fullmatch(word):
                return word.lower()
        return ""
    # Обёртки, у которых двоичный файл общий на все программы: по «steam» нельзя узнать, какая это
    # игра, и без этого списка первая же демка из библиотеки забирала себе окна самого Steam.
    if head in ("env", "sh", "bash", "gtk-launch", "kioclient", "systemd-run", "steam", "lutris",
                "heroic", "wine", "wine64", "python", "python3", "electron", "java", "bottles-cli"):
        return ""
    key = head.lower()
    # AppImageLauncher: KanekiRapt_<hash>.appimage → окно зовёт себя KanekiRapt.
    if key.endswith(".appimage"):
        stem = key[: -len(".appimage")]
        stem = re.sub(r"_[0-9a-f]{8,}$", "", stem)
        return stem or key
    return key


def match_keys(app: dict, *, weak: bool = False) -> list[str]:
    """Строки, любая из которых может оказаться appId открытого окна.

    weak=True — только догадки (имя двоичного файла). Их берут вторым проходом, чтобы точное
    совпадение по идентификатору всегда было сильнее.
    """
    ident = str(app.get("id", ""))
    if weak:
        out = [_exec_key(app.get("exec", ""))]
    else:
        out = [ident.lower(), str(app.get("wmclass", "")).lower()]
        if "." in ident:                  # org.kde.dolphin → dolphin: так окно зовут в половине случаев
            out.append(ident.rsplit(".", 1)[-1].lower())
        # AppImageLauncher: appimagekit_<hash>-KanekiRapt → KanekiRapt (resourceClass окна).
        m = re.match(r"appimagekit_[^-]+-(.+)$", ident, re.I)
        if m:
            out.append(m.group(1).lower())
        # Однословное имя программы часто совпадает с WM_CLASS, когда StartupWMClass пуст.
        name = str(app.get("name", "")).strip().lower()
        if name and " " not in name and "/" not in name:
            out.append(name)
    seen: set[str] = set()
    return [k for k in out if k and not (k in seen or seen.add(k))]


def pinned() -> list[str]:
    """Закреплённое в доке, слева направо. Ключ — «вид:идентификатор», как у меню."""
    try:
        got = json.loads(PIN_FILE.read_text(encoding="utf-8"))
        if isinstance(got, list):
            return [str(k) for k in got][:PIN_MAX]
    except (OSError, ValueError):
        pass
    return _seed()


def _seed() -> list[str]:
    """Чем заполнить док, пока его не тронули руками."""
    keep = [k for k in launcher.favourites() if k.startswith("app:")]
    if keep:
        return keep[:8]
    apps = desktop.list_apps()
    for marks in SEED:
        want = set(marks)
        hit = next((a for a in apps if want & {m.strip() for m in a.get("categories", "").split(";")}), None)
        if hit and f"app:{hit['id']}" not in keep:
            keep.append(f"app:{hit['id']}")
    if keep:
        return keep
    return [k for k in launcher.recents() if k.startswith("app:")][:6]


def save(keys: list[str]) -> None:
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    keep = [k for k in keys if k and not (k in seen or seen.add(k))][:PIN_MAX]
    try:
        PIN_FILE.write_text(json.dumps(keep, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass


def pin(kind: str, ident: str, on: bool | None = None) -> dict:
    """Закрепить или открепить. on=None — переключить."""
    key = f"{kind}:{ident}"
    have = pinned()
    on = key not in have if on is None else bool(on)
    save(([k for k in have if k != key] + [key]) if on else [k for k in have if k != key])
    return {"ok": True, "on": on} | catalog()


def pin_focused(on: bool | None = None) -> dict:
    """Закрепить программу активного окна (или открепить / переключить).

    Горячая клавиша зовёт именно это: человек смотрит на окно и жмёт сочетание — док
    должен понять, какая это программа, без имени из настроек.
    """
    wins = desktop.windows("active")
    if not wins:
        return {"ok": False, "error": "нет активного окна"}
    app = str(wins[0].get("app") or "").lower()
    if not app:
        return {"ok": False, "error": "у окна нет имени программы"}
    match = catalog()["match"]
    hit = match.get(app) or (match.get(app.rsplit(".", 1)[-1]) if "." in app else None)
    if not hit:
        return {"ok": False, "error": f"не нашёл программу для «{app}»"}
    return pin(hit["kind"], hit["id"], on) | {"name": hit.get("name", hit["id"]), "app": app}


def arrange(keys: list[str]) -> dict:
    """Новый порядок после перетаскивания.

    Чужие ключи отбрасываются молча, а свои, которых в списке не оказалось, дописываются в конец в
    прежнем порядке: перестановка — это перестановка, и потерять значок она права не имеет, чем бы
    ни был неполон присланный список.
    """
    was = pinned()
    have = set(was)
    order = [str(k) for k in keys if str(k) in have]
    seen = set(order)
    order += [k for k in was if k not in seen]
    save(order)
    return {"ok": True} | catalog()


# Значок меню берётся у темы значков: в макосных темах «start-here» — это яблоко. Но нарисован он
# «цветом текста» (currentColor), которого разрисовщик Qt не разрешает: на тёмном доке получилось бы
# чёрное пятно. Поэтому файл перекрашивается один раз и кладётся рядом, а док читает уже копию.
LAUNCHER_FILE = config.STATE_DIR / "launcher-icon.svg"
ICON_DIRS = (config.HOME / ".local/share/icons", config.HOME / ".icons",
             pathlib.Path("/usr/share/icons"), pathlib.Path("/usr/local/share/icons"))


def icon_theme() -> str:
    """Имя набора значков, выбранного в системе.

    Плазма держит его в каскаде: своё поверх того, что положила тема оформления. Поэтому сначала
    спрашиваем саму плазму, и только если её утилиты нет — читаем файлы руками.
    """
    try:
        got = subprocess.run([kde.KREAD, "--file", "kdeglobals", "--group", "Icons", "--key", "Theme"],
                             capture_output=True, text=True, timeout=5).stdout.strip()
        if got:
            return got
    except (OSError, subprocess.SubprocessError):
        pass
    base = config.CONFIG_DIR.parent
    for path in (base / "kdeglobals", base / "kdedefaults/kdeglobals"):
        try:
            in_icons = False
            for line in path.read_text(encoding="utf-8").splitlines():
                if line.startswith("["):
                    in_icons = line.strip() == "[Icons]"
                elif in_icons and line.startswith("Theme="):
                    return line.partition("=")[2].strip()
        except OSError:
            continue
    return ""


def find_icon(name: str, theme: str = "") -> pathlib.Path | None:
    """Файл значка в выбранном наборе. Крупный предпочтительнее: его потом уменьшат, а не растянут."""
    theme = theme or icon_theme()
    if not theme:
        return None
    found: list[pathlib.Path] = []
    for root in ICON_DIRS:
        base = root / theme
        if base.is_dir():
            found += list(base.rglob(f"{name}.svg")) + list(base.rglob(f"{name}.png"))
    if not found:
        return None
    # scalable важнее всех, дальше — по размеру в имени каталога, дальше — svg важнее png
    def rank(p: pathlib.Path) -> tuple:
        parts = [q for q in p.parts if q.isdigit()]
        size = int(parts[-1]) if parts else 0
        return (0 if "scalable" in p.parts else 1, -size, 0 if p.suffix == ".svg" else 1)
    return sorted(found, key=rank)[0]


def launcher_icon(want: str = "apple") -> str:
    """Путь к значку, из которого достаётся меню. Пусто — рисовать свою сетку точек."""
    if want in ("", "grid"):
        return ""
    src = find_icon("start-here" if want == "apple" else want)
    if not src:
        return ""
    if src.suffix != ".svg":
        return str(src)
    try:
        text = src.read_text(encoding="utf-8")
    except OSError:
        return ""
    if "currentColor" not in text:
        return str(src)                      # цветной значок трогать незачем
    try:
        config.STATE_DIR.mkdir(parents=True, exist_ok=True)
        LAUNCHER_FILE.write_text(text.replace("currentColor", "#ffffff"), encoding="utf-8")
    except OSError:
        return ""
    return str(LAUNCHER_FILE)


# Кошка. Эталон — виджет CatWalk (Юрий Сауров, GPL-2.0+), а он, в свою очередь, повторяет RunCat.
# Если виджет стоит на машине, берём его кадры: ровно та кошка, к которой человек привык. Свои
# остаются запасными — для машин, где виджета нет. Файлы читаются у него, а не лежат у нас: чужую
# рисовку под другой лицензией мы не раздаём.
CAT_DIR = config.STATE_DIR / "cat"
CATWALK_DIRS = (config.HOME / ".local/share/plasma/plasmoids/org.kde.plasma.catwalk/contents/images",
                pathlib.Path("/usr/share/plasma/plasmoids/org.kde.plasma.catwalk/contents/images"))
CAT_NAMES = ("my-active-0", "my-active-1", "my-active-2", "my-active-3", "my-active-4", "my-idle")


def _whiten(src: pathlib.Path, dst: pathlib.Path) -> bool:
    """Копия значка, перекрашенная в белый. Ничего не делает, если копия уже свежая."""
    try:
        if dst.exists() and dst.stat().st_mtime >= src.stat().st_mtime:
            return True
        text = src.read_text(encoding="utf-8")
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(text.replace("currentColor", "#ffffff").replace("#232629", "#ffffff"), encoding="utf-8")
        return True
    except OSError:
        return False


def cat_frames() -> dict:
    """Кадры бегущей кошки: пять в беге и один спящий. Пусто — у островка есть свои."""
    for base in CATWALK_DIRS:
        if not (base / "my-active-0-symbolic.svg").exists():
            continue
        out: list[str] = []
        for name in CAT_NAMES:
            src, dst = base / f"{name}-symbolic.svg", CAT_DIR / f"{name}.svg"
            if not _whiten(src, dst):
                return {}
            out.append(str(dst))
        return {"run": out[:5], "idle": out[5], "from": "catwalk"}
    return {}


# Корзина. Значок у неё два: пустая и полная, и показывать пустую при сорока файлах внутри — это
# не мелочь, а прямая ложь о состоянии машины. Смотрим один каталог и останавливаемся на первой же
# записи: считать сорок штук незачем, вопрос двоичный.
TRASH_DIRS = (config.HOME / ".local/share/Trash/files",)


def trash_full() -> bool:
    import os

    for base in TRASH_DIRS:
        try:
            with os.scandir(base) as it:
                for _ in it:
                    return True
        except OSError:
            continue
    return False


# Очистить корзину. Действие необратимое, поэтому здесь оно нарочно тупое: ходим по двум каталогам
# самой корзины и больше никуда. Ни поиска, ни обхода ссылок — иначе ссылка, брошенная в корзину,
# уводит удаление в живой каталог, и «очистить корзину» стирает то, что там не лежало.
#
# Подтверждение — на стороне того, кто просит: в доке это второй щелчок по пункту, в командной
# строке — сама команда. Спрашивать дважды в обоих местах некуда.
def trash_empty() -> dict:
    import shutil

    base = config.HOME / ".local/share/Trash"
    gone, failed = 0, 0
    for part in ("files", "info"):
        folder = base / part
        try:
            entries = list(folder.iterdir())
        except OSError:
            continue
        for item in entries:
            try:
                if item.is_symlink() or item.is_file():
                    item.unlink()
                else:
                    shutil.rmtree(item)
                if part == "files":
                    gone += 1
            except OSError:
                if part == "files":
                    failed += 1
    return {"ok": failed == 0, "removed": gone, "failed": failed, "trash_full": trash_full()}


# Бросили файлы на корзину. Через `gio trash`, а не `rm`: корзина — это не «удалить», а «убрать со
# стола», и вернуть оттуда должно быть можно. Своими руками класть файлы в ~/.local/share/Trash тоже
# нельзя: туда полагается писать ещё и .trashinfo с исходным путём, иначе «восстановить» некуда.
def trash_put(paths: list[str]) -> dict:
    good = [p for p in (str(x).strip() for x in paths) if p and os.path.exists(p)]
    if not good:
        return {"ok": False, "error": "нечего выбрасывать", "trash_full": trash_full()}
    try:
        done = subprocess.run(["gio", "trash", *good], capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        return {"ok": False, "error": str(e), "trash_full": trash_full()}
    if done.returncode != 0:
        return {"ok": False, "error": (done.stderr or "").strip()[:200], "trash_full": trash_full()}
    return {"ok": True, "moved": len(good), "trash_full": trash_full()}


def hidden_tray() -> list[str]:
    """Идентификаторы значков лотка, которые прятать. Сравнение — без учёта регистра."""
    from . import config as cfg_mod

    got = (cfg_mod.load().get("tray") or {}).get("hidden") or []
    return [str(k).strip().lower() for k in got if str(k).strip()]


def _tray_key_hits(hidden_key: str, name: str) -> bool:
    """Exact or stem-alias match: hidden "discord" covers "discord-tray" and vice versa."""
    if not hidden_key or not name:
        return False
    if hidden_key == name:
        return True
    if len(hidden_key) < 4 or len(name) < 4:
        return False
    return name.startswith(hidden_key) or hidden_key.startswith(name)


def hide_tray(ident: str, on: bool | None = None, aliases: list[str] | None = None) -> dict:
    """Спрятать значок лотка или вернуть его. on=None — переключить.

    aliases — дополнительные имена того же значка (id/title/tooltip). При показе
    убираем из hidden всю семью алиасов, иначе leftover "discord-tray" держит
    Discord выключенным после включения в настройках.
    """
    from . import config as cfg_mod

    keys = [str(ident).strip().lower()] + [str(a).strip().lower() for a in (aliases or [])]
    keys = [k for k in keys if k]
    # unique, stable
    seen: list[str] = []
    for k in keys:
        if k not in seen:
            seen.append(k)
    keys = seen
    if not keys:
        return {"ok": False, "error": "пустой идентификатор"}
    have = hidden_tray()
    primary = keys[0]
    currently_hidden = any(_tray_key_hits(h, k) for h in have for k in keys)
    on = (not currently_hidden) if on is None else bool(on)
    if on:
        keep = sorted(set(have) | {primary})
    else:
        keep = [h for h in have if not any(_tray_key_hits(h, k) for k in keys)]
    cfg_mod.set_value("tray", "hidden", keep)
    return {"ok": True, "on": on, "hidden": keep}


# Theme SVGs (MacTahoe/WhiteSur) for Discord embed a small Clyde face with
# preserveAspectRatio="none" — Qt scales it into tiny eyes. Prefer the stock PNG.
_DISCORD_ICON_NAMES = {
    "discord", "discord-tray", "com.discordapp.discord",
    "com.discordapp.discordcanary", "com.discordapp.discordptb",
}

def _prefer_discord_png(name: str) -> pathlib.Path | None:
    key = str(name or "").strip().lower().rsplit("/", 1)[-1]
    key = key.removesuffix(".svg").removesuffix(".png")
    if key not in _DISCORD_ICON_NAMES and "discord" not in key:
        return None
    for root in ICON_DIRS:
        for size in ("512x512", "256x256", "128x128", "64x64"):
            p = root / "hicolor" / size / "apps" / "discord.png"
            if p.is_file():
                return p
        p = root / "hicolor" / "scalable" / "apps" / "discord.svg"
        if p.is_file():
            # Only if it is a real vector (no embedded raster plate).
            try:
                if "data:image/png" not in p.read_text(encoding="utf-8", errors="ignore"):
                    return p
            except OSError:
                pass
    return None


def _resolve_icon(name: str, theme: str = "") -> str:
    """Turn a theme Icon= name into an absolute path when we can.

    Quickshell.iconPath is async and often blank on the first one/two UI starts (theme not
    warm yet) — that looked like transparent dock icons. A file:// path paints immediately.
    """
    n = str(name or "").strip()
    if not n:
        return ""
    if n.startswith("file:") or n.startswith("image:") or n.startswith("/"):
        # Absolute theme SVG for Discord still gets the shrunken Clyde — swap when we can.
        base = pathlib.Path(n.removeprefix("file://")).name if "discord" in n.lower() else ""
        if base:
            pref = _prefer_discord_png(base)
            if pref:
                return str(pref)
        return n
    pref = _prefer_discord_png(n)
    if pref:
        return str(pref)
    hit = find_icon(n, theme)
    return str(hit) if hit else n


def _save_catalog(data: dict) -> None:
    try:
        config.STATE_DIR.mkdir(parents=True, exist_ok=True)
        # Drop huge match table from the on-disk seed? Keep it — UI needs it for running windows.
        CATALOG_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    except OSError:
        pass



def _lookup_window(app_id: str, match: dict) -> dict | None:
    """Match table row for a window appId (same rules as JD.dockLookup)."""
    a = str(app_id or "").lower()
    if not a:
        return None
    hit = match.get(a)
    if hit:
        return hit
    # Soft alias parent
    parent = ALIAS_CLASSES.get(a)
    if parent and parent in match:
        return match[parent]
    return None


def slot_apps() -> list[dict]:
    """App icons left-to-right as the dock draws them (pinned, then running extras).

    Skips launcher/sep/trash/cat/clock — only real app slots, 0-based list for go().
    """
    cfg = config.load().get("dock") or {}
    layout = cfg.get("layout") or ["launcher", "sep", "pinned", "running", "sep", "trash", "sep", "cat", "clock"]
    words = [str(w).strip().lower() for w in layout if str(w).strip()]
    cat = catalog_cached()
    pinned_items = list(cat.get("items") or [])
    match = cat.get("match") or {}
    skip = {s.lower() for s in (cat.get("skip") or list(SKIP))}
    separate = set(SEPARATE_INSTANCES) | {str(x).lower() for x in (cat.get("separate") or [])}

    # Group live windows like DockView.grouped
    by: dict[str, dict] = {}
    order: list[str] = []
    try:
        wins = desktop.windows("list") or []
    except Exception:
        wins = []
    for w in wins:
        a = str(w.get("app") or "").lower()
        if not a or a in skip:
            continue
        hit = _lookup_window(a, match)
        split = a in separate or bool(hit and hit.get("separate"))
        key = f"win:{a}:{w.get('id', '')}" if split else (hit["key"] if hit else f"win:{a}")
        if key not in by:
            raw_icon = (hit.get("icon") if hit else None) or ("wine" if a.endswith(".exe") else a)
            if split:
                label = (w.get("title") or "").strip() or (hit.get("name") if hit else w.get("app") or "")
            else:
                label = hit.get("name") if hit else (w.get("app") or "")
            by[key] = {
                "key": key,
                "kind": (hit.get("kind") if hit else "app") or "app",
                "id": (hit.get("id") if hit else "") or "",
                "name": label,
                "icon": raw_icon,
                "wins": [],
            }
            order.append(key)
        by[key]["wins"].append(w)

    taken = {it.get("key") for it in pinned_items if it.get("key")}
    out: list[dict] = []
    for word in words:
        if word == "pinned":
            for it in pinned_items:
                live = by.get(it["key"])
                row = {
                    "key": it["key"], "kind": it.get("kind") or "app", "id": it.get("id") or "",
                    "name": it.get("name") or it.get("id") or "", "icon": it.get("icon") or "",
                    "pinned": True, "wins": live["wins"] if live else [],
                }
                out.append(row)
        elif word == "running":
            for k in order:
                if k in taken:
                    continue
                g = by[k]
                out.append({
                    "key": k, "kind": g.get("kind") or "app", "id": g.get("id") or "",
                    "name": g.get("name") or "", "icon": g.get("icon") or "",
                    "pinned": False, "wins": g.get("wins") or [],
                })
    return out


def go(index: int) -> dict:
    """Activate the Nth dock app left-to-right (1-based), like macOS Cmd+N / Meta+N.

    Running → focus (raise); closed → launch. Out of range → error.
    """
    try:
        n = int(index)
    except (TypeError, ValueError):
        return {"ok": False, "error": "нужен номер слота (1…N)"}
    if n < 1:
        return {"ok": False, "error": "номер слота начинается с 1"}
    apps = slot_apps()
    if not apps:
        return {"ok": False, "error": "док пуст"}
    if n > len(apps):
        return {"ok": False, "error": f"в доке только {len(apps)} программ(ы)", "n": n, "count": len(apps)}
    item = apps[n - 1]
    wins = [w for w in (item.get("wins") or []) if w]
    if wins:
        # Prefer visible, then any
        front = next((w for w in wins if not w.get("minimized") and w.get("active")), None)
        if not front:
            front = next((w for w in wins if not w.get("minimized")), wins[0])
        wid = str(front.get("id") or "")
        if wid:
            desktop.windows("focus", wid=wid)
            return {"ok": True, "action": "focus", "name": item.get("name"), "id": item.get("id"),
                    "n": n, "wid": wid}
        # Fallback: focus by app query
        desktop.windows("focus", query=str(item.get("id") or item.get("name") or ""))
        return {"ok": True, "action": "focus", "name": item.get("name"), "id": item.get("id"), "n": n}
    # Launch
    kind = item.get("kind") or "app"
    ident = item.get("id") or ""
    if not ident:
        return {"ok": False, "error": f"слот {n} ({item.get('name')}) без id — нечего запускать", "n": n}
    got = launcher.run(kind, ident)
    return {"ok": bool(got.get("ok")), "action": "launch", "name": item.get("name"), "id": ident,
            "n": n, **{k: v for k, v in got.items() if k != "ok"}}


def catalog_cached() -> dict:
    """Return the last saved catalog immediately; `_warm_dock` builds a miss asynchronously."""
    try:
        got = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
        if isinstance(got, dict) and isinstance(got.get("items"), list) and got.get("pinned") is not None:
            # Keep trash/launcher fresh cheaply.
            got["trash_full"] = trash_full()
            launcher = launcher_icon(str((config.load().get("dock") or {}).get("launcher", "apple")))
            if launcher:
                got["launcher"] = launcher
            return got
    except (OSError, ValueError, TypeError):
        pass
    return {}


# ───────────── папки-стопки ─────────────
#
# Папка в доке — это не ярлык на файловый менеджер, а стопка: нажал — видно, что внутри, и можно
# открыть нужное, не заходя никуда. На макоси это самая используемая часть дока после программ, и
# ровно по этой причине: чаще всего от папки нужен один файл из неё, а не она сама.
FOLDER_MAX = 40


def folder_items(path: str) -> dict:
    """Что лежит в закреплённой папке. Папки первыми, потом файлы, и те и другие по алфавиту."""
    import os

    base = pathlib.Path(os.path.expanduser(str(path or ""))).resolve()
    if not base.is_dir():
        return {"ok": False, "error": "это не папка", "path": str(base), "items": []}
    out = []
    try:
        with os.scandir(base) as it:
            for entry in it:
                if entry.name.startswith("."):
                    continue
                try:
                    is_dir = entry.is_dir()
                    size = 0 if is_dir else entry.stat().st_size
                    when = entry.stat().st_mtime
                except OSError:
                    continue
                out.append({"name": entry.name, "path": str(base / entry.name),
                            "dir": is_dir, "bytes": size, "at": when})
    except OSError as e:
        return {"ok": False, "error": str(e), "path": str(base), "items": []}
    out.sort(key=lambda i: (not i["dir"], i["name"].lower()))
    return {"ok": True, "path": str(base), "name": base.name or str(base),
            "items": out[:FOLDER_MAX], "more": max(0, len(out) - FOLDER_MAX)}


def _steam_icon(appid: str, theme: str = "") -> str:
    """Значок игры Steam, который Steam сам кладёт в hicolor при создании ярлыка; нет его — общий
    значок «игра», а не чужой, подобранный по догадке."""
    name = f"steam_icon_{appid}"
    return name if find_icon(name, theme) else "applications-games"


def catalog() -> dict:
    """Всё, что доку нужно от этой половины, одним куском.

    `items` — закреплённое в своём порядке. `match` — таблица «appId окна → программа»; по ней QML
    подписывает окна настоящими именами и не заводит второй значок рядом с закреплённым.
    """
    apps = desktop.list_apps()
    rows = {f"app:{a['id']}": {"kind": "app", "id": a["id"],
                               "strong": match_keys(a), "weak": match_keys(a, weak=True),
                               "name": a.get("name_ru") or a.get("name") or a["id"],
                               "icon": a.get("icon", "")} for a in apps}
    theme = icon_theme()
    game_list = desktop.list_games()
    games = {f"game:{g['id']}": {"kind": "game", "id": str(g["id"]), "strong": [], "weak": [],
                                 "name": g["name"],
                                 "icon": _steam_icon(str(g["id"]), theme) if g["source"].startswith("steam") else "applications-games"}
             for g in game_list}
    # Папки-стопки: ключ dir:<путь>, имя — имя папки. Проверять существование здесь обязательно:
    # папку могли удалить или отмонтировать, и значок, ведущий в никуда, хуже отсутствующего.
    folders = {}
    for key in pinned():
        if not key.startswith("dir:"):
            continue
        path = pathlib.Path(key[4:])
        if not path.is_dir():
            continue
        folders[key] = {"kind": "dir", "id": str(path), "strong": [], "weak": [],
                        "name": path.name or str(path), "icon": "folder"}

    known = rows | games | folders

    # Два прохода: сначала точные ключи (идентификатор, StartupWMClass), потом догадки по имени
    # двоичного файла. Иначе случайная программа, запускаемая тем же файлом, забирает окна себе.
    match: dict[str, dict] = {}
    for field in ("strong", "weak"):
        for key, row in rows.items():
            short = {"kind": row["kind"], "id": row["id"], "name": row["name"], "icon": row["icon"], "key": key}
            for k in row[field]:
                match.setdefault(k, short)

    # Окна игр Steam приходят с классом steam_app_<appid> и без .desktop: раньше они подписывались сырым
    # классом и получали чужой значок. Имя и значок берём у самой игры; ключ — тот же, что у закреплённой.
    for g in game_list:
        if g["source"].startswith("steam"):
            gk = f"game:{g['id']}"
            match.setdefault(f"steam_app_{g['id']}", {"kind": "game", "id": str(g["id"]), "name": g["name"],
                                                      "icon": games[gk]["icon"], "key": gk})

    # Soft aliases: octium gets Octo Browser's name/icon, but keeps its own match key
    # so DockView can still split profile windows into separate slots.
    for child, parent in ALIAS_CLASSES.items():
        parent_hit = match.get(parent)
        if not parent_hit:
            continue
        soft = dict(parent_hit)
        soft["key"] = f"win:{child}"          # not parent key — no hard merge
        soft["alias_of"] = parent_hit["key"]
        soft["separate"] = child in SEPARATE_INSTANCES
        match.setdefault(child, soft)

    launcher = launcher_icon(str((config.load().get("dock") or {}).get("launcher", "apple")))
    want = pinned()
    items = []
    for k in want:
        if k not in known:
            continue
        row = {k2: v for k2, v in (known[k] | {"key": k}).items() if k2 not in ("strong", "weak")}
        row["icon"] = _resolve_icon(row.get("icon", ""), theme)
        items.append(row)
    # Also resolve icons inside match so running (unpinned) windows paint immediately.
    for short in match.values():
        if isinstance(short, dict) and short.get("icon"):
            short["icon"] = _resolve_icon(short["icon"], theme)
    out = {"launcher": launcher, "cat": cat_frames(), "items": items,
           "pinned": [k for k in want if k in known], "match": match, "skip": list(SKIP),
           "separate": sorted(SEPARATE_INSTANCES), "trash_full": trash_full()}
    if want and not items:
        prev = None
        try:
            prev = json.loads(CATALOG_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError, TypeError):
            prev = None
        if isinstance(prev, dict) and (prev.get("items") or []):
            prev["trash_full"] = out["trash_full"]
            if out.get("launcher"):
                prev["launcher"] = out["launcher"]
            return prev
        return out
    _save_catalog(out)
    return out
