"""Configuration: built-in defaults overlaid with ~/.config/justday/config.toml."""
from __future__ import annotations

import copy
import json
import os
import re
import tomllib
from pathlib import Path

HOME = Path.home()
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config")) / "justday"
DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", HOME / ".local/share")) / "justday"
STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", HOME / ".local/state")) / "justday"
RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
SOCKET_PATH = RUNTIME_DIR / "justday.sock"
CONFIG_FILE = CONFIG_DIR / "config.toml"
EVENTS_FILE = STATE_DIR / "events.jsonl"
STATE_FILE = STATE_DIR / "state.json"
# The repository this package was installed from (editable install) — holds persona + plugin.
REPO_DIR = Path(__file__).resolve().parents[2]

SECRETS_FILE = CONFIG_DIR / "secrets.env"


def secret(name: str) -> str:
    """An API key from the environment, or from ~/.config/justday/secrets.env (KEY=value, mode 600).

    Keys are never written to config.toml, never logged and never handed to the model."""
    got = os.environ.get(name, "")
    if got:
        return got.strip()
    try:
        for line in SECRETS_FILE.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == name:
                return value.strip().strip("'\"")
    except OSError:
        pass
    return _mcp_secret(name)


def _mcp_secret(name: str) -> str:
    """A key an MCP server in ~/.claude.json already holds — no reason to ask for the same key twice."""
    import json as jsonlib

    try:
        servers = jsonlib.loads((HOME / ".claude.json").read_text(encoding="utf-8")).get("mcpServers") or {}
    except (OSError, ValueError):
        return ""
    for server in servers.values():
        got = ((server or {}).get("env") or {}).get(name)
        if got:
            return str(got).strip()
    return ""


def set_secret(name: str, value: str) -> None:
    """Store a key in secrets.env with owner-only permissions (or drop it when value is empty)."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    lines = []
    try:
        lines = [ln for ln in SECRETS_FILE.read_text(encoding="utf-8").splitlines() if not ln.startswith(f"{name}=")]
    except OSError:
        pass
    if value:
        lines.append(f"{name}={value}")
    SECRETS_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    SECRETS_FILE.chmod(0o600)


DEFAULTS: dict = {
    # assistant_name: how the assistant calls itself and what you call it (also a hint for speech recognition)
    "user": {"name": "", "address_as": "сэр", "assistant_name": "Джарвис", "assistant_aliases": ["JustDay"],
             "language": "ru"},  # ru | en — assistant replies, voice lines and the island
    "audio": {
        # Substring of a PipeWire source node name; empty = system default source.
        "microphone": True,  # false = keyboard only: no mic, no wake word, speech recognition never loads
        "input": "",
        "output": "",
        "earcons": True,
        "max_utterance_seconds": 40,
        "silence_seconds": 1.0,
        "no_speech_timeout_seconds": 7,
        # After JustDay asks a question, listen again automatically for this long (0 = off).
        "followup_seconds": 6,
        # two presses of the talk key within this time = cancel everything (0 = off)
        "double_tap_seconds": 0.35,
    },
    "stt": {
        "model": "large-v3-turbo",
        "device": "cuda",
        "compute_type": "int8_float16",
        "language": "ru",
        "initial_prompt": "Джарвис, JustDay, Claude Code, YouTube, Discord, Steam, Proton, GitHub, KDE, Helium, VS Code.",
    },
    "tts": {
        "engine": "silero",  # qwen (neural, justday-voice service) | elevenlabs | silero | espeak | none
        "voice": "jarvis",  # neural voice id: built-in jarvis, friday, or one you designed/cloned
        "neural_quality": "fast",  # fast (0.6B, ~2.5 GB VRAM) | best (1.7B, ~4.5 GB VRAM)
        "silero_model_url": "https://models.silero.ai/models/tts/ru/v5_5_ru.pt",
        "speaker": "eugene",
        "sample_rate": 48000,
        "speed": 1.15,  # 1.0 = as the model speaks; 1.1–1.3 sounds like a person in a hurry
        "latin": "auto",  # auto = spell English the Russian way only for voices that cannot read it (silero, espeak)
        "numbers": True,  # say figures as words: «7:05» → «семь ноль пять», «3,5 ГБ» → «три с половиной гигабайта»
        # ElevenLabs (engine = "elevenlabs"): the key lives in ~/.config/justday/secrets.env, never here.
        "eleven_voice": "JBFqnCBsd6RMkjVDRZzb",  # `justday voice eleven` lists the voices on your account
        "eleven_model": "eleven_flash_v2_5",  # flash = fastest; eleven_multilingual_v2 = richer, slower
        "previous_engine": "",  # remembered when voice replies are switched off
    },
    # names = also wake on the assistant's names («Джарвис», «JustDay»), read by Whisper on the start of each phrase
    # wake_names: which names wake it (empty = the assistant name only)
    "wakeword": {"enabled": False, "names": True, "wake_names": [], "model": "hey_jarvis", "threshold": 0.5},
    "brain": {
        # claude | ollama | openrouter | deepseek | custom — see `justday model list`
        "provider": "claude",
        "base_url": "",  # only for provider = "custom"
        "context_tokens": 0,  # model context window for non-Claude providers (0 = provider default)
        "model": "sonnet",
        "effort": "low",
        "permission_mode": "auto",
        "chrome": True,
        # Resume the previous conversation if it was active within this many hours.
        "resume_within_hours": 12,
        "claude_cli": "claude",
    },
    "workers": {
        "model": "",  # empty = user's Claude Code default
        "permission_mode": "auto",
        "poll_seconds": 15,
        "auto_review": True,
    },
    "ui": {"notifications": True},
    "updates": {"check": True, "interval_hours": 6},
    # personal voice profile (Settings → Голос и звук → «Настроить под мой голос»)
    "voiceprint": {"mode": "off"},  # off | wake (only wake word / follow-ups must be you) | always
    # Dynamic Island look & feel (applied live)
    "island": {
        "animations": "spring",  # spring (Apple-like bounce) | smooth | off
        "hover_reveal": True,  # hover the top edge to show the island
        "show_weather": True,
        "show_events": True,  # last answer / new mail / Claude status in the hover view
        "show_notifications": True,  # mirror desktop notifications on the island (they never leave the computer)
        "city": "",  # weather location; empty = no weather requests at all
        "screen": "",  # monitor name (e.g. DP-2); empty = the one at the top-left
    },
    # Accessibility bus on: Qt/GTK apps expose their buttons, so `look` can mark them for exact clicks.
    "desktop": {"accessibility": True},
    # Local model for private data (mail). Ollama listens on localhost only.
    "local_llm": {"url": "http://127.0.0.1:11434", "model": "qwen3.5:9b", "num_ctx": 16384, "keep_alive": "10m"},
    "mail": {
        "address": "",
        "imap_host": "imap.gmail.com",
        "smtp_host": "smtp.gmail.com",
        # Gmail search syntax: Primary = what a person wrote; the rest is only counted
        "query": "category:primary is:unread newer_than:7d",
        "other_query": "is:unread newer_than:7d -category:primary",
        "max_letters": 8,
        "announce": True,  # say "новое письмо от …" when important mail arrives
        "poll_seconds": 180,
    },
    # Local creative studio (justday studio): ComfyUI is found automatically; empty = auto
    "studio": {"comfy_dir": "", "python": "", "url": "", "rmbg_dir": "", "free_after": True},
    # Own player: music from YouTube is downloaded to ~/Music/JustDay/YouTube and plays in a background mpv.
    # video_where: ask | island | window | browser — where "включи видео …" plays
    # duck: the music gets quieter while the assistant listens or speaks
    "media": {"video_where": "ask", "volume": 70, "duck": True, "show_player": True},
    # Spoken name → desktop id, checked first by the instant path (e.g. "дискорд" = "org.equicord.equibop").
    "apps": {"aliases": {}},
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load() -> dict:
    cfg = DEFAULTS
    if CONFIG_FILE.exists():
        with CONFIG_FILE.open("rb") as f:
            cfg = _merge(DEFAULTS, tomllib.load(f))
    return cfg


def _toml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    return json.dumps(str(v), ensure_ascii=False)


def set_value(section: str, key: str, value) -> None:
    """Set one key in config.toml, keeping the user's comments and layout."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    lines = CONFIG_FILE.read_text(encoding="utf-8").splitlines() if CONFIG_FILE.exists() else []
    line = f"{key} = {_toml_value(value)}"
    header = f"[{section}]"
    try:
        start = next(i for i, l in enumerate(lines) if l.strip() == header)
    except StopIteration:
        lines += ["", header, line]
    else:
        end = next((i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("[")), len(lines))
        for i in range(start + 1, end):
            if re.match(rf"\s*{re.escape(key)}\s*=", lines[i]):
                lines[i] = line
                break
        else:
            lines.insert(start + 1, line)
    CONFIG_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def ensure_dirs() -> None:
    for d in (CONFIG_DIR, DATA_DIR, STATE_DIR):
        d.mkdir(parents=True, exist_ok=True)
