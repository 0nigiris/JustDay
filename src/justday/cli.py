"""`justday` command: control the daemon, helper commands used by the brain, diagnostics."""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

from . import config


def _print(obj) -> None:
    print(obj if isinstance(obj, str) else json.dumps(obj, ensure_ascii=False, indent=2))


def control(cmd: str, timeout: float | None = 10, **kw) -> dict:
    s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    s.settimeout(timeout)
    try:
        s.connect(str(config.SOCKET_PATH))
    except (FileNotFoundError, ConnectionRefusedError):
        return {"ok": False, "error": "daemon is not running (systemctl --user start justday)"}
    s.sendall((json.dumps({"cmd": cmd, **kw}, ensure_ascii=False) + "\n").encode())
    buf = b""
    while not buf.endswith(b"\n"):
        chunk = s.recv(65536)
        if not chunk:
            break
        buf += chunk
    return json.loads(buf.decode() or '{"ok": false}')


# ---------------- diagnostics ----------------
def _check(name: str, fn) -> bool:
    t = time.monotonic()
    try:
        detail = fn()
        print(f"  ✔ {name:<14} {detail or ''}  ({time.monotonic() - t:.1f}s)")
        return True
    except Exception as e:
        print(f"  ✘ {name:<14} {e}")
        return False


def t_mic(seconds: float = 3.0):
    import numpy as np

    from . import audio

    cfg = config.load()
    src = audio.find_node(cfg["audio"]["input"]) if cfg["audio"]["input"] else None
    if cfg["audio"]["input"] and not src:
        raise RuntimeError(f"no PipeWire source matching '{cfg['audio']['input']}'")
    cmd = ["pw-record", "--rate", "16000", "--channels", "1", "--format", "s16", "--raw"]
    cmd += (["--target", src] if src else []) + ["-"]
    p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    time.sleep(seconds)
    p.terminate()
    pcm = np.frombuffer(p.stdout.read(), dtype=np.int16)
    if not len(pcm):
        raise RuntimeError("no audio captured")
    rms = float(np.sqrt((pcm.astype(float) ** 2).mean()))
    return f"source={src or 'default'} samples={len(pcm)} rms={rms:.0f} peak={int(abs(pcm).max())}"


def t_tts(text: str = "Все системы в норме, сэр."):
    import asyncio

    from . import audio
    from .tts import TTS, normalize

    tts = TTS(config.load()["tts"])
    pcm = tts.synth(normalize(text))
    asyncio.run(audio.Player(config.load()["audio"]["output"]).play(pcm, tts.rate))
    return f"engine={tts.cfg['engine']} speaker={tts.cfg['speaker']} {len(pcm) / tts.rate:.1f}s audio"


def t_stt():
    import numpy as np

    from .stt import STT
    from .tts import TTS, normalize

    cfg = config.load()
    tts = TTS(cfg["tts"])
    phrase = "Джарвис, открой браузер и найди видео про раст."
    pcm = tts.synth(normalize(phrase))
    pcm16k = pcm[:: max(1, tts.rate // 16000)].astype(np.int16)  # 48k → 16k decimation is fine for a smoke test
    text = STT(cfg["stt"]).transcribe(pcm16k)
    if not text:
        raise RuntimeError("empty transcription")
    return f"«{text}»"


def t_llm():
    out = subprocess.run([shutil.which("claude") or "claude", "-p", "Ответь одним словом: работаю", "--model",
                          config.load()["brain"]["model"], "--output-format", "json", "--no-session-persistence"],
                         capture_output=True, text=True, timeout=120, cwd=str(config.STATE_DIR))
    data = json.loads(out.stdout)
    if data.get("is_error"):
        raise RuntimeError(data.get("result"))
    return f"«{data['result']}» {data.get('duration_ms')}ms"


def t_mcp():
    out = subprocess.run([shutil.which("claude") or "claude", "-p", "ok", "--model", "haiku", "--output-format",
                          "stream-json", "--verbose", "--no-session-persistence", "--chrome",
                          "--plugin-dir", str(config.REPO_DIR / "plugin"), "--max-budget-usd", "0.05"],
                         capture_output=True, text=True, timeout=120, cwd=str(config.STATE_DIR))
    for line in out.stdout.splitlines():
        if '"subtype":"init"' in line:
            servers = {s["name"]: s["status"] for s in json.loads(line)["mcp_servers"]}
            bad = {k: v for k, v in servers.items() if v != "connected"}
            summary = ", ".join(f"{k}={v}" for k, v in servers.items())
            if any("kwin" in k and v != "connected" for k, v in servers.items()):
                raise RuntimeError(summary)
            return summary + ("" if not bad else "  (not connected ones need `claude` → /mcp)")
    raise RuntimeError(out.stderr[-400:] or "no init message")


def t_desktop():
    if not shutil.which("kwin-mcp"):
        raise RuntimeError("kwin-mcp not installed (uv tool install git+https://github.com/VibeProgramm/kwin-mcp)")
    wins = subprocess.run(["qdbus-qt6", "org.kde.KWin", "/KWin", "org.kde.KWin.supportInformation"],
                          capture_output=True, text=True, timeout=10)
    if wins.returncode:
        raise RuntimeError("KWin D-Bus not reachable")
    return f"kwin-mcp ok, KWin D-Bus ok, session={os.environ.get('XDG_SESSION_TYPE')}"


def t_files():
    from . import desktop

    apps = desktop.list_apps()
    rec = desktop.recent(48, 5)
    return f"{len(apps)} apps, {len(desktop.list_games())} games, {len(rec['files'])} recent files, " \
           f"{len(rec['claude_projects'])} recent Claude projects, plocate={'yes' if shutil.which('plocate') else 'no'}"


def t_browser():
    if not shutil.which("xdg-open"):
        raise RuntimeError("xdg-open missing")
    default = subprocess.run(["xdg-settings", "get", "default-web-browser"], capture_output=True, text=True).stdout.strip()
    return f"default browser={default}; Claude in Chrome status is shown by `justday test mcp`"


def t_claude():
    from . import workers

    a = workers.agents()
    return f"claude {subprocess.run(['claude', '--version'], capture_output=True, text=True).stdout.strip()}, {len(a)} sessions visible"


def t_memory():
    from .brain import BRAIN_DIR

    mem = memory_dir()
    files = list(mem.glob("*.md")) if mem.exists() else []
    return f"CLAUDE.md={'yes' if (BRAIN_DIR / 'CLAUDE.md').exists() else 'MISSING'}, memory dir={mem} ({len(files)} files)"


def t_local_llm():
    from . import localllm, providers

    cfg = config.load()
    if not localllm.available():
        raise RuntimeError(f"{cfg['local_llm']['model']} not served at {cfg['local_llm']['url']} "
                           "(systemctl --user status justday-ollama; scripts/setup-local-llm.sh)")
    b = cfg["brain"]
    providers.env(cfg)  # raises when the selected provider has no key
    return f"{cfg['local_llm']['model']} ready; brain = {b.get('provider', 'claude')}/{b['model']}"


def t_mail():
    from . import mail

    m = config.load()["mail"]
    if not m["address"]:
        return "not configured (optional): justday mail setup"
    return f"{m['address']}: {mail.count(m['query'])} unread important"


def t_software():
    import shutil

    if not shutil.which("jii"):
        return "JII not installed (optional, for «установи …»): https://github.com/0nigiris/JII"
    return subprocess.run(["jii", "--version"], capture_output=True, text=True, timeout=10).stdout.strip()


def t_daemon():
    r = control("status", timeout=5)
    if not r.get("ok"):
        raise RuntimeError(r.get("error"))
    return f"state={r['state']} model={r['model']} mic={r['mic_source']} wakeword={r['wakeword']}"


def t_hotkey():
    from .manage import hotkeys
    keys = hotkeys()
    mouse = subprocess.run(["kreadconfig6", "--file", "kcminputrc", "--group", "ButtonRebinds", "--group", "Mouse",
                            "--key", "ExtraButton1"], capture_output=True, text=True).stdout.strip()
    if not keys["talk"]:
        raise RuntimeError("global shortcut not registered (run install.sh)")
    return f"talk={keys['talk']}" + (f"+{keys['extra']}" if keys["extra"] else "") + f", cancel={keys['cancel'] or '—'}" + \
        (f", mouse ExtraButton1→{mouse}" if mouse else "")


def screenshot(all_screens: bool = False, full: bool = False) -> dict:
    """Active window (default) or all monitors → small JPEG + the mapping back to screen coordinates."""
    from . import desktop

    png, jpg = "/tmp/justday-screen.png", f"/tmp/justday-screen-{int(time.time() * 1000)}.jpg"
    subprocess.run(["spectacle", "-b", "-n", "-f", "-o", png], check=True, stderr=subprocess.DEVNULL, timeout=20)
    crop, ox, oy, title, app, ww, wh = [], 0, 0, "all monitors", "", 0, 0
    if not all_screens:
        win = desktop.windows("active")
        if win:
            w = win[0]
            ox, oy, title, app = max(0, w["x"]), max(0, w["y"]), f"{w['app']}: {w['title']}", w["app"]
            ww, wh = w["w"], w["h"]
            crop = ["-crop", f"{w['w']}x{w['h']}+{ox}+{oy}", "+repage"]
    limit = 10000 if full else (1600 if not all_screens else 1800)
    ident = subprocess.run(["magick", png, *crop, "-format", "%w", "info:"], capture_output=True, text=True).stdout
    width = int(ident.strip() or limit)
    scale = min(1.0, limit / width)
    subprocess.run(["magick", png, *crop, "-resize", f"{scale * 100:.2f}%", "-quality", "85", jpg], check=True, timeout=20)
    return {"path": jpg, "window": title, "app": app, "width": ww, "height": wh,
            "origin_x": ox, "origin_y": oy, "scale": round(scale, 4),
            "to_screen": "screen_x = origin_x + image_x / scale; screen_y = origin_y + image_y / scale"}


TESTS = {"daemon": t_daemon, "mic": t_mic, "tts": t_tts, "stt": t_stt, "llm": t_llm, "mcp": t_mcp,
         "desktop": t_desktop, "browser": t_browser, "files": t_files, "claude": t_claude, "memory": t_memory,
         "hotkey": t_hotkey, "local_llm": t_local_llm, "mail": t_mail, "software": t_software}


def memory_dir():
    import re
    from pathlib import Path

    from .brain import BRAIN_DIR

    return Path.home() / ".claude" / "projects" / re.sub(r"[^A-Za-z0-9]", "-", str(BRAIN_DIR)) / "memory"


# ---------------- entry ----------------
def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(prog="justday", description="JustDay personal desktop agent")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("daemon", help="run the voice daemon (normally via systemd)")
    sub.add_parser("toggle", help="hotkey action: start/finish listening, or interrupt speech")
    sub.add_parser("stop", help="stop speaking and interrupt the current task")
    sp = sub.add_parser("ask", help="send a text command (as if spoken)")
    sp.add_argument("text", nargs="+")
    sp.add_argument("--silent", action="store_true", help="do not speak the answer")
    sp = sub.add_parser("say", help="speak text through JustDay's voice")
    sp.add_argument("text", nargs="+")
    sub.add_parser("status")
    sub.add_parser("approve", help="allow the action JustDay is asking about")
    sub.add_parser("deny", help="deny the action JustDay is asking about")
    sp = sub.add_parser("compose", help="keyboard shortcut: open the island's text field (takes the selected text along)")
    sp.add_argument("text", nargs="*")
    sp.add_argument("--no-selection", action="store_true")
    sub.add_parser("new-session", help="forget the current conversation (memory is kept)")
    sp = sub.add_parser("logs", help="show recent events")
    sp.add_argument("-f", "--follow", action="store_true")
    sp.add_argument("-n", type=int, default=40)
    sp = sub.add_parser("doctor", help="check every component")
    sp.add_argument("--quick", action="store_true", help="skip checks that call the model")
    sp.add_argument("--json", action="store_true", help="machine-readable results (fast checks only)")
    sp = sub.add_parser("test", help="test one component")
    sp.add_argument("component", choices=sorted(TESTS))
    sp = sub.add_parser("memory", help="show where JustDay's memory lives / print it")
    sp.add_argument("action", nargs="?", choices=["path", "show", "edit", "list", "forget", "clear-journal", "read", "write", "new"],
                    default="show")
    sp.add_argument("target", nargs="?", help="memory file for `forget`")

    # helpers used by the brain
    sp = sub.add_parser("apps", help="find/launch desktop applications")
    sp.add_argument("action", choices=["find", "launch", "list"])
    sp.add_argument("query", nargs="*")
    sp = sub.add_parser("games", help="list/launch installed games (Steam, Heroic)")
    sp.add_argument("action", choices=["list", "launch"])
    sp.add_argument("query", nargs="*")
    sp = sub.add_parser("windows", help="list/focus/close/minimize windows (KWin)")
    sp.add_argument("action", choices=["list", "focus", "close", "minimize"])
    sp.add_argument("query", nargs="*")
    sp = sub.add_parser("screenshot", help="capture the screen as a small JPEG and print its path")
    sp.add_argument("--all", action="store_true", help="all monitors instead of the active window")
    sp.add_argument("--full", action="store_true", help="keep full resolution (small text)")
    sp = sub.add_parser("habits", help="what the user usually asks around this hour (for «как обычно»)")
    sp.add_argument("--hour", type=int, help="a different hour of the day (0-23)")
    sp = sub.add_parser("recent", help="recently used files and Claude Code projects")
    sp.add_argument("--hours", type=float, default=48)
    sp = sub.add_parser("claude", help="Claude Code worker sessions")
    sp.add_argument("action", choices=["start", "send", "result", "list", "stop", "open", "wait"])
    sp.add_argument("args", nargs="*")
    sp.add_argument("--cwd", default=None)
    sp.add_argument("--model", default=None)
    sp.add_argument("--timeout", type=float, default=1800)

    sp = sub.add_parser("model", help="which model drives the agent: list | status | use PROVIDER [MODEL] | signin (free Ollama cloud)")
    sp.add_argument("action", choices=["list", "status", "use", "signin"], nargs="?", default="status")
    sp.add_argument("args", nargs="*")
    sp = sub.add_parser("contacts", help="address book JustDay learns: list | find QUERY | set NAME key=value… | forget NAME")
    sp.add_argument("action", choices=["list", "find", "set", "forget"])
    sp.add_argument("args", nargs="*")
    sp = sub.add_parser("compose-mail", help="draft an e-mail locally (confirmed by the user); the address stays private")
    sp.add_argument("--to", required=True, help="contact name or alias, e.g. мама")
    sp.add_argument("--about", default="", help="what the letter should say")
    sp.add_argument("--attach", action="append", default=[], help="file to attach (repeatable)")
    sp = sub.add_parser("confirm-message", help="show a message draft on the island and wait for the user's answer "
                                                "(run it BEFORE opening the messenger)")
    sp.add_argument("--to", required=True, help="who, as the user calls them")
    sp.add_argument("--via", default="", help="Discord, Telegram, WhatsApp…")
    sp.add_argument("--text", required=True, help="the exact text that will be sent")
    sp = sub.add_parser("studio", help="local creative studio: status | image | edit | upscale | nobg | video | animate | "
                                       "music | 3d | speech | subs | cut | join | audio | burn | vertical | nopause | "
                                       "speed | gif | slideshow | info | jobs | job ID | stop  (key=value options)")
    sp.add_argument("action")
    sp.add_argument("args", nargs="*", help="text / files, then key=value")
    sp = sub.add_parser("play", help="play music: finds it on YouTube, downloads the audio, plays in JustDay's player "
                                     "(count=N for several songs, playlist=1 for an album/playlist, shuffle=1, next=1 / add=1 to queue); also a file or a folder")
    sp.add_argument("query", nargs="+")
    sp = sub.add_parser("video", help="play a video (search words or a link): where=island|window|browser, "
                                      "asks the user when not given (Settings → Медиа)")
    sp.add_argument("query", nargs="+")
    sp = sub.add_parser("player", help="JustDay's player: status | pause | resume | toggle | next | prev | restart | stop | "
                                       "seek SECONDS | volume 0-130 | repeat off|all|one | shuffle on|off | jump INDEX | "
                                       "color жёлтый|#ffd23f|auto (the colour of the track on the island)")
    sp.add_argument("action", nargs="?", default="status")
    sp.add_argument("value", nargs="?")
    sp = sub.add_parser("config", help="get / set a setting: config set audio.earcons false")
    sp.add_argument("action", choices=["get", "set"])
    sp.add_argument("key", nargs="?")
    sp.add_argument("value", nargs="?")
    sub.add_parser("restart", help="restart the daemon and start a fresh conversation (after model changes)")
    sp = sub.add_parser("secret", help="store an API key / password in the desktop keyring")
    sp.add_argument("action", choices=["set", "check"])
    sp.add_argument("name", help="openrouter | deepseek | custom | mail")
    sp.add_argument("--stdin", action="store_true", help="read the value from stdin (for the Settings window)")
    sp = sub.add_parser("mail", help="private mail lane (local model): setup | check | read N")
    sp.add_argument("action", choices=["setup", "check", "test"])
    sp.add_argument("args", nargs="*")
    sp.add_argument("--address", help="setup without prompts: address here, app password on stdin")
    sp = sub.add_parser("settings-data", help="JSON snapshot for the Settings window")
    sp = sub.add_parser("voice", help="voices: list | design NAME DESCRIPTION | record SECONDS | clone NAME WAV TEXT | "
                                      "delete ID | preview TEXT | speed 1.2 | volume 80 | eleven [VOICE_ID] | "
                                      "key (reads stdin) | mute | unmute | games [on|off]")
    sp.add_argument("action", choices=["list", "design", "record", "clone", "delete", "preview", "speed", "volume",
                                       "eleven", "key", "mute", "unmute", "games"])
    sp.add_argument("args", nargs="*")
    sp = sub.add_parser("job", help="long commands in the background, so the assistant stays free: "
                                    "`justday job start \"Обновление системы\" -- jii update --json` · list · log ID · stop ID")
    sp.add_argument("action", choices=["start", "list", "log", "stop"])
    sp.add_argument("args", nargs=argparse.REMAINDER)
    sp = sub.add_parser("persona", help="the assistant's character: `justday persona` shows it; "
                                        "`justday persona friend|jarvis|calm|custom [swearing=on|off] [live=on|off]`")
    sp.add_argument("args", nargs="*")
    sp = sub.add_parser("timer", help="set a timer: `justday timer 10m чай` · `justday timer` lists what is set")
    sp.add_argument("args", nargs="*")
    sp = sub.add_parser("alarm", help="set an alarm: `justday alarm 7:30 подъём` [--daily] · `justday alarm` lists them")
    sp.add_argument("args", nargs="*")
    sp.add_argument("--daily", action="store_true", help="ring every day at that time")
    sp = sub.add_parser("reminders", help="what is waiting: list | cancel [timer|alarm|ID]")
    sp.add_argument("action", nargs="?", default="list", choices=["list", "cancel"])
    sp.add_argument("args", nargs="*")
    sp = sub.add_parser("hotkey", help="talk/cancel shortcuts: get | set --talk Meta+J --extra F19 --cancel Meta+Shift+J")
    sp.add_argument("action", choices=["get", "set"])
    sp.add_argument("--talk", default="Meta+J")
    sp.add_argument("--extra", default="F19")
    sp.add_argument("--cancel", default="Meta+Shift+J")
    sp.add_argument("--type", dest="type_", default=None, help="open the text field (default Meta+K)")
    sp.add_argument("--yes", default=None, help="answer yes / allow (default Meta+Y)")
    sp.add_argument("--no", default=None, help="answer no / deny (default Meta+N)")
    sp = sub.add_parser("autostart", help="start JustDay with the session: on | off | status")
    sp.add_argument("state", nargs="?", choices=["on", "off", "status"], default="status")
    sp = sub.add_parser("setup", help="first-run wizard: model, mail, voice, buttons")
    sp = sub.add_parser("calendar", help="private calendar from iCal links: setup | today | tomorrow | week")
    sp.add_argument("action", choices=["setup", "today", "tomorrow", "week", "test", "forget"])
    sp = sub.add_parser("voiceprint", help="personal voice profile: status | enroll | record KIND INDEX SECONDS | finish | reset | mode off|wake|always")
    sp.add_argument("action", choices=["status", "enroll", "record", "finish", "reset", "mode"])
    sp.add_argument("args", nargs="*")
    sp = sub.add_parser("version")
    sp = sub.add_parser("update", help="update JustDay from GitHub (git pull + install.sh); --check only looks")
    sp.add_argument("--check", action="store_true")

    a = p.parse_args(argv)

    if a.cmd == "daemon":
        from .daemon import main as dmain

        dmain()
    elif a.cmd == "toggle":
        r = control("toggle")
        if not r.get("ok"):
            subprocess.run(["notify-send", "-a", "JustDay", "JustDay не запущен", r.get("error", "")])
        _print(r)
    elif a.cmd == "stop":
        _print(control("stop"))
    elif a.cmd == "ask":
        r = control("ask", timeout=None, text=" ".join(a.text), silent=a.silent)
        print(r.get("result") if r.get("ok") else f"error: {r.get('error')}")
    elif a.cmd == "say":
        _print(control("say", timeout=120, text=" ".join(a.text)))
    elif a.cmd in ("approve", "deny"):
        _print(control(a.cmd))
    elif a.cmd == "compose":
        _print(control("compose", text=" ".join(a.text), context={} if a.no_selection else _screen_context()))
    elif a.cmd == "status":
        _print(control("status"))
    elif a.cmd == "new-session":
        _print(control("new_session", timeout=120))
    elif a.cmd == "logs":
        _logs(a.n, a.follow)
    elif a.cmd == "doctor" and a.json:
        from . import manage

        _print(manage.doctor())
    elif a.cmd == "doctor":
        print("JustDay doctor")
        skip = {"llm", "mcp", "tts", "stt"} if a.quick else set()
        ok = all([_check(n, fn) for n, fn in TESTS.items() if n not in skip])
        print(f"\nlogs: {config.STATE_DIR / 'justday.log'}  events: {config.EVENTS_FILE}")
        sys.exit(0 if ok else 1)
    elif a.cmd == "test":
        sys.exit(0 if _check(a.component, TESTS[a.component]) else 1)
    elif a.cmd == "memory":
        from .brain import BRAIN_DIR

        mem = memory_dir()
        if a.action in ("list", "forget", "clear-journal", "read", "write", "new"):
            from . import manage

            if a.action in ("read", "write"):  # a memory note or the profile; text for `write` comes in JUSTDAY_TEXT
                target = Path(a.target or "").resolve()
                if target.parent != mem.resolve() and target != (BRAIN_DIR / "CLAUDE.md").resolve():
                    sys.exit("not a memory file")
                if a.action == "read":
                    _print({"text": target.read_text(encoding="utf-8") if target.exists() else ""})
                else:
                    target.write_text(os.environ.get("JUSTDAY_TEXT", ""), encoding="utf-8")
                    _print({"ok": True})
                return
            if a.action == "new":
                _print(manage.new_memory(a.target or "Заметка", os.environ.get("JUSTDAY_TEXT", "")))
                return
            if a.action == "list":
                _print(manage.memory_files())
            elif a.action == "forget":
                target = Path(a.target or "").resolve()
                if target.parent != mem.resolve():  # only memory notes, nothing else on disk
                    sys.exit("not a memory file")
                _print(manage.forget_memory(target))
            else:
                _print(manage.trash(str(config.EVENTS_FILE)))
            return
        if a.action == "path":
            print(f"profile: {BRAIN_DIR / 'CLAUDE.md'}\nauto-memory: {mem}")
        elif a.action == "edit":
            subprocess.Popen(["xdg-open", str(mem if mem.exists() else BRAIN_DIR)])
        else:
            print(f"# {BRAIN_DIR / 'CLAUDE.md'}\n")
            print((BRAIN_DIR / "CLAUDE.md").read_text() if (BRAIN_DIR / "CLAUDE.md").exists() else "(missing)")
            for f in sorted(mem.glob("*.md")) if mem.exists() else []:
                print(f"\n# {f}\n{f.read_text()}")
    elif a.cmd == "apps":
        from . import desktop

        q = " ".join(a.query)
        if a.action == "list":
            _print([{"id": x["id"], "name": x["name"]} for x in desktop.list_apps()])
        elif a.action == "find":
            _print(desktop.find_apps(q))
        else:
            _print(desktop.launch_app(q))
    elif a.cmd == "games":
        from . import desktop

        _print(desktop.list_games() if a.action == "list" else desktop.launch_game(" ".join(a.query)))
    elif a.cmd == "windows":
        from . import desktop

        _print(desktop.windows(a.action, " ".join(a.query)))
    elif a.cmd == "screenshot":
        _print(screenshot(a.all, a.full))
    elif a.cmd == "recent":
        from . import desktop

        _print(desktop.recent(a.hours))
    elif a.cmd == "habits":
        from . import habits

        _print(habits.summary(a.hour))
    elif a.cmd == "claude":
        _claude_cmd(a)
    elif a.cmd == "model":
        _model_cmd(a)
    elif a.cmd == "voice":
        from . import manage

        args = a.args
        if a.action == "list":
            _print(manage.voices())
        elif a.action == "design":
            _print(manage.voice_request({"cmd": "design", "name": args[0], "description": " ".join(args[1:])}))
        elif a.action == "clone":
            _print(manage.voice_request({"cmd": "clone", "name": args[0], "audio": args[1], "text": " ".join(args[2:])}))
        elif a.action == "delete":
            _print(manage.voice_request({"cmd": "delete", "id": args[0]}))
        elif a.action == "speed":  # how fast the assistant talks, 0.5–2.0
            if args:
                config.set_value("tts", "speed", max(0.5, min(2.0, float(args[0]))))
                control("reload_settings", timeout=10)
            _print({"speed": config.load()["tts"]["speed"]})
        elif a.action == "volume":  # how loud the assistant is, 0–100 (the system volume stays where it is)
            if args:
                _print(control("volume", timeout=10, value=max(0, min(100, int(float(args[0]))))))
            else:
                _print({"volume": config.load()["audio"].get("volume", 100)})
        elif a.action in ("mute", "unmute"):  # answers stay on the island, they are just not spoken
            config.set_value("tts", "muted", a.action == "mute")
            control("reload_settings", timeout=10)
            _print({"muted": a.action == "mute"})
        elif a.action == "games":  # fall silent by itself while a game is running (the GPU is the game's)
            if args:
                config.set_value("tts", "mute_in_games", args[0] in ("on", "1", "true", "yes"))
                control("reload_settings", timeout=10)
            from . import desktop

            _print({"mute_in_games": config.load()["tts"].get("mute_in_games", True), "game": desktop.running_game()})
        elif a.action == "key":  # the ElevenLabs key, read from stdin so it never lands in the shell history
            key = sys.stdin.read().strip()
            config.set_secret("ELEVENLABS_API_KEY", key)
            _print({"ok": True, "stored_in": str(config.SECRETS_FILE), "cleared": not key})
        elif a.action == "eleven":  # voices on the ElevenLabs account, or switch to one of them
            from . import manage

            if args:
                config.set_value("tts", "eleven_voice", args[0])
                config.set_value("tts", "engine", "elevenlabs")
                control("reload_settings", timeout=10)
                _print({"ok": True, "engine": "elevenlabs", "voice": args[0]})
            else:
                _print(manage.eleven_voices())
        elif a.action == "record":  # the daemon records from the configured mic and transcribes (Whisper is loaded there)
            _print(control("record_sample", timeout=120, seconds=float(args[0] if args else 12)))
        else:
            _print(control("say", timeout=120, text=" ".join(args) or "Здравствуйте. Так звучит мой голос."))
    elif a.cmd in ("timer", "alarm", "reminders"):
        _reminder_cmd(a)
    elif a.cmd == "settings-data":
        from . import manage

        _print(manage.overview())
    elif a.cmd == "hotkey":
        from . import manage

        if a.action == "get":
            _print(manage.hotkeys())
        else:
            _print(manage.set_hotkeys(a.talk, a.extra, a.cancel, a.type_, a.yes, a.no))
            control("reload_settings", timeout=5)  # the island shows the keys in its hints
    elif a.cmd == "autostart":
        from . import manage

        _print(manage.autostart(None if a.state == "status" else a.state))
    elif a.cmd == "update":
        from . import manage

        st = manage.update_status()
        if a.check or not st.get("ok"):
            _print(st)
            sys.exit(0 if st.get("ok") else 1)
        if st["behind"] == 0:
            print("JustDay уже последней версии")
            return
        if st["local_changes"]:
            sys.exit("в папке JustDay есть ваши изменения — обновление остановлено, чтобы их не потерять (git stash)")
        print(f"Обновляю: {st['behind']} изменений\n  " + "\n  ".join(st["changes"]))
        if subprocess.run(["git", "-C", str(config.REPO_DIR), "pull", "--ff-only", "--quiet"]).returncode != 0:
            sys.exit("git pull не удался")
        env = {**os.environ, "JUSTDAY_SETUP": "0"}
        sys.exit(subprocess.run([str(config.REPO_DIR / "install.sh")], env=env).returncode)
    elif a.cmd == "calendar":
        from . import calendar_lane

        if a.action == "setup":
            print("Google Календарь → Настройки → ваш календарь → «Закрытый адрес в формате iCal». Несколько ссылок — через пробел; "
                  "новые добавляются к уже подключённым (убрать все: justday calendar forget).")
            import getpass

            value = (os.environ.get("JUSTDAY_SECRET") or getpass.getpass("ссылка(и) (ввод скрыт): ")).strip()
            _print(calendar_lane.setup(value))
        elif a.action == "forget":
            _print(calendar_lane.forget())
        elif a.action == "test":
            _print({"configured": bool(calendar_lane.urls()), "calendars": len(calendar_lane.urls())})
        else:
            import datetime as dt

            if a.action == "week":
                now = dt.datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
                _print(calendar_lane.between(now, now + dt.timedelta(days=7)))
            else:
                _print(calendar_lane.day(1 if a.action == "tomorrow" else 0))
    elif a.cmd == "voiceprint":
        _voiceprint_cmd(a)
    elif a.cmd == "version":
        from . import manage

        print(manage.app_version())
    elif a.cmd == "setup":
        from .wizard import run as wizard

        wizard()
    elif a.cmd == "config":
        _config_cmd(a)
    elif a.cmd == "persona":
        _persona_cmd(a.args)
    elif a.cmd == "job":
        _job_cmd(a.action, a.args)
    elif a.cmd == "contacts":
        _contacts_cmd(a)
    elif a.cmd == "compose-mail":
        r = control("mail_compose", timeout=120, to=a.to, about=a.about, attach=[os.path.abspath(f) for f in a.attach])
        print(r.get("result") if r.get("ok") else f"error: {r.get('error')}")
        sys.exit(0 if r.get("ok") else 1)
    elif a.cmd == "studio":
        _studio_cmd(a)
    elif a.cmd in ("play", "video"):
        words = [w for w in a.query if not re.match(r"^(count|next|add|where|playlist|album|shuffle)=", w)]
        kw = dict(w.split("=", 1) for w in a.query if w not in words)
        q = " ".join(words)
        if a.cmd == "play":
            mode = "next" if kw.get("next") in ("1", "true") else "append" if kw.get("add") in ("1", "true") else "replace"
            yes = lambda k: kw.get(k) in ("1", "true", "yes")  # noqa: E731
            r = control("media_play", timeout=300, query=q, count=int(kw.get("count", 1)), mode=mode,
                        playlist=yes("playlist") or yes("album"), shuffle=yes("shuffle"))
        else:
            r = control("media_video", timeout=900, query=q, where=kw.get("where", ""))
        print(json.dumps(r, ensure_ascii=False))
        sys.exit(0 if r.get("ok") else 1)
    elif a.cmd == "player":
        r = control("media", timeout=15, action=a.action, value=a.value)
        print(json.dumps(r, ensure_ascii=False, indent=1))
        sys.exit(0 if r.get("ok") else 1)
    elif a.cmd == "confirm-message":
        r = control("confirm_message", timeout=140, to=a.to, via=a.via, text=a.text)
        print(r.get("result") if r.get("ok") else f"error: {r.get('error')}")
        sys.exit(0 if r.get("ok") else 1)
    elif a.cmd == "restart":
        subprocess.run(["systemctl", "--user", "restart", "justday.service"], check=True)
        for _ in range(60):
            time.sleep(1)
            if control("status", timeout=3).get("ok"):
                break
        _print(control("new_session", timeout=120))
    elif a.cmd == "secret":
        _secret_cmd(a)
    elif a.cmd == "mail":
        _mail_cmd(a)


def _screen_context() -> dict:
    """The text selected right now (primary selection) — for "explain this", "translate this"."""
    try:
        sel = subprocess.run(["wl-paste", "--primary", "--no-newline", "--type", "text/plain"],
                             capture_output=True, text=True, timeout=1).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        sel = ""
    if not sel:
        return {}
    return {"selection": sel[:6000]}  # (the active window lookup takes ~0.7 s — too slow for a shortcut)


def _studio_cmd(a) -> None:
    from . import studio

    words = [x for x in a.args if "=" not in x or x.startswith(("/", "~", "."))]
    kw = dict(x.split("=", 1) for x in a.args if x not in words)
    text = " ".join(words)
    opt = kw.get
    num = lambda k, d: float(kw[k]) if k in kw else d  # noqa: E731
    seed = int(kw["seed"]) if "seed" in kw else None
    out = opt("out")
    act = a.action
    try:
        if act == "status":
            r = studio.status()
        elif act == "image":
            r = studio.image(text or opt("prompt", ""), opt("size", "square"), out, seed,
                             transparent=opt("transparent", "") in ("1", "true", "yes"))
        elif act == "edit":
            r = studio.edit(words[0], " ".join(words[1:]) or opt("prompt", ""), out, seed)
        elif act == "upscale":
            r = studio.upscale(text, out)
        elif act == "nobg":
            r = studio.remove_bg(text, out)
        elif act in ("video", "animate"):
            src = words[0] if act == "animate" else opt("image")
            prompt = " ".join(words[1:]) if act == "animate" else text
            r = studio.video(prompt or opt("prompt", "gentle natural motion, cinematic"), num("seconds", 3),
                             opt("size", "wide"), out, seed, src)
        elif act == "music":
            r = studio.music(text or opt("tags", ""), num("seconds", 30), opt("lyrics", ""), out, seed)
        elif act == "3d":
            is_file = bool(words) and os.path.isfile(os.path.expanduser(words[0]))
            r = studio.model3d(words[0] if is_file else None, "" if is_file else text, out, seed,
                               stl=opt("stl", "1") not in ("0", "false"))
        elif act == "speech":
            r = studio.speech(text or opt("text", ""), out, opt("voice", ""))
        elif act == "subs":
            r = studio.transcribe(text, out, opt("language", ""))
        elif act == "cut":
            r = studio.cut(text, opt("from", "0"), opt("to", ""), out)
        elif act == "join":
            r = studio.join(words, out)
        elif act == "audio":
            r = studio.add_audio(words[0], words[1], out, num("volume", 0.35), opt("replace", "") in ("1", "true"))
        elif act == "burn":
            r = studio.subtitles(words[0], words[1] if len(words) > 1 else None, out, opt("burn", "1") != "0")
        elif act == "vertical":
            r = studio.vertical(text, out, opt("mode", "blur"))
        elif act == "nopause":
            r = studio.trim_silence(text, out, num("pause", 0.6))
        elif act == "speed":
            r = studio.speed(words[0], float(words[1]) if len(words) > 1 else num("x", 1.5), out)
        elif act == "gif":
            r = studio.gif(text, out, int(num("width", 480)), int(num("fps", 12)), opt("from", ""), num("seconds", 0))
        elif act == "slideshow":
            r = studio.slideshow(words, out, num("each", 3.0), opt("music", ""), opt("size", "1920x1080"))
        elif act == "info":
            r = studio.probe(text)
        elif act == "jobs":
            r = studio.jobs()
        elif act == "job":
            job = studio.load_job(text)
            r = studio.summary(studio.wait(job, num("wait", 0)))
        elif act == "free":
            studio.free()
            r = {"ok": True}
        elif act == "stop":
            r = {"stopped": studio.stop_engine()}
        else:
            sys.exit(f"unknown studio action {act}")
    except (RuntimeError, OSError, IndexError, ValueError) as e:
        _print({"state": "failed", "error": str(e) or type(e).__name__})
        sys.exit(1)
    if isinstance(r, dict) and r.get("state") == "done" and act not in ("image", "edit", "upscale", "music", "job"):
        control("studio_done", timeout=5, job=r, kind=act, what=text[:80], quiet=True)
    _print(r)
    sys.exit(1 if isinstance(r, dict) and r.get("state") == "failed" else 0)


def _contacts_cmd(a) -> None:
    from . import contacts

    if a.action == "list":
        _print(contacts.load())
    elif a.action == "find":
        found = contacts.find(" ".join(a.args))
        _print(found if found else {"found": 0, "hint": "не знаю такого человека — спроси пользователя и сохрани"})
    elif a.action == "forget":
        _print({"ok": contacts.forget(" ".join(a.args))})
    else:  # set NAME key=value …   (aliases=мама,мамуля)
        if not a.args:
            sys.exit("usage: justday contacts set NAME [key=value …]")
        name_parts = [x for x in a.args if "=" not in x]
        fields = dict(x.split("=", 1) for x in a.args if "=" in x)
        unknown = set(fields) - set(contacts.FIELDS)
        if unknown:
            sys.exit(f"unknown fields {sorted(unknown)}; allowed: {', '.join(contacts.FIELDS)}")
        _print(contacts.upsert(" ".join(name_parts), **fields))


def _reminder_cmd(a) -> None:
    """`justday timer 10m чай`, `justday alarm 7:30 подъём --daily`, `justday reminders cancel timer`."""
    from . import reminders

    args = list(a.args)
    if a.cmd == "reminders" and getattr(a, "action", "list") == "cancel":
        _print(control("reminder_cancel", timeout=10, which=" ".join(args)))
        return
    if a.cmd == "reminders" or not args:
        _print(control("reminders", timeout=10))
        return
    spec, label = args[0], " ".join(args[1:])
    if a.cmd == "timer":
        seconds = reminders.parse_span(spec) or reminders.parse_span(spec + " минут")
        if not seconds:
            _print({"ok": False, "error": "how long? e.g. 10m, 90s, «1 час 30 минут»"})
            return
        _print(control("reminder_set", timeout=10, kind="timer", seconds=seconds, label=label))
        return
    at = reminders.parse_time("в " + spec) or reminders.parse_time(spec)
    if not at:
        _print({"ok": False, "error": "when? e.g. 7:30"})
        return
    _print(control("reminder_set", timeout=10, kind="alarm", at=at, label=label,
                   repeat="daily" if getattr(a, "daily", False) else ""))


def _voiceprint_cmd(a) -> None:
    args = a.args
    if a.action == "status":
        _print(control("voiceprint_status", timeout=10))
    elif a.action == "record":
        _print(control("enroll_record", timeout=60, kind=args[0], index=int(args[1]), seconds=float(args[2])))
    elif a.action == "finish":
        _print(control("enroll_finish", timeout=300))
    elif a.action == "reset":
        _print(control("voiceprint_reset", timeout=20))
    elif a.action == "mode":
        config.set_value("voiceprint", "mode", args[0])
        _print(control("reload_settings", timeout=5))
    else:  # interactive enrollment in the terminal
        st = control("voiceprint_status", timeout=10)
        steps = [("wake", i, 2.5, p) for i, p in enumerate(st["wake_phrases"])] + [("phrase", i, 5.0, p) for i, p in enumerate(st["phrases"])]
        print("Настройка под ваш голос: после сигнала произнесите фразу обычным голосом. Enter — записать, s — пропустить.")
        for n, (kind, idx, secs, phrase) in enumerate(steps, 1):
            while True:
                if input(f"\n[{n}/{len(steps)}] Скажите: «{phrase}»  (Enter) ").strip().lower() == "s":
                    break
                r = control("enroll_record", timeout=60, kind=kind, index=idx, seconds=secs)
                if r.get("ok"):
                    print("  ✓" + (f" услышал: «{r['text']}»" if r.get("text") else ""))
                    break
                print(f"  ✗ {r.get('error')} — ещё раз")
        r = control("enroll_finish", timeout=300)
        print("\nГотово: порог узнавания {threshold}, пауза конца фразы {silence_seconds} с, слово пробуждения дообучено: {wake}".format(
            threshold=r.get("threshold"), silence_seconds=r.get("silence_seconds"), wake="да" if r.get("wake_verifier") else "нет")
            if r.get("ok") else f"\nНе получилось: {r.get('error')}")


def _job_cmd(action: str, args: list[str]) -> None:
    """A job runs in the daemon, not here: this returns at once and the daemon reports the end."""
    if action == "start":
        if "--" not in args or args.index("--") == len(args) - 1:
            sys.exit('usage: justday job start "Title" -- command args…')
        cut = args.index("--")
        title, command = " ".join(args[:cut]), shlex.join(args[cut + 1:])
        if len(args[cut + 1:]) == 1:   # one quoted string: a shell line as written («a && b | c»)
            command = args[cut + 1]
        r = control("job_start", timeout=150, title=title, command=command, cwd=os.getcwd())
        if r.get("ok"):
            r["note"] = "running in the background; the daemon reports when it ends — finish your turn now"
        _print(r)
    elif action == "list":
        _print(control("job_list", timeout=5))
    elif action == "log":
        r = control("job_log", timeout=5, id=args[0] if args else "", lines=int(args[1]) if len(args) > 1 else 40)
        print(r.get("log", ""))
    else:
        _print(control("job_stop", timeout=5, id=args[0] if args else ""))


def _persona_cmd(args: list[str]) -> None:
    """Who the assistant is. A new character applies within seconds, the conversation goes on."""
    from . import persona

    on = lambda v: v.lower() in ("1", "on", "true", "yes", "да", "вкл")  # noqa: E731
    changed = False
    for arg in args:
        if arg in persona.PRESETS:
            config.set_value("persona", "character", arg)
            # the preset brings its own manner of address, unless the person chose one by hand
            u = config.load()["user"]
            if (u.get("address_as") or "") in persona.DEFAULT_ADDRESS:
                en = u.get("language") == "en"
                config.set_value("user", "address_as", {"jarvis": "sir" if en else "сэр",
                                                        "friend": "bro" if en else "брат"}.get(arg, ""))
            changed = True
        elif "=" in arg:
            k, v = arg.split("=", 1)
            key = {"swearing": "swearing", "мат": "swearing", "live": "live_speech", "live_speech": "live_speech"}.get(k)
            if not key:
                sys.exit(f"unknown option {k!r}: swearing=on|off, live=on|off")
            config.set_value("persona", key, on(v))
            changed = True
        else:
            sys.exit(f"unknown character {arg!r}: {', '.join(persona.PRESETS)}")
    if changed:
        control("reload_settings", timeout=5)
    p = config.load()["persona"]
    _print({"character": p["character"], "swearing": p["swearing"], "live_speech": p["live_speech"],
            "address_as": config.load()["user"]["address_as"]})


def _config_cmd(a) -> None:
    cfg = config.load()
    if a.action == "get":
        node = cfg
        for part in (a.key.split(".") if a.key else []):
            node = node[part]
        _print(node)
        return
    if not a.key or a.value is None or "." not in a.key:
        sys.exit("usage: justday config set section.key value")
    section, key = a.key.rsplit(".", 1)
    old = cfg
    for part in a.key.split("."):
        old = old.get(part) if isinstance(old, dict) else None
    value: object = a.value
    if isinstance(old, bool):
        value = a.value.lower() in ("1", "true", "yes", "on", "да")
    elif isinstance(old, int):
        value = int(a.value)
    elif isinstance(old, float):
        value = float(a.value)
    elif isinstance(old, list):
        value = [x.strip() for x in a.value.split(",") if x.strip()]
    config.set_value(section, key, value)
    control("reload_settings", timeout=5)
    print(f"{a.key} = {value}")


def _restart_hint() -> None:
    print("применится после: systemctl --user restart justday && justday new-session")


def _model_cmd(a) -> None:
    from . import providers

    b = config.load()["brain"]
    if a.action == "list":
        for name, p in providers.PROVIDERS.items():
            mark = "*" if name == b.get("provider", "claude") else " "
            key = ""
            if p.get("secret"):
                key = " [ключ есть]" if providers.secret_get(p["secret"]) else f" [нужен ключ: justday secret set {p['secret']}]"
            if p.get("cloud_signin"):
                acc = providers.cloud_account()
                key = f" [вход: {acc.get('user') or 'выполнен'}]" if acc["signed_in"] else " [нужен вход: justday model signin]"
            print(f"{mark} {name:<12} {p['desc']}{key}")
        print("\nбесплатно: justday model use ollama_cloud kimi-k3:cloud (после justday model signin) | "
              "justday model use openrouter openrouter/free | justday model use ollama qwen3.5:9b (на вашей видеокарте)"
              "\nплатно: justday model use claude sonnet | justday model use deepseek deepseek-v4-pro")
    elif a.action == "signin":
        acc = providers.cloud_account()
        if acc["signed_in"]:
            print(f"уже выполнен вход в Ollama: {acc.get('user') or ''}".strip())
        elif acc.get("signin_url"):
            print(f"Откройте и войдите (бесплатный аккаунт, карта не нужна):\n  {acc['signin_url']}")
            subprocess.run(["xdg-open", acc["signin_url"]], check=False)
        else:
            sys.exit(acc.get("error") or "Ollama не ответила")
    elif a.action == "status":
        print(f"provider: {b.get('provider', 'claude')}\nmodel:    {b['model']}"
              + (f"\nbase_url: {b['base_url']}" if b.get("base_url") else ""))
    else:
        if not a.args or a.args[0] not in providers.PROVIDERS:
            sys.exit(f"укажите провайдера: {', '.join(providers.PROVIDERS)}")
        name = a.args[0]
        model = a.args[1] if len(a.args) > 1 else ("sonnet" if name == "claude" else "")
        if not model:
            sys.exit("укажите модель, например: justday model use ollama qwen3.5:9b")
        if name == "custom" and len(a.args) > 2:
            config.set_value("brain", "base_url", a.args[2])
        config.set_value("brain", "provider", name)
        config.set_value("brain", "model", model)
        if name == "ollama_cloud":
            providers.ensure_cloud_model(model)
            if not providers.cloud_account()["signed_in"]:
                print("нужен бесплатный аккаунт Ollama: justday model signin")
        cfg = config.load()
        try:
            providers.env(cfg)
        except Exception as e:
            print(f"внимание: {e}")
        print(f"мозг: {name} / {model}. Память, навыки и инструменты остаются те же.")
        _restart_hint()


def _secret_cmd(a) -> None:
    import getpass

    from . import providers

    if a.action == "check":
        print("есть" if providers.secret_get(a.name) else "нет")
        return
    # Settings window passes the value in JUSTDAY_SECRET (visible only to this user's processes, gone on exit)
    value = (os.environ.get("JUSTDAY_SECRET") or (sys.stdin.readline() if a.stdin else "")).strip() \
        or getpass.getpass(f"{a.name} (ввод скрыт): ").strip()
    if not value:
        sys.exit("пусто, ничего не сохранено")
    providers.secret_set(a.name, value)
    print("сохранено в связке ключей (KWallet / GNOME Keyring)")


def _mail_cmd(a) -> None:
    import getpass

    from . import localllm, mail, providers

    if a.action == "setup" and a.address:  # from the Settings window: password on stdin, JSON result
        pw = (os.environ.get("JUSTDAY_SECRET") or sys.stdin.readline()).strip().replace(" ", "")
        providers.secret_set("mail", pw)
        config.set_value("mail", "address", a.address.strip())
        try:
            _print({"ok": True, "inbox": mail.count("in:inbox")})
        except Exception as e:
            _print({"ok": False, "error": str(e)})
        control("reload_settings", timeout=5)
        return
    if a.action == "setup":
        addr = input("адрес Gmail: ").strip()
        print("Пароль приложения: https://myaccount.google.com/apppasswords (нужна двухэтапная аутентификация).\n"
              "Это отдельный 16-значный пароль только для почты, основной пароль не нужен.")
        pw = getpass.getpass("пароль приложения (ввод скрыт): ").replace(" ", "")
        providers.secret_set("mail", pw)
        config.set_value("mail", "address", addr)
        try:
            n = mail.count("in:inbox")
            print(f"подключено: во входящих {n} писем")
        except Exception as e:
            sys.exit(f"не удалось войти: {e}")
        _restart_hint()
    elif a.action == "test":
        print("локальная модель:", "ok" if localllm.available() else "НЕ ДОСТУПНА (systemctl --user status justday-ollama)")
        try:
            print("почта:", f"ok, непрочитанных важных: {mail.count(config.load()['mail']['query'])}")
        except Exception as e:
            print("почта:", e)
    else:  # check: the same thing the voice command does, printed
        reply, _ = mail.MailAssistant()._summary()
        print(reply)


def _claude_cmd(a) -> None:
    from . import workers

    args = a.args
    try:
        if a.action == "start":
            _print(workers.start(a.cwd or os.getcwd(), " ".join(args), model=a.model))
        elif a.action == "send":
            _print(workers.send(args[0], " ".join(args[1:])))
        elif a.action == "result":
            _print(workers.result(args[0]))
        elif a.action == "list":
            _print([{k: x.get(k) for k in ("id", "kind", "cwd", "state", "status", "waitingFor", "name")}
                    for x in workers.agents()])
        elif a.action == "stop":
            _print(workers.stop(args[0]))
        elif a.action == "open":
            workers.open_terminal(args[0] if args else None, cwd=a.cwd)
            _print({"ok": True})
        elif a.action == "wait":
            deadline = time.monotonic() + a.timeout
            while time.monotonic() < deadline:
                r = workers.result(args[0])
                if r["state"] not in ("working", None):
                    _print(r)
                    return
                time.sleep(10)
            _print({"timeout": True, **workers.result(args[0])})
    except Exception as e:
        print(f"error: {e}", file=sys.stderr)
        sys.exit(1)


def _logs(n: int, follow: bool) -> None:
    path = config.EVENTS_FILE
    if not path.exists():
        print("no events yet")
        return

    def fmt(line: str) -> str:
        try:
            e = json.loads(line)
        except json.JSONDecodeError:
            return line.rstrip()
        ts, kind = e.pop("ts", ""), e.pop("kind", "")
        body = e.get("text") or e.get("desc") or json.dumps(e, ensure_ascii=False)
        return f"{ts[11:]} {kind:<16} {body[:220]}"

    lines = path.read_text(encoding="utf-8").splitlines()[-n:]
    for line in lines:
        print(fmt(line))
    if follow:
        with path.open(encoding="utf-8") as f:
            f.seek(0, 2)
            while True:
                line = f.readline()
                if line:
                    print(fmt(line), flush=True)
                else:
                    time.sleep(0.3)


if __name__ == "__main__":
    main()
