"""`justday` command: control the daemon, helper commands used by the brain, diagnostics."""
from __future__ import annotations

import argparse
import json
import os
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
    from . import audio
    import numpy as np

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
    from . import audio
    from .tts import TTS, normalize
    import asyncio

    tts = TTS(config.load()["tts"])
    pcm = tts.synth(normalize(text))
    asyncio.run(audio.Player(config.load()["audio"]["output"]).play(pcm, tts.rate))
    return f"engine={tts.cfg['engine']} speaker={tts.cfg['speaker']} {len(pcm) / tts.rate:.1f}s audio"


def t_stt():
    from .stt import STT
    from .tts import TTS, normalize
    import numpy as np

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


def t_daemon():
    r = control("status", timeout=5)
    if not r.get("ok"):
        raise RuntimeError(r.get("error"))
    return f"state={r['state']} model={r['model']} mic={r['mic_source']} wakeword={r['wakeword']}"


def t_hotkey():
    out = subprocess.run(["kreadconfig6", "--file", "kglobalshortcutsrc", "--group", "services", "--group",
                          "net.local.justday.desktop", "--key", "_launch"], capture_output=True, text=True).stdout.strip()
    mouse = subprocess.run(["kreadconfig6", "--file", "kcminputrc", "--group", "ButtonRebinds", "--group", "Mouse",
                            "--key", "ExtraButton1"], capture_output=True, text=True).stdout.strip()
    if not out:
        raise RuntimeError("global shortcut not registered (run install.sh)")
    return f"shortcut={out}" + (f", mouse ExtraButton1→{mouse}" if mouse else "")


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
         "hotkey": t_hotkey, "local_llm": t_local_llm, "mail": t_mail}


def memory_dir():
    from pathlib import Path
    import re

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
    sp = sub.add_parser("recent", help="recently used files and Claude Code projects")
    sp.add_argument("--hours", type=float, default=48)
    sp = sub.add_parser("claude", help="Claude Code worker sessions")
    sp.add_argument("action", choices=["start", "send", "result", "list", "stop", "open", "wait"])
    sp.add_argument("args", nargs="*")
    sp.add_argument("--cwd", default=None)
    sp.add_argument("--model", default=None)
    sp.add_argument("--timeout", type=float, default=1800)

    sp = sub.add_parser("model", help="which model drives the agent: list | status | use PROVIDER [MODEL]")
    sp.add_argument("action", choices=["list", "status", "use"], nargs="?", default="status")
    sp.add_argument("args", nargs="*")
    sp = sub.add_parser("contacts", help="address book JustDay learns: list | find QUERY | set NAME key=value… | forget NAME")
    sp.add_argument("action", choices=["list", "find", "set", "forget"])
    sp.add_argument("args", nargs="*")
    sp = sub.add_parser("compose-mail", help="draft an e-mail locally (confirmed by the user); the address stays private")
    sp.add_argument("--to", required=True, help="contact name or alias, e.g. мама")
    sp.add_argument("--about", default="", help="what the letter should say")
    sp.add_argument("--attach", action="append", default=[], help="file to attach (repeatable)")
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
    sp = sub.add_parser("voice", help="neural voices: list | design NAME DESCRIPTION | record SECONDS | clone NAME WAV TEXT | delete ID | preview TEXT")
    sp.add_argument("action", choices=["list", "design", "record", "clone", "delete", "preview"])
    sp.add_argument("args", nargs="*")
    sp = sub.add_parser("hotkey", help="talk/cancel shortcuts: get | set --talk Meta+J --extra F19 --cancel Meta+Shift+J")
    sp.add_argument("action", choices=["get", "set"])
    sp.add_argument("--talk", default="Meta+J")
    sp.add_argument("--extra", default="F19")
    sp.add_argument("--cancel", default="Meta+Shift+J")
    sp = sub.add_parser("autostart", help="start JustDay with the session: on | off | status")
    sp.add_argument("state", nargs="?", choices=["on", "off", "status"], default="status")
    sp = sub.add_parser("setup", help="first-run wizard: model, mail, voice, buttons")
    sp = sub.add_parser("calendar", help="private calendar from iCal links: setup | today | tomorrow | week")
    sp.add_argument("action", choices=["setup", "today", "tomorrow", "week", "test"])
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
                _print(manage.trash(str(target)))
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
        elif a.action == "record":  # the daemon records from the configured mic and transcribes (Whisper is loaded there)
            _print(control("record_sample", timeout=120, seconds=float(args[0] if args else 12)))
        else:
            _print(control("say", timeout=120, text=" ".join(args) or "Здравствуйте. Так звучит мой голос."))
    elif a.cmd == "settings-data":
        from . import manage

        _print(manage.overview())
    elif a.cmd == "hotkey":
        from . import manage

        _print(manage.hotkeys() if a.action == "get" else manage.set_hotkeys(a.talk, a.extra, a.cancel))
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
        from . import calendar_lane, providers

        if a.action == "setup":
            print("Google Календарь → Настройки → ваш календарь → «Закрытый адрес в формате iCal». Несколько ссылок — через пробел.")
            value = (os.environ.get("JUSTDAY_SECRET") or input("ссылка(и): ")).strip()
            providers.secret_set("calendar", value)
            try:
                _print({"ok": True, "today": len(calendar_lane.day(0)), "calendars": len(calendar_lane.urls())})
            except Exception as e:  # noqa: BLE001
                _print({"ok": False, "error": str(e)})
        elif a.action == "test":
            _print({"configured": bool(calendar_lane.urls()), "calendars": len(calendar_lane.urls())})
        else:
            import datetime as dt

            if a.action == "week":
                now = dt.datetime.now().astimezone().replace(hour=0, minute=0, second=0, microsecond=0)
                _print(calendar_lane.between(now, now + dt.timedelta(days=7)))
            else:
                _print(calendar_lane.day(1 if a.action == "tomorrow" else 0))
    elif a.cmd == "version":
        from . import manage

        print(manage.app_version())
    elif a.cmd == "setup":
        from .wizard import run as wizard

        wizard()
    elif a.cmd == "config":
        _config_cmd(a)
    elif a.cmd == "contacts":
        _contacts_cmd(a)
    elif a.cmd == "compose-mail":
        r = control("mail_compose", timeout=120, to=a.to, about=a.about, attach=[os.path.abspath(f) for f in a.attach])
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
            print(f"{mark} {name:<11} {p['desc']}{key}")
        print("\nпримеры: justday model use claude sonnet | justday model use ollama qwen3.5:9b | "
              "justday model use openrouter nvidia/nemotron-3-super-120b-a12b:free")
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
        except Exception as e:  # noqa: BLE001
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
