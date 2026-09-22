"""Everything the Dynamic Island is told about: the settings it shows, the icon for a tool call,
the last requests with their answers — and the words Whisper should expect from this user."""
from __future__ import annotations

import json
import re
import subprocess
from datetime import datetime

from . import config


def tool_icon(name: str, inp: str) -> str:
    """Freedesktop icon name for a tool call, shown next to it in the Dynamic Island."""
    if name.startswith("mcp__claude-in-chrome"):
        return "internet-web-browser"
    if name.endswith("__look") or name.endswith("screenshot"):
        return "view-preview"
    if name.startswith("mcp__plugin_justday_kwin"):
        return "input-mouse"
    if name in ("WebSearch", "WebFetch"):
        return "system-search"
    if name in ("Read", "Edit", "Write", "Glob", "Grep"):
        return "document-edit" if name in ("Edit", "Write") else "document-open"
    if name in ("Agent", "Task"):
        return "applications-development"
    if name == "Skill":
        return "games-hint"
    if name == "Bash":
        cmd = inp.lower()
        for needle, icon in (("justday play", "media-playback-start"), ("justday video", "video-x-generic"),
                             ("justday player", "media-playback-start"), ("youtube", "youtube"), ("yt-dlp", "youtube"),
                             ("justday claude", "applications-development"), ("jii ", "system-software-install"),
                             ("justday studio", "applications-graphics"), ("justday games", "applications-games"),
                             ("steam", "steam"), ("justday apps", "application-x-executable"),
                             ("justday windows", "preferences-system-windows"), ("xdg-open http", "internet-web-browser"),
                             ("playerctl", "media-playback-start"), ("wpctl", "audio-volume-high"), ("git ", "git"),
                             ("kitty", "utilities-terminal"), ("plocate", "system-search"), ("fd ", "system-search")):
            if needle in cmd:
                return icon
        return "utilities-terminal"
    return "system-run"


def vocabulary(cfg: dict) -> str:
    """Whisper hint: the words this user says that a generic model gets wrong. Kept short (prompt ≤ ~224 tokens)."""
    from . import contacts

    words = [cfg["user"]["assistant_name"], *cfg["user"].get("assistant_aliases", [])]
    for c in contacts.load():
        words += [c.get("name", ""), *c.get("aliases", [])]
    words += [k for k in cfg["apps"]["aliases"]]
    base = cfg["stt"].get("initial_prompt", "")
    seen, extra = set(base.lower().replace(",", " ").split()), []
    for w in words:
        if w and w.lower() not in seen:
            seen.add(w.lower())
            extra.append(w)
    return (base.rstrip(". ") + ", " + ", ".join(extra[:40]) + ".") if extra else base


def settings_snapshot(cfg: dict) -> dict:
    b, m = cfg["brain"], cfg["mail"]
    return {"provider": b.get("provider", "claude"), "model": b["model"], "assistant_name": cfg["user"]["assistant_name"],
            "language": cfg["user"].get("language", "ru"),
            "earcons": cfg["audio"]["earcons"], "notifications": cfg["ui"]["notifications"],
            "wakeword": cfg["wakeword"]["enabled"], "mail": bool(m["address"]), "mail_announce": m["announce"],
            "accessibility": cfg["desktop"]["accessibility"], "island": cfg["island"],
            "microphone": cfg["audio"].get("microphone", True),
            "voice": cfg["tts"]["engine"] != "none" and not cfg["tts"].get("muted"),
            "mute_in_games": cfg["tts"].get("mute_in_games", True),
            "volume": int(cfg["audio"].get("volume", 100)),
            "tts_engine": cfg["tts"]["engine"], "tts_previous": cfg["tts"].get("previous_engine", ""),
            "hotkeys": _hotkeys(), "media": cfg["media"]}


def _hotkeys() -> dict:
    from . import manage

    try:
        return manage.hotkeys()
    except (OSError, subprocess.SubprocessError):
        return {}


# Text selected on screen is attached to a typed request; the list of recent requests shows what the
# person actually asked, not the page they had open.
ATTACHED = re.compile(r"\n\n\[Текст, выделенный пользователем.*", re.S)


def recent_history(limit: int = 6) -> list[dict]:
    """Last requests with their spoken answers, for the expanded island."""
    try:
        with config.EVENTS_FILE.open("rb") as f:
            f.seek(0, 2)
            f.seek(max(0, f.tell() - 200_000))
            lines = f.read().decode("utf-8", "replace").splitlines()[1:]
    except OSError:
        return []
    def said_soon_after(request_ts: str, say_ts: str) -> bool:
        """A request that was interrupted has no answer: what is spoken an hour later (an alarm, new mail)
        belongs to nobody, and must not be shown as its reply."""
        try:
            return abs(datetime.fromisoformat(say_ts) - datetime.fromisoformat(request_ts)).total_seconds() <= 300
        except ValueError:
            return True

    out: list[dict] = []
    for line in lines:
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            continue
        if e.get("kind") == "request" and e.get("source") != "event":
            out.append({"ts": e.get("ts", "")[11:16], "q": ATTACHED.sub("", e.get("text", "")).strip(), "a": "",
                        "at": e.get("ts", "")})
        elif e.get("kind") == "fast" and e.get("text"):
            out.append({"ts": e.get("ts", "")[11:16], "q": ATTACHED.sub("", e["text"]).strip(), "a": e.get("desc", ""),
                        "at": e.get("ts", "")})
        elif e.get("kind") == "say" and out and not out[-1]["a"] and said_soon_after(out[-1]["at"], e.get("ts", "")):
            out[-1]["a"] = e.get("text", "")
    return [{k: v for k, v in r.items() if k != "at"} for r in out[-limit:][::-1]]
