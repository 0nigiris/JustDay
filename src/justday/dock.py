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
import pathlib
import re
import subprocess

from . import config, desktop, launcher

PIN_FILE = config.STATE_DIR / "dock.json"
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
                         "kwin_wayland", "ksplashqml", "xdg-desktop-portal-kde")

_FLATPAK = re.compile(r"\b([A-Za-z][\w-]*(?:\.[\w-]+){2,})\b")


def _exec_key(line: str) -> str:
    """Имя двоичного файла из строки Exec — последняя надежда сопоставления.

    У flatpak-обёрток это `flatpak`, одинаковый у всех, поэтому оттуда берём идентификатор
    приложения: `flatpak run --branch=stable com.discordapp.Discord` → com.discordapp.Discord.
    """
    words = [w for w in str(line or "").split() if not w.startswith("%")]
    if not words:
        return ""
    head = words[0].rsplit("/", 1)[-1]
    if head in ("flatpak", "flatpak-spawn"):
        for word in words[1:]:
            if _FLATPAK.fullmatch(word):
                return word.lower()
        return ""
    # Обёртки, у которых двоичный файл общий на все программы: по «steam» нельзя узнать, какая это
    # игра, и без этого списка первая же демка из библиотеки забирала себе окна самого Steam.
    if head in ("env", "sh", "bash", "gtk-launch", "kioclient", "systemd-run", "steam", "lutris",
                "heroic", "wine", "wine64", "python", "python3", "electron", "java", "bottles-cli"):
        return ""
    return head.lower()


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


def arrange(keys: list[str]) -> dict:
    """Новый порядок после перетаскивания. Чужие ключи отбрасываются молча."""
    have = set(pinned())
    save([str(k) for k in keys if str(k) in have])
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
        got = subprocess.run(["kreadconfig6", "--file", "kdeglobals", "--group", "Icons", "--key", "Theme"],
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


def hidden_tray() -> list[str]:
    """Идентификаторы значков лотка, которые прятать. Сравнение — без учёта регистра."""
    from . import config as cfg_mod

    got = (cfg_mod.load().get("tray") or {}).get("hidden") or []
    return [str(k).strip().lower() for k in got if str(k).strip()]


def hide_tray(ident: str, on: bool | None = None) -> dict:
    """Спрятать значок лотка или вернуть его. on=None — переключить."""
    from . import config as cfg_mod

    key = str(ident).strip().lower()
    if not key:
        return {"ok": False, "error": "пустой идентификатор"}
    have = hidden_tray()
    on = key not in have if on is None else bool(on)
    keep = sorted(set(have) | {key}) if on else [k for k in have if k != key]
    cfg_mod.set_value("tray", "hidden", keep)
    return {"ok": True, "on": on, "hidden": keep}


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
    games = {f"game:{g['id']}": {"kind": "game", "id": str(g["id"]), "strong": [], "weak": [],
                                 "name": g["name"], "icon": "applications-games"}
             for g in desktop.list_games()}
    known = rows | games

    # Два прохода: сначала точные ключи (идентификатор, StartupWMClass), потом догадки по имени
    # двоичного файла. Иначе случайная программа, запускаемая тем же файлом, забирает окна себе.
    match: dict[str, dict] = {}
    for field in ("strong", "weak"):
        for key, row in rows.items():
            short = {"kind": row["kind"], "id": row["id"], "name": row["name"], "icon": row["icon"], "key": key}
            for k in row[field]:
                match.setdefault(k, short)

    launcher = launcher_icon(str((config.load().get("dock") or {}).get("launcher", "apple")))
    want = pinned()
    return {"launcher": launcher, "items": [{k2: v for k2, v in (known[k] | {"key": k}).items() if k2 not in ("strong", "weak")}
                      for k in want if k in known],
            "pinned": [k for k in want if k in known], "match": match, "skip": list(SKIP)}
