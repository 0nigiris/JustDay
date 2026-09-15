"""Backend of the Settings window and the setup wizard: everything returns plain JSON-able data."""
from __future__ import annotations

import json
import re
import shutil
import subprocess
from importlib.metadata import PackageNotFoundError, version as pkg_version
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
    # free tool-capable models listed by openrouter.ai/api/v1/models (Sept 2026); the list changes over time
    "openrouter": ["nvidia/nemotron-3-super-120b-a12b:free", "google/gemma-4-31b-it:free", "nvidia/nemotron-3.5-lightning:free"],
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
            "neural": items, "silero": VOICES}


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


def hotkeys() -> dict:
    talk, cancel = _shortcut("net.local.justday.desktop"), _shortcut("net.local.justday-stop.desktop")
    return {"talk": talk[0] if talk else "", "extra": talk[1] if len(talk) > 1 else "", "cancel": cancel[0] if cancel else ""}


def set_hotkeys(talk: str, extra: str, cancel: str) -> dict:
    script = config.REPO_DIR / "scripts" / "setup-hotkey.sh"
    p = subprocess.run([str(script), "--talk", talk, "--extra", extra, "--cancel", cancel], capture_output=True, text=True)
    return {"ok": p.returncode == 0, "output": (p.stdout + p.stderr).strip(), **hotkeys()}


def models() -> dict:
    b = config.load()["brain"]
    out = []
    for name, p in providers.PROVIDERS.items():
        has_key = True if not p.get("secret") else bool(providers.secret_get(p["secret"]))
        out.append({"id": name, "desc": p["desc"], "needs_key": bool(p.get("secret")), "has_key": has_key,
                    "suggested": MODELS.get(name, [])})
    return {"current": {"provider": b.get("provider", "claude"), "model": b["model"], "base_url": b.get("base_url", ""),
                        "effort": b.get("effort", "low")}, "providers": out}


def local_models() -> list[str]:
    ollama = config.DATA_DIR / "ollama" / "bin" / "ollama"
    if not ollama.exists():
        return []
    p = subprocess.run([str(ollama), "list"], capture_output=True, text=True, env={"OLLAMA_HOST": "127.0.0.1:11434"})
    return [line.split()[0] for line in p.stdout.splitlines()[1:] if line.strip() and not line.startswith("hf.co/")]


def memory_files() -> dict:
    from .cli import memory_dir
    from .brain import BRAIN_DIR

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
        except Exception as e:  # noqa: BLE001 — every failure is a row in the report
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
            "memory": memory_files(), "autostart": autostart(), "services": services(), "about": about()}
