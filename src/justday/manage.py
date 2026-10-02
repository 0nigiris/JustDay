"""Backend of the Settings window and the setup wizard: everything returns plain JSON-able data."""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from importlib.metadata import PackageNotFoundError
from importlib.metadata import version as pkg_version
from pathlib import Path

from . import config, providers

SERVICES = ["justday.service", "justday-island.service", "justday-voice.service", "justday-ollama.service"]
VOICES = [
    {"id": "eugene", "name": "Евгений", "kind": "мужской"},
    {"id": "aidar", "name": "Айдар", "kind": "мужской"},
    {"id": "baya", "name": "Бая", "kind": "женский"},
    {"id": "kseniya", "name": "Ксения", "kind": "женский"},
    {"id": "xenia", "name": "Ксения 2", "kind": "женский"},
]
MODELS = {  # suggested models per provider (any id works)
    "claude": ["sonnet", "opus", "haiku"],
    "ollama": ["qwen3.5:9b", "qwen3.5:4b", "gemma4:e4b"],
    # ollama.com/search?c=cloud, tool-capable (Sept 2026)
    "ollama_cloud": ["kimi-k3:cloud", "glm-5.3:cloud", "deepseek-v4-flash:cloud", "minimax-m3:cloud", "qwen3.5:cloud",
                     "gpt-oss:120b-cloud"],
    # free tool-capable models listed by openrouter.ai/api/v1/models (Sept 2026); the list changes over time.
    # openrouter/free picks whichever free model is up
    "openrouter": ["openrouter/free", "nvidia/nemotron-3-ultra-550b-a55b:free", "nvidia/nemotron-3-super-120b-a12b:free",
                   "google/gemma-4-31b-it:free", "nvidia/nemotron-3.5-lightning:free"],
    "deepseek": ["deepseek-v4-pro", "deepseek-flash"],
    "custom": [],
}


def voice_request(req: dict, timeout: float = 600) -> dict:
    """One JSON command to the neural voice service (justday-voice)."""
    import socket

    path = config.RUNTIME_DIR / "justday-voice.sock"
    try:
        with socket.socket(socket.AF_UNIX) as s:
            s.settimeout(timeout)
            s.connect(str(path))
            s.sendall((json.dumps(req, ensure_ascii=False) + "\n").encode())
            return json.loads(s.makefile().readline() or "{}")
    except OSError as e:
        return {"ok": False, "error": f"голосовой сервис недоступен ({e}); scripts/setup-voice.sh"}


def voice_dir(voice_id: str) -> Path | None:
    """Каталог голоса: сначала свои, потом встроенные."""
    for root in (config.DATA_DIR / "voices", config.REPO_DIR / "voice" / "voices"):
        d = root / voice_id
        if (d / "ref.wav").exists():
            return d
    return None


def voice_tempo(voice_id: str, tempo: float) -> dict:
    """Темп — в сам образец голоса, а не в речь после синтеза.

    Нейроголос копирует образец целиком, вместе с его скоростью. Раньше
    ускорение делалось уже по готовой речи (WSOLA) — отсюда металлический
    призвук, на который и жалуются. Если ускорить образец один раз хорошим
    алгоритмом, модель просто заговорит быстрее, и растягивать больше нечего.

    Встроенный голос при этом не переписывается: ускоренная копия ложится
    в пользовательский каталог голосов и перекрывает встроенную, как любой
    свой голос. `tempo 1.0` просто убирает копию, и всё как было.
    """
    tempo = max(0.6, min(1.6, float(tempo)))
    source = voice_dir(voice_id)
    if source is None:
        return {"ok": False, "error": f"нет такого голоса: {voice_id}"}
    mine = config.DATA_DIR / "voices" / voice_id
    original = mine / "ref-original.wav"
    if original.exists():  # копия уже делалась: растягиваем всегда исходник
        source_ref = original
    else:
        source_ref = (source / "ref-original.wav") if (source / "ref-original.wav").exists() else source / "ref.wav"
    if abs(tempo - 1.0) < 0.01:
        if mine.exists() and original.exists():
            shutil.copy2(original, mine / "ref.wav")
            return {"ok": True, "voice": voice_id, "tempo": 1.0, "restored": True}
        return {"ok": True, "voice": voice_id, "tempo": 1.0, "restored": False}
    if not shutil.which("ffmpeg"):
        return {"ok": False, "error": "нужен ffmpeg (он умеет растягивать звук без призвука)"}
    mine.mkdir(parents=True, exist_ok=True)
    if not original.exists():
        shutil.copy2(source_ref, original)
    for name in ("ref.txt", "voice.json"):  # текст образца и описание едут вместе со звуком
        if (source / name).exists() and not (mine / name).exists():
            shutil.copy2(source / name, mine / name)
    # rubberband звучит заметно чище atempo, но есть не в каждой сборке ffmpeg
    for chain in (f"rubberband=tempo={tempo:.3f}", f"atempo={tempo:.3f}"):
        tmp = mine / "ref-tempo.wav"
        done = subprocess.run(["ffmpeg", "-y", "-i", str(original), "-filter:a", chain, str(tmp)],
                              capture_output=True, timeout=120)
        if done.returncode == 0 and tmp.exists() and tmp.stat().st_size > 1000:
            tmp.replace(mine / "ref.wav")
            return {"ok": True, "voice": voice_id, "tempo": round(tempo, 3),
                    "filter": chain.split("=")[0], "file": str(mine / "ref.wav")}
        tmp.unlink(missing_ok=True)
    return {"ok": False, "error": "ffmpeg не смог растянуть образец"}


def eleven_voices() -> dict:
    """Voices available on the ElevenLabs account behind the stored key (names and ids, nothing else)."""
    import urllib.error
    import urllib.request

    key = config.secret("ELEVENLABS_API_KEY")
    if not key:
        return {"ok": False, "error": "no key yet: `justday voice key` (paste it on stdin)"}
    req = urllib.request.Request("https://api.elevenlabs.io/v2/voices?page_size=100", headers={"xi-api-key": key})
    try:
        with urllib.request.urlopen(req, timeout=20) as r:
            data = json.loads(r.read().decode())
    except (urllib.error.URLError, OSError, ValueError) as e:
        return {"ok": False, "error": f"ElevenLabs: {e}"}
    got = [{"id": v.get("voice_id", ""), "name": v.get("name", ""),
            "labels": ", ".join(f"{k}: {x}" for k, x in (v.get("labels") or {}).items())}
           for v in data.get("voices") or []]
    return {"ok": True, "voices": got, "current": config.load()["tts"].get("eleven_voice", "")}


def voices() -> dict:
    """Neural voices are read from disk (the service may be busy speaking); status comes from systemd."""
    installed = (config.DATA_DIR / "voice" / ".venv" / "bin" / "python").exists()
    state = subprocess.run(["systemctl", "--user", "is-active", "justday-voice.service"], capture_output=True, text=True).stdout.strip()
    items = []
    for root, builtin in ((config.REPO_DIR / "voice" / "voices", True), (config.DATA_DIR / "voices", False)):
        for d in sorted(root.iterdir()) if root.is_dir() else []:
            if not (d / "ref.wav").exists():
                continue
            meta = json.loads((d / "voice.json").read_text(encoding="utf-8")) if (d / "voice.json").exists() else {}
            items = [v for v in items if v["id"] != d.name]  # user voice overrides a built-in one
            items.append({"id": d.name, "name": meta.get("name", d.name), "description": meta.get("description", ""),
                          "kind": meta.get("kind", ""), "builtin": builtin})
    return {"neural_installed": installed, "neural_running": state == "active", "neural_available": installed and state == "active",
            "neural": items, "silero": VOICES, "eleven_key": bool(config.secret("ELEVENLABS_API_KEY"))}


def update_status(fetch: bool = True) -> dict:
    """Is the GitHub copy newer than this install? (git fetch + compare; works for shallow clones too)"""
    repo = str(config.REPO_DIR)
    git = lambda *a: subprocess.run(["git", "-C", repo, *a], capture_output=True, text=True, timeout=60)  # noqa: E731
    if not (config.REPO_DIR / ".git").exists():
        return {"ok": False, "error": "не git-копия"}
    branch = git("rev-parse", "--abbrev-ref", "HEAD").stdout.strip() or "main"
    if fetch:
        f = git("fetch", "--quiet", "origin", branch)
        if f.returncode != 0:
            return {"ok": False, "error": (f.stderr.strip() or "нет сети")[:200]}
    behind = git("rev-list", "--count", f"HEAD..origin/{branch}").stdout.strip()
    log = git("log", "--format=%s", f"HEAD..origin/{branch}").stdout.strip().splitlines()
    dirty = bool(git("status", "--porcelain", "--untracked-files=no").stdout.strip())
    return {"ok": True, "branch": branch, "behind": int(behind or 0), "changes": log[:10], "local_changes": dirty,
            "current": git("rev-parse", "--short", "HEAD").stdout.strip()}


def app_version() -> str:
    try:
        return pkg_version("justday")
    except PackageNotFoundError:
        return "dev"


def audio_devices() -> dict:
    def listing(kind: str) -> list[dict]:
        try:
            out = subprocess.run(["pactl", "--format=json", "list", kind], capture_output=True, text=True, timeout=5).stdout
            items = json.loads(out or "[]")
        except (OSError, json.JSONDecodeError, subprocess.TimeoutExpired):
            return []
        return [{"name": d["name"], "description": d.get("description") or d["name"]}
                for d in items if not d["name"].endswith(".monitor")]
    return {"sources": listing("sources"), "sinks": listing("sinks")}


def _shortcut(desktop_id: str) -> list[str]:
    """Active keys of a desktop-file shortcut. kglobalshortcutsrc holds only keys changed in System Settings;
    keys equal to the desktop file's X-KDE-Shortcuts defaults are not written there, so fall back to the file."""
    raw = subprocess.run(["kreadconfig6", "--file", "kglobalshortcutsrc", "--group", "services", "--group",
                          desktop_id, "--key", "_launch"], capture_output=True, text=True).stdout.strip()
    if raw and raw != "none":
        return [k for k in raw.split("\t") if k and k != "none"]
    f = Path.home() / ".local/share/applications" / desktop_id
    m = re.search(r"^X-KDE-Shortcuts=(.*)$", f.read_text(), re.M) if f.exists() else None
    return [k.strip() for k in m.group(1).split(",") if k.strip()] if m else []


# Клавиши описаны здесь и в scripts/setup-hotkey.sh — по одной строке на каждую: имя, подпись для
# настроек, значение по умолчанию. Всё остальное (островок, настройки, `justday hotkey`) читает эту
# таблицу, поэтому новая клавиша не требует правок в четырёх местах.
HOTKEYS: tuple[tuple[str, str, str], ...] = (
    ("talk", "Говорить", "Meta+J"),
    ("cancel", "Отменить всё", "Meta+Shift+J"),
    ("type", "Написать текстом", "Meta+K"),
    ("yes", "Да / разрешить", "Meta+Y"),
    ("no", "Нет / отклонить", "Meta+N"),
    ("apps", "Spotlight / поиск", "Alt+Space"),
    ("clip", "Буфер обмена", "Meta+V"),
    ("emoji", "Эмодзи", "Meta+."),
    ("load", "Нагрузка машины", ""),
    ("menu", "Меню приложений", "Meta"),
    # Meta забираем у лаунчера Plasma (см. free_key / set_hotkeys). Meta+P — «pin».
    ("pin", "Закрепить в доке", "Meta+P"),
    # Meta+1…9 — N-я программа слева направо (как Cmd+N на macOS). Забираем у
    # plasmashell «Activate Task Manager Entry N».
    ("dock1", "Док: слот 1", "Meta+1"),
    ("dock2", "Док: слот 2", "Meta+2"),
    ("dock3", "Док: слот 3", "Meta+3"),
    ("dock4", "Док: слот 4", "Meta+4"),
    ("dock5", "Док: слот 5", "Meta+5"),
    ("dock6", "Док: слот 6", "Meta+6"),
    ("dock7", "Док: слот 7", "Meta+7"),
    ("dock8", "Док: слот 8", "Meta+8"),
    ("dock9", "Док: слот 9", "Meta+9"),
)
HOTKEY_DEFAULTS = {name: default for name, _, default in HOTKEYS}


def _hotkey_id(name: str) -> str:
    return "net.local.justday.desktop" if name == "talk" else f"net.local.justday-{name}.desktop"


# ───────────────────── клавиша, которую уже кто-то занял ─────────────────────
#
# Записать сочетание в kglobalshortcutsrc мало. Клавишу держит живой KWin, и если она уже за кем-то
# числится — за KRunner (Alt+Space), за выбиралкой эмодзи (Meta+.), за Klipper (Meta+V), — нажатие
# уходит ему, а наша запись лежит мёртвой. Хуже того, часть этих привязок вообще не описана в
# файле: они встроены в сами программы, и искать их в настройках бесполезно.
#
# Поэтому спрашиваем не файл, а KWin: кто держит вот эту клавишу. И у него же просим отдать —
# убирая из его списка ровно одну клавишу, не трогая остальные (у KRunner их три, и Alt+F2 должен
# остаться). Прежнее значение KDE помнит как «по умолчанию», так что вернуть его можно кнопкой
# «По умолчанию» в системных настройках.

QT_MODS = {"meta": 0x10000000, "super": 0x10000000, "win": 0x10000000,
           "ctrl": 0x04000000, "control": 0x04000000, "alt": 0x08000000, "shift": 0x02000000}
# Голая «Meta» — это не модификатор, а самостоятельная клавиша (Qt::Key_Meta). Так её держит
# plasmashell под меню приложений, так же её должны просить и мы.
QT_KEYS = {"meta": 0x01000022, "super": 0x01000022, "win": 0x01000022,
           "ctrl": 0x01000021, "control": 0x01000021, "alt": 0x01000023, "shift": 0x01000020,
           "space": 0x20, "tab": 0x01000001, "backspace": 0x01000003, "return": 0x01000004,
           "enter": 0x01000005, "esc": 0x01000000, "escape": 0x01000000, "insert": 0x01000006,
           "delete": 0x01000007, "home": 0x01000010, "end": 0x01000011, "pageup": 0x01000016,
           "pagedown": 0x01000017, "left": 0x01000012, "up": 0x01000013, "right": 0x01000014,
           "down": 0x01000015, "print": 0x01000009, "menu": 0x01000055}


def key_code(combo: str) -> int | None:
    """«Meta+Shift+J» → число, каким эту клавишу знает Qt. Непонятное сочетание — None."""
    code = 0
    parts = [p for p in str(combo or "").replace(" ", "").split("+") if p or combo.endswith("+")]
    # «Meta++» — это Meta и знак «плюс»: пустая часть в конце значит именно его.
    if combo.endswith("+") and len(parts) < len(combo.split("+")):
        parts.append("+")
    if not parts:
        return None
    *mods, key = parts
    for mod in mods:
        if (bit := QT_MODS.get(mod.lower())) is None:
            return None
        code |= bit
    key = key.lower()
    if key in QT_KEYS:
        return code | QT_KEYS[key]
    if len(key) == 1:
        return code | ord(key.upper())
    if key.startswith("f") and key[1:].isdigit() and 1 <= int(key[1:]) <= 35:
        return code | (0x01000030 + int(key[1:]) - 1)
    return None


def _accel(method: str, *args: str) -> str:
    """Вызов к kglobalaccel. Его держит KWin, и разговаривать с ним можно только по шине."""
    cmd = ["gdbus", "call", "--session", "--dest", "org.kde.kglobalaccel",
           "--object-path", "/kglobalaccel", "--method", f"org.kde.KGlobalAccel.{method}", *args]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return ""
    return p.stdout.strip() if p.returncode == 0 else ""


def shortcut_owners(code: int) -> list[tuple]:
    """Кто сейчас держит эту клавишу: список (action, friendly, component, …, keys, defaults)."""
    import ast

    out = _accel("getGlobalShortcutsByKey", str(code))
    try:
        got = ast.literal_eval(out)
    except (ValueError, SyntaxError):
        return []
    return list(got[0]) if got and isinstance(got[0], list) else []


def free_key(combo: str, keep: str) -> list[str]:
    """Отобрать клавишу у всех, кроме `keep`. Возвращает, у кого отобрали."""
    code = key_code(combo)
    if code is None:
        return []
    taken = []
    for owner in shortcut_owners(code):
        action, friendly, component, comp_friendly = owner[0], owner[1], owner[2], owner[3]
        if component == keep:
            continue
        rest = [k for k in owner[6] if k != code]
        # Убираем одну клавишу, остальные оставляем: у KRunner их три, и Alt+F2 должен остаться.
        #
        # Порядок в actionId — [составляющая, действие, её подпись, его подпись], и он не
        # украшение: с переставленными подписями kglobalaccel молча ничего не делает и отвечает
        # успехом. Так голая Meta осталась за plasmashell при отчёте «клавиша наша».
        keys = "@ai [" + ", ".join(str(k) for k in rest) + "]"
        _accel("setShortcut", f"['{component}','{action}','{comp_friendly}','{friendly}']", keys, "4")
        taken.append(friendly or component)
    return taken


def claim_key(combo: str, component: str, friendly: str) -> None:
    """Повесить клавишу на нашу запись живьём — иначе она сработает только после перезахода."""
    code = key_code(combo)
    if code is not None:
        _accel("setShortcut", f"['{component}','_launch','{friendly}','{friendly}']",
               f"@ai [{code}]", "4")


def key_is_ours(combo: str, component: str) -> bool:
    """Держим ли мы эту клавишу на самом деле. Единственная проверка, которой стоит верить:
    записи в файле хватает ровно до первого соседа, который занял ту же клавишу."""
    code = key_code(combo)
    return code is not None and any(o[2] == component for o in shortcut_owners(code))


def hotkeys() -> dict:
    """Что сейчас назначено. `extra` — вторая клавиша «говорить» (кнопка мыши)."""
    out = {}
    for name, _, _ in HOTKEYS:
        keys = _shortcut(_hotkey_id(name)) or [""]
        out[name] = keys[0]
        if name == "talk":
            out["extra"] = keys[1] if len(keys) > 1 else ""
    return out


def hotkey_list() -> list[dict]:
    """Таблица для настроек: имя, подпись, что назначено, что было бы по умолчанию и — главное —
    держим ли мы эту клавишу на самом деле. Запись в файле ничего не значит, если её занял сосед."""
    now = hotkeys()
    out = []
    for name, label, default in HOTKEYS:
        key = now.get(name, "")
        out.append({"name": name, "label": label, "key": key, "default": default,
                    "live": bool(key) and key_is_ours(key, _hotkey_id(name)),
                    "taken_by": [o[1] for o in shortcut_owners(key_code(key) or 0)
                                 if o[2] != _hotkey_id(name)] if key else []})
    return out


def set_hotkeys(*args: str | None, **named: str | None) -> dict:
    """Назначить клавиши. Не названное остаётся как было, пустая строка — снять клавишу.

    Позиционные аргументы приняты ради старого порядка (talk, extra, cancel, type, yes, no):
    его ждут `justday hotkey` и настройки островка."""
    order = ("talk", "extra", "cancel", "type", "yes", "no")
    given = {name: value for name, value in zip(order, args) if value is not None}
    given.update({k: v for k, v in named.items() if v is not None})
    now = hotkeys()
    argv: list[str] = []
    for name, _, default in HOTKEYS:
        value = given.get(name, now.get(name) or default)
        argv += [f"--{name}", value]
    argv += ["--extra", given.get("extra", now.get("extra", ""))]
    script = config.REPO_DIR / "scripts" / "setup-hotkey.sh"
    p = subprocess.run([str(script), *argv], capture_output=True, text=True)

    # Скрипт написал файлы и создал записи. Теперь самое важное: убедиться, что клавиша
    # действительно наша. Занята кем-то — отобрать и повесить заново, иначе привязка есть только
    # на бумаге, а нажатие уходит соседу.
    # Клавиша, которая уже наша, — не трогается вовсе. Это не экономия: у «говорить» их две
    # (Meta+J и F19 с кнопки мыши), и переустановка одной стёрла бы вторую.
    taken: dict[str, list[str]] = {}
    live: dict[str, bool] = {}
    # Скрипт снимает и вешает записи заново, и пока KWin это переваривает, он честно отвечает
    # «клавиша ничья». Ждём, пока уляжется, а не спрашиваем сразу: иначе проверка соврёт про всё.
    first = next(((n, given.get(n, now.get(n) or d), _hotkey_id(n))
                  for n, _, d in HOTKEYS if given.get(n, now.get(n) or d)), None)
    for _ in range(20):
        if first is None or key_is_ours(first[1], first[2]):
            break
        time.sleep(0.25)

    for name, label, default in HOTKEYS:
        key = given.get(name, now.get(name) or default)
        if not key:
            continue
        component = _hotkey_id(name)
        # Always strip co-owners first (KRunner shares Alt+Space; plasmashell Meta). Skipping
        # free_key when we already appear in the owner list left the neighbour holding the key
        # and `hotkey get` showed ✔ ← занято. Do not claim_key if we already own it: talk has
        # two chords (Meta+J + mouse F19) and reclaiming one would wipe the other.
        if (was := free_key(key, component)):
            taken[key] = was
        if key_is_ours(key, component):
            live[name] = True
            continue
        claim_key(key, component, f"JustDay: {label.lower()}")
        live[name] = key_is_ours(key, component)
    return {"ok": p.returncode == 0, "output": (p.stdout + p.stderr).strip(),
            "taken_from": taken, "live": live, **hotkeys()}


def models() -> dict:
    b = config.load()["brain"]
    out = []
    for name, p in providers.PROVIDERS.items():
        has_key = True if not p.get("secret") else bool(providers.secret_get(p["secret"]))
        item = {"id": name, "desc": p["desc"], "needs_key": bool(p.get("secret")), "has_key": has_key,
                "suggested": MODELS.get(name, [])}
        if p.get("cloud_signin"):
            item["account"] = providers.cloud_account()
        out.append(item)
    return {"current": {"provider": b.get("provider", "claude"), "model": b["model"], "base_url": b.get("base_url", ""),
                        "effort": b.get("effort", "low")}, "providers": out}


def local_models() -> list[str]:
    ollama = config.DATA_DIR / "ollama" / "bin" / "ollama"
    if not ollama.exists():
        return []
    p = subprocess.run([str(ollama), "list"], capture_output=True, text=True, env={"OLLAMA_HOST": "127.0.0.1:11434"})
    names = [line.split()[0] for line in p.stdout.splitlines()[1:] if line.strip() and not line.startswith("hf.co/")]
    return [n for n in names if not n.endswith("cloud")]  # `…:cloud` run on ollama.com, not on this GPU


def memory_files() -> dict:
    from .brain import BRAIN_DIR
    from .cli import memory_dir

    mem = memory_dir()
    files = []
    for f in sorted(mem.glob("*.md")) if mem.exists() else []:
        if f.name == "MEMORY.md":
            continue
        text = f.read_text(encoding="utf-8", errors="replace")
        body = text.split("---", 2)[-1].strip() if text.startswith("---") else text
        desc = next((l.split(":", 1)[1].strip() for l in text.splitlines() if l.startswith("description:")), "")
        files.append({"file": str(f), "name": f.stem, "description": desc, "body": body[:600]})
    journal = config.EVENTS_FILE
    return {"dir": str(mem), "profile": str(BRAIN_DIR / "CLAUDE.md"), "files": files,
            "journal": str(journal), "journal_kb": round(journal.stat().st_size / 1024) if journal.exists() else 0}


def new_memory(title: str, text: str) -> dict:
    """A note the user writes by hand, in Claude Code's auto-memory format (+ index line in MEMORY.md)."""
    import re
    import time

    from .cli import memory_dir

    mem = memory_dir()
    mem.mkdir(parents=True, exist_ok=True)
    slug = re.sub(r"[^a-z0-9а-яё]+", "-", title.lower()).strip("-")[:40] or f"note-{int(time.time())}"
    path = mem / f"user_{slug}.md"
    path.write_text(f"---\nname: {slug}\ndescription: {title}\nmetadata:\n  type: user\n---\n\n{text.strip()}\n",
                    encoding="utf-8")
    index = mem / "MEMORY.md"
    line = f"- [{title}]({path.name}) — добавлено вручную в настройках"
    old = index.read_text(encoding="utf-8") if index.exists() else ""
    if path.name not in old:
        index.write_text(old.rstrip("\n") + ("\n" if old else "") + line + "\n", encoding="utf-8")
    return {"ok": True, "file": str(path)}


def trash(path: str) -> dict:
    """Move to the desktop trash (recoverable) — used for "forget" actions."""
    p = Path(path)
    if not p.exists():
        return {"ok": False, "error": "нет файла"}
    r = subprocess.run(["gio", "trash", str(p)], capture_output=True, text=True)
    return {"ok": r.returncode == 0, "error": r.stderr.strip()}


def forget_memory(path: Path) -> dict:
    """Trash a memory note and drop its line from the MEMORY.md index, so the model is not pointed at a missing file."""
    r = trash(str(path))
    index = path.parent / "MEMORY.md"
    if r["ok"] and index.exists():
        lines = index.read_text(encoding="utf-8").splitlines(keepends=True)
        kept = [line for line in lines if f"]({path.name})" not in line]
        if len(kept) != len(lines):
            index.write_text("".join(kept), encoding="utf-8")
    return r


def autostart(state: str | None = None) -> dict:
    units = [u for u in SERVICES if (Path.home() / ".config/systemd/user" / u).exists()]
    if state in ("on", "off"):
        subprocess.run(["systemctl", "--user", "enable" if state == "on" else "disable", *units], capture_output=True)
    enabled = subprocess.run(["systemctl", "--user", "is-enabled", "justday.service"], capture_output=True, text=True).stdout.strip()
    return {"enabled": enabled == "enabled"}


def services() -> list[dict]:
    out = []
    for u in SERVICES:
        state = subprocess.run(["systemctl", "--user", "is-active", u], capture_output=True, text=True).stdout.strip()
        out.append({"unit": u, "active": state == "active", "state": state})
    return out


def doctor() -> list[dict]:
    from . import cli

    results = []
    for name, fn in cli.TESTS.items():
        if name in ("llm", "mcp", "mic", "tts", "stt"):  # slow, model-loading or billed checks stay in the terminal doctor
            continue
        try:
            results.append({"name": name, "ok": True, "detail": fn() or ""})
        except Exception as e:
            results.append({"name": name, "ok": False, "detail": str(e)})
    return results


def about() -> dict:
    claude = shutil.which(config.load()["brain"]["claude_cli"])
    cv = subprocess.run([claude, "--version"], capture_output=True, text=True).stdout.strip() if claude else ""
    return {"version": app_version(), "repo": str(config.REPO_DIR), "claude": cv,
            "manual": str(config.REPO_DIR / "docs" / "MANUAL.md"), "config": str(config.CONFIG_FILE)}


def overview() -> dict:
    """Everything the Settings window shows on open, in one call."""
    cfg = config.load()
    return {"config": cfg, "voices": voices(), "devices": audio_devices(), "hotkeys": hotkeys(), "models": models(),
            "local_models": local_models(), "mail_password": bool(providers.secret_get("mail")),
            "calendar": len(__import__("justday.calendar_lane", fromlist=["urls"]).urls()),
            "memory": memory_files(), "autostart": autostart(), "services": services(), "about": about(),
            "guard": guard()}


GUARD_UNIT = "justday-guard.service"


def guard(action: str = "status") -> dict:
    """Предупреждение перед выключением компьютера.

    Служба ничего не рисует сама: она берёт у logind блокирующую задержку, и окно выхода
    KDE показывает её причину вместе с кнопкой «всё равно выключить». Поэтому включение —
    это ровно enable/disable пользовательской службы."""
    unit_dir = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "systemd/user"
    if action in ("on", "off"):
        if action == "on":
            unit_dir.mkdir(parents=True, exist_ok=True)
            (unit_dir / GUARD_UNIT).write_text(
                (config.REPO_DIR / "systemd" / GUARD_UNIT).read_text(encoding="utf-8"), encoding="utf-8")
            subprocess.run(["systemctl", "--user", "daemon-reload"], capture_output=True, timeout=20)
        subprocess.run(["systemctl", "--user", "enable" if action == "on" else "disable", "--now", GUARD_UNIT],
                       capture_output=True, timeout=30)
    state = subprocess.run(["systemctl", "--user", "is-active", GUARD_UNIT],
                           capture_output=True, text=True, timeout=10).stdout.strip()
    return {"on": state == "active", "unit": GUARD_UNIT, "state": state}
