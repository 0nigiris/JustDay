"""Lightweight Spotlight-like file index for the JustDay menu.

Not a full-disk indexer. Sources, in order:
  1. XDG / KDE recently-used files (desktop.recent) — instant, already on disk
  2. A shallow scan of common home directories (Documents, Downloads, …),
     cached under STATE_DIR and refreshed every few minutes
  3. Optional plocate / fd for deeper hits when the user typed a query

The menu and the voice assistant then share one search path: apps already come
from .desktop entries; files come from here.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from . import config, desktop

INDEX_FILE = config.STATE_DIR / "file-index.json"
INDEX_TTL = 900.0          # seconds before a quiet rebuild (was 180; 1.8MB rewrite stuttered UI)
INDEX_MAX = 8000           # hard cap — enough for a home tree tip, not a Steam library
SEARCH_DEPTH = 4
SKIP_DIR_NAMES = {
    "node_modules", ".git", ".cache", ".venv", "venv", "__pycache__",
    ".tox", ".mypy_cache", ".pytest_cache", "dist", "build",
    ".local", ".var", ".npm", ".yarn", ".pnpm-store", ".bun", ".cargo", ".rustup",
    ".spicetify", ".steam", ".thumbnails", ".Trash", "Trash",
    "Steam", "steamapps", "Proton", "lutris", "target",  # rust build
}
# Path fragments that mean "noise" even when plocate finds them under $HOME.
NOISE_PATH_PARTS = (
    "/node_modules/", "/.cache/", "/.bun/", "/.npm/", "/.yarn/", "/.pnpm-store/",
    "/.local/share/Steam/", "/.var/app/", "/.cargo/registry/", "/.rustup/",
    "/.spicetify/", "/__pycache__/", "/.git/", "/target/debug/", "/target/release/",
    "/.venv/", "/venv/", "/.tox/",
)
SKIP_NAME_PREFIXES = (".",)
COMMON_DIRS = (
    "Desktop", "Documents", "Downloads", "Pictures", "Videos", "Music",
    "Projects", "projects", "src", "code", "dev", "Development", "repos", "git",
    "Work", "work", "Notes", "notes",
)

_cache: dict | None = None
_cache_at = 0.0


def _home() -> Path:
    return Path.home()


def _flat(text: str) -> str:
    return str(text or "").lower().replace("ё", "е")



def _noisy(path: str) -> bool:
    p = path.replace("\\", "/")
    if any(part in p for part in NOISE_PATH_PARTS):
        return True
    # Dot-dir segment anywhere except a few allowlisted ones.
    parts = Path(p).parts
    for part in parts:
        if part in SKIP_DIR_NAMES:
            return True
    return False


def _icon_for(path: Path) -> str:
    if path.is_dir():
        return "folder"
    ext = path.suffix.lower()
    if ext in {".png", ".jpg", ".jpeg", ".gif", ".webp", ".svg", ".bmp"}:
        return "image-x-generic"
    if ext in {".mp3", ".flac", ".ogg", ".wav", ".m4a"}:
        return "audio-x-generic"
    if ext in {".mp4", ".mkv", ".webm", ".avi", ".mov"}:
        return "video-x-generic"
    if ext in {".pdf"}:
        return "application-pdf"
    return "text-x-generic"


def _row(path: str, *, name: str = "", sub: str = "") -> dict | None:
    try:
        p = Path(path).expanduser()
        if not p.exists():
            return None
        if _noisy(str(p)):
            return None
        # Resolve only for existence; keep the user-facing path compact.
        path = str(p)
        name = name or p.name or path
        parent = str(p.parent).replace(str(_home()), "~", 1) if p.parent else ""
        return {
            "kind": "file",
            "id": path,
            "name": name,
            "icon": _icon_for(p),
            "sub": sub or parent,
            "dir": p.is_dir(),
        }
    except OSError:
        return None


def _should_skip(name: str) -> bool:
    if name in SKIP_DIR_NAMES:
        return True
    if name.startswith(SKIP_NAME_PREFIXES) and name not in {".config", ".local"}:
        # Still skip most dotdirs; .config / .local are handled by not walking them deep.
        return name not in {".config"}
    return False


def _walk_root(root: Path, depth: int, out: list[dict], budget: list[int]) -> None:
    if budget[0] <= 0 or depth < 0 or not root.is_dir():
        return
    try:
        entries = list(os.scandir(root))
    except OSError:
        return
    for ent in entries:
        if budget[0] <= 0:
            return
        name = ent.name
        if _should_skip(name):
            continue
        try:
            is_dir = ent.is_dir(follow_symlinks=False)
            is_file = ent.is_file(follow_symlinks=False)
        except OSError:
            continue
        if not is_dir and not is_file:
            continue
        # Don't index the whole of ~/.config — only keep top-level names when asked.
        path = ent.path
        row = _row(path, name=name)
        if row:
            out.append(row)
            budget[0] -= 1
        if is_dir and depth > 0:
            # Never descend into ~/.cache / Steam / huge trees even if listed.
            if name in {".cache", ".local", "Steam", "node_modules"}:
                continue
            _walk_root(Path(path), depth - 1, out, budget)


def rebuild() -> dict:
    """Scan common home dirs and write the cache. Safe to call from a worker thread."""
    home = _home()
    rows: list[dict] = []
    budget = [INDEX_MAX]
    seen: set[str] = set()
    for name in COMMON_DIRS:
        root = home / name
        if not root.is_dir():
            continue
        chunk: list[dict] = []
        _walk_root(root, SEARCH_DEPTH, chunk, budget)
        for row in chunk:
            if row["id"] in seen:
                continue
            seen.add(row["id"])
            rows.append(row)
    # Also tip of home itself (depth 1): loose files on the desk of the home folder.
    try:
        for ent in os.scandir(home):
            if budget[0] <= 0:
                break
            if _should_skip(ent.name) or ent.name in COMMON_DIRS:
                continue
            try:
                if not (ent.is_file(follow_symlinks=False) or ent.is_dir(follow_symlinks=False)):
                    continue
            except OSError:
                continue
            row = _row(ent.path, name=ent.name)
            if row and row["id"] not in seen:
                seen.add(row["id"])
                rows.append(row)
                budget[0] -= 1
    except OSError:
        pass

    payload = {"at": time.time(), "n": len(rows), "items": rows}
    config.STATE_DIR.mkdir(parents=True, exist_ok=True)
    try:
        tmp = INDEX_FILE.with_suffix(f".{os.getpid()}.tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        tmp.replace(INDEX_FILE)
    except OSError:
        pass
    global _cache, _cache_at
    _cache, _cache_at = payload, time.time()
    return payload


def _load() -> dict:
    global _cache, _cache_at
    now = time.time()
    if _cache is not None and now - _cache_at < INDEX_TTL:
        return _cache
    try:
        got = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
        if isinstance(got, dict) and isinstance(got.get("items"), list):
            age = now - float(got.get("at") or 0)
            _cache, _cache_at = got, now if age < INDEX_TTL else 0.0
            if age < INDEX_TTL:
                return got
    except (OSError, ValueError):
        pass
    return rebuild()


def ensure_fresh(*, force: bool = False) -> dict:
    """Rebuild if the cache is stale. Used by the daemon watchdog."""
    if force:
        return rebuild()
    try:
        got = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
        if isinstance(got, dict) and time.time() - float(got.get("at") or 0) < INDEX_TTL:
            return got
    except (OSError, ValueError):
        pass
    return rebuild()


def _score(words: list[str], name: str, path: str) -> int:
    name_f, path_f = _flat(name), _flat(path)
    best = 0
    for word in words:
        if name_f == word:
            hit = 0
        elif name_f.startswith(word):
            hit = 1
        elif any(part.startswith(word) for part in name_f.replace("-", " ").replace("_", " ").split()):
            hit = 2
        elif word in name_f:
            hit = 3
        elif word in path_f:
            hit = 5
        else:
            return 99
        best = max(best, hit)
    return best


def _recent_rows(limit: int = 40) -> list[dict]:
    try:
        got = desktop.recent(hours=72, limit=limit)
    except Exception:
        return []
    out = []
    for f in got.get("files") or []:
        row = _row(f.get("path", ""))
        if row:
            out.append(row)
    return out


def _plocate(query: str, limit: int) -> list[dict]:
    if not query.strip() or not shutil.which("plocate"):
        return []
    home = str(_home())
    try:
        raw = subprocess.run(
            ["plocate", "-i", "-l", str(max(limit * 4, 40)), "--", query],
            capture_output=True, text=True, timeout=3,
        ).stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        return []
    out = []
    for line in raw:
        line = line.strip()
        if not line.startswith(home):
            continue
        if any(f"/{skip}/" in line or line.endswith(f"/{skip}") for skip in SKIP_DIR_NAMES):
            continue
        row = _row(line)
        if row:
            out.append(row)
        if len(out) >= limit:
            break
    return out


def _fd(query: str, limit: int) -> list[dict]:
    bin_name = "fd" if shutil.which("fd") else ("fd-find" if shutil.which("fd-find") else "")
    if not query.strip() or not bin_name:
        return []
    try:
        raw = subprocess.run(
            [bin_name, "-i", "-H", "--max-depth", str(SEARCH_DEPTH + 1),
             "-E", "node_modules", "-E", ".cache", "-E", ".git", "-E", "Steam",
             "--", query, str(_home())],
            capture_output=True, text=True, timeout=4,
        ).stdout.splitlines()
    except (OSError, subprocess.SubprocessError):
        return []
    out = []
    for line in raw[: limit * 3]:
        row = _row(line.strip())
        if row:
            out.append(row)
        if len(out) >= limit:
            break
    return out


def search(query: str = "", limit: int = 24) -> list[dict]:
    """Find files for the menu / launcher. Empty query → recent files only."""
    words = [w for w in _flat(query).split() if w]
    rows: list[tuple[int, int, int, str, dict]] = []
    seen: set[str] = set()

    def add(row: dict | None, score: int) -> None:
        if not row or row["id"] in seen:
            return
        seen.add(row["id"])
        # Prefer common user dirs (Documents/Downloads/…) over deep src trees.
        path_f = row["id"].replace(str(_home()), "~", 1)
        depth = path_f.count("/")
        prefer = 0
        for tip in ("~/Desktop", "~/Documents", "~/Downloads", "~/Pictures",
                    "~/Videos", "~/Music", "~/Projects", "~/projects", "~/Notes"):
            if path_f.startswith(tip):
                prefer = -1
                break
        rows.append((score, prefer, depth, _flat(row["name"]), row))

    # Recent always — Spotlight shows what you touched.
    for row in _recent_rows(limit=40):
        score = _score(words, row["name"], row["id"]) if words else 1
        if score < 99:
            add(row, score)

    if words:
        idx = _load()
        for row in idx.get("items") or []:
            score = _score(words, row.get("name", ""), row.get("id", ""))
            if score < 99:
                add(row, score)
        # Top up with system indexes when the typed query is real.
        if len(rows) < limit:
            for row in _plocate(" ".join(words), limit):
                score = _score(words, row["name"], row["id"])
                if score < 99:
                    add(row, score)
        if len(rows) < max(4, limit // 2):
            for row in _fd(words[0], limit):
                score = _score(words, row["name"], row["id"])
                if score < 99:
                    add(row, score)
    else:
        # Empty query: a short recent strip, not the whole index.
        pass

    rows.sort(key=lambda r: (r[0], r[1], r[2], r[3]))
    return [r for *_, r in rows[:limit]]


def open_path(path: str) -> dict:
    """Open a file or folder with the desktop default (xdg-open)."""
    p = Path(path).expanduser()
    if not p.exists():
        return {"ok": False, "error": "файл не найден", "path": str(p)}
    cmd = ["xdg-open", str(p)]
    try:
        subprocess.Popen(
            desktop.detached(cmd), start_new_session=True,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        return {"ok": True, "kind": "file", "id": str(p), "name": p.name}
    except OSError as e:
        return {"ok": False, "error": str(e), "path": str(p)}


def stats() -> dict:
    got = _load()
    return {
        "indexed": int(got.get("n") or len(got.get("items") or [])),
        "at": got.get("at"),
        "plocate": bool(shutil.which("plocate")),
        "fd": bool(shutil.which("fd") or shutil.which("fd-find")),
        "file": str(INDEX_FILE),
    }
