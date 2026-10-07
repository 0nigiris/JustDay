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


def manage_hotkeys():
    """Таблица клавиш из manage — единственное место, где они описаны."""
    from .manage import HOTKEYS

    return HOTKEYS


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

    from . import audio, parts
    from .tts import TTS, normalize

    tts = TTS(config.load()["tts"])
    pcm = tts.synth(normalize(text))
    asyncio.run(audio.Player(config.load()["audio"]["output"]).play(pcm, tts.rate))
    fell_back = " (нейросетевого голоса нет, звучит espeak-ng — justday parts add voice)" \
        if tts.cfg["engine"] == "silero" and not parts.have("voice") else ""
    return f"engine={tts.cfg['engine']} speaker={tts.cfg['speaker']} {len(pcm) / tts.rate:.1f}s audio{fell_back}"


def t_parts():
    """Что из необязательного стоит. Отсутствие части — это выбор пользователя, а не поломка."""
    from . import parts

    have = parts.installed()
    rest = [n for n in parts.suggested() if n not in have]
    words = ", ".join(have) if have else "только ядро"
    return words + (f" · не ставили: {', '.join(rest)} (justday parts add {' '.join(rest)})" if rest else "")


def t_stt():
    import numpy as np

    from . import parts
    from .stt import STT
    from .tts import TTS, normalize

    if not parts.have("speech"):
        return "не ставили — justday parts add speech"
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
    """Чем управляем окнами и что рисует состояние — на каждом рабочем столе это разное."""
    from . import desktop

    session = os.environ.get("XDG_SESSION_TYPE", "?")
    if desktop.backend() == "kwin":
        if not shutil.which("kwin-mcp"):
            raise RuntimeError("kwin-mcp not installed (uv tool install git+https://github.com/VibeProgramm/kwin-mcp)")
        # Дешёвый вопрос вместо supportInformation: тот выгружает килобайты текста о всей системе,
        # а нам нужно ровно «KWin на шине и отвечает».
        from .desktop import qdbus_bin
        bin = qdbus_bin()
        if not bin:
            raise RuntimeError("qdbus not found (qdbus-qt6/qdbus6)")
        wins = subprocess.run([bin, "org.kde.KWin", "/KWin", "org.kde.KWin.currentDesktop"],
                              capture_output=True, text=True, timeout=10)
        if wins.returncode:
            raise RuntimeError("KWin D-Bus not reachable")
        return f"kwin-mcp ok, KWin D-Bus ok, session={session}, окна: {len(desktop.windows('list'))}, экран: {_face()}"
    if desktop.backend() == "x11":
        shot = next((x for x in ("grim", "gnome-screenshot", "maim", "scrot", "import") if shutil.which(x)), "")
        if not shot:
            raise RuntimeError("нечем снять экран: поставьте maim или scrot")
        return (f"окна: wmctrl ({len(desktop.windows('list'))}), снимки: {shot}, session={session}, экран: {_face()}"
                + ("" if shutil.which("xdotool") else ", без xdotool не свернуть окно"))
    raise RuntimeError("окнами управлять нечем: нужен KWin 6 (Wayland) или wmctrl на X11")


def _face() -> str:
    """Что сейчас на экране и почему именно оно. «Почему у меня полоска вместо острова» — первый
    вопрос на машине с двумя сеансами, и отвечать на него должна сама программа, а не человек."""
    from . import face

    what, why = face.pick()
    word = "остров" if what == "island" else "полоска"
    if _unit_active("justday-ui"):
        return f"{word} ({why})"
    for old, name in (("justday-island", "остров"), ("justday-panel", "полоска")):
        if _unit_active(old):
            return f"{name} — старая служба {old}; переустановите, чтобы выбор шёл по сеансу"
    return f"ничего не запущено: нужен {word} ({why}) — systemctl --user enable --now justday-ui"


def _unit_active(name: str) -> bool:
    return subprocess.run(["systemctl", "--user", "is-active", "--quiet", name],
                          capture_output=True).returncode == 0


def t_files():

    from . import desktop, filesearch
    apps = desktop.list_apps()
    rec = desktop.recent(48, 5)
    fs = filesearch.stats()
    return f"{len(apps)} apps, {len(desktop.list_games())} games, {len(rec['files'])} recent files, " \
           f"{fs.get('indexed', 0)} indexed, {len(rec['claude_projects'])} recent Claude projects, " \
           f"plocate={'yes' if fs.get('plocate') else 'no'}, fd={'yes' if fs.get('fd') else 'no'}"



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
    if not shutil.which("kreadconfig6") and not shutil.which("kreadconfig5"):
        # не KDE: сочетания живут в GNOME или в настройках самого окружения
        got = subprocess.run(["gsettings", "get", "org.gnome.settings-daemon.plugins.media-keys",
                              "custom-keybindings"], capture_output=True, text=True).stdout
        if "justday" in got:
            return "GNOME: настроены (scripts/setup-hotkey-gnome.sh)"
        raise RuntimeError("сочетания не настроены: scripts/setup-hotkey-gnome.sh или вручную в настройках стола")
    keys = hotkeys()
    mouse = subprocess.run([shutil.which("kreadconfig6") or "kreadconfig5", "--file", "kcminputrc",
                            "--group", "ButtonRebinds", "--group", "Mouse",
                            "--key", "ExtraButton1"], capture_output=True, text=True).stdout.strip()
    if not keys["talk"]:
        raise RuntimeError("global shortcut not registered (run install.sh)")
    return f"talk={keys['talk']}" + (f"+{keys['extra']}" if keys["extra"] else "") + f", cancel={keys['cancel'] or '—'}" + \
        (f", mouse ExtraButton1→{mouse}" if mouse else "")


def _capture(png: str) -> None:
    """Снимок экрана. Вся правда о том, чем снимать на KWin, — в desktop.capture_screen."""
    from . import desktop

    try:
        desktop.capture_screen(png)
    except RuntimeError as e:
        raise RuntimeError(
            "нечем снять экран: не ответил портал рабочего стола "
            "(xdg-desktop-portal-kde), а grim на KWin не работает" + f" ({e})"
        ) from e


def screenshot(all_screens: bool = False, full: bool = False) -> dict:
    """Active window (default) or all monitors → small JPEG + the mapping back to screen coordinates."""
    from . import desktop

    png, jpg = "/tmp/justday-screen.png", f"/tmp/justday-screen-{int(time.time() * 1000)}.jpg"
    _capture(png)
    crop, ox, oy, title, app, ww, wh = [], 0, 0, "all monitors", "", 0, 0
    if not all_screens:
        win = desktop.windows("active")
        if win:
            w = win[0]
            ox, oy, title, app = max(0, w["x"]), max(0, w["y"]), f"{w['app']}: {w['title']}", w["app"]
            ww, wh = w["w"], w["h"]
            crop = ["-crop", f"{w['w']}x{w['h']}+{ox}+{oy}", "+repage"]
    limit = 10000 if full else (1600 if not all_screens else 1800)
    if not shutil.which("magick"):   # без ImageMagick отдаём снимок как есть: лучше так, чем никак
        return {"path": png, "window": title, "app": app, "width": ww, "height": wh,
                "origin_x": ox, "origin_y": oy, "scale": 1.0,
                "to_screen": "screen_x = origin_x + image_x; screen_y = origin_y + image_y"}
    ident = subprocess.run(["magick", png, *crop, "-format", "%w", "info:"], capture_output=True, text=True).stdout
    width = int(ident.strip() or limit)
    scale = min(1.0, limit / width)
    subprocess.run(["magick", png, *crop, "-resize", f"{scale * 100:.2f}%", "-quality", "85", jpg], check=True, timeout=20)
    return {"path": jpg, "window": title, "app": app, "width": ww, "height": wh,
            "origin_x": ox, "origin_y": oy, "scale": round(scale, 4),
            "to_screen": "screen_x = origin_x + image_x / scale; screen_y = origin_y + image_y / scale"}


def t_speed():
    from . import speed
    return speed.report()


TESTS = {"daemon": t_daemon, "parts": t_parts, "mic": t_mic, "tts": t_tts, "stt": t_stt, "llm": t_llm, "mcp": t_mcp,
         "desktop": t_desktop, "browser": t_browser, "files": t_files, "claude": t_claude, "memory": t_memory,
         "hotkey": t_hotkey, "local_llm": t_local_llm, "mail": t_mail, "software": t_software, "speed": t_speed}


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
    sub.add_parser("chat", help="открыть окно чата с ассистентом (ответы в нём не озвучиваются)")
    sp = sub.add_parser("compose", help="keyboard shortcut: open the island's text field (takes the selected text along)")
    sp.add_argument("text", nargs="*")
    sp.add_argument("--no-selection", action="store_true")
    sub.add_parser("new-session", help="forget the current conversation (memory is kept)")
    sp = sub.add_parser("crashlog", help="save a crash report after a failed service (systemd ExecStopPost)")
    sp.add_argument("service")
    sp = sub.add_parser("logs", help="show recent events")
    sp.add_argument("-f", "--follow", action="store_true")
    sp.add_argument("-n", type=int, default=40)
    sub.add_parser("panel", help="the fallback panel for desktops without the island (X11, Plasma 5, GNOME)")
    sp = sub.add_parser("shell", help="open the OpenCode window with the JustDay provider ladder")
    sp.add_argument("rest", nargs=argparse.REMAINDER, help="arguments passed on to opencode")
    # Одна команда на «сесть за работу»: пока подписка Claude отвечает — Claude Code (только в нём
    # она и разрешена), кончился лимит — оболочка на живой ступени лестницы.
    # Своя оболочка: один терминал, в котором задачу подхватывает тот, кто сейчас может.
    sp = sub.add_parser("terminal", help="своя оболочка: один терминал, лестница движков")
    sp.add_argument("task", nargs="*", help="задача строкой (без неё открывается окно)")
    sp.add_argument("--night", action="store_true",
                    help="оставить задачу на ночь: не давать машине спать, ждать возвращения лимитов, "
                         "писать журнал на диск")
    sp.add_argument("--hours", type=float, default=8.0, help="сколько часов ждать лимиты ночью")
    sp.add_argument("--tell", action="store_true", help="написать письмо, когда кончится")
    sp.add_argument("--dark", action="store_true",
                    help="заодно режим сервера: экраны гаснут, музыка на паузу (см. justday night)")
    sp = sub.add_parser("work", help="сесть за работу: Claude Code, пока он отвечает, иначе оболочка")
    sp.add_argument("--shell", action="store_true", help="сразу оболочка, не спрашивая Claude")
    sp.add_argument("--claude", action="store_true", help="сразу Claude Code")
    sp.add_argument("rest", nargs=argparse.REMAINDER, help="остальное уходит выбранной оболочке")
    sub.add_parser("ui", help="show the assistant on screen: the island on Wayland, the fallback panel elsewhere "
                             "(decided at every login; ui.face pins it)")
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
    sp.add_argument("action", choices=["list", "focus", "close", "close-active", "minimize", "wake"])
    sp.add_argument("query", nargs="*")
    sp = sub.add_parser("click", help="щёлкнуть в точке экрана (X11: xdotool; на Wayland щелчки идут через kwin-mcp)")
    sp.add_argument("x", type=int)
    sp.add_argument("y", type=int)
    sp.add_argument("--button", type=int, default=1, help="1 левая, 2 средняя, 3 правая")
    sp.add_argument("--double", action="store_true")
    sp = sub.add_parser("keys", help="нажать сочетание клавиш: justday keys ctrl+s (X11: xdotool)")
    sp.add_argument("combo")
    sp = sub.add_parser("screenshot", help="capture the screen as a small JPEG and print its path")
    sp.add_argument("--all", action="store_true", help="all monitors instead of the active window")
    sp.add_argument("--full", action="store_true", help="keep full resolution (small text)")
    sp = sub.add_parser("guard", help="предупреждение перед выключением компьютера: status | on | off")
    sp.add_argument("action", nargs="?", choices=["status", "on", "off"], default="status")
    sp = sub.add_parser("session", help="the open applications: save | close [--keep NAME] | restore | list")
    sp.add_argument("action", choices=["save", "close", "restore", "list"])
    sp.add_argument("--keep", action="append", default=[], help="an application to leave open (may repeat)")
    sp = sub.add_parser("phone", help="the phone through KDE Connect: list | notify TEXT | send FILE_OR_URL | ring")
    sp.add_argument("action", choices=["list", "notify", "send", "ring", "commands"])
    sp.add_argument("args", nargs="*")
    sp.add_argument("--to", default="", help="device name, when more than one is paired")
    sp.add_argument("--install", action="store_true",
                    help="для commands: записать команды в KDE Connect, чтобы телефон мог их запускать")
    sp = sub.add_parser("portable", help="собрать флешку: воткнул в чужой компьютер, поработал, "
                                        "вынул — следов не осталось")
    sp.add_argument("action", choices=["init"])
    sp.add_argument("where", help="папка на смонтированной флешке")
    sp.add_argument("--keys", default="", help="какие ключи положить, через запятую: openrouter,groq")
    sp = sub.add_parser("server", help="режим сервера: экраны гаснут, музыка встаёт на паузу, "
                                      "машина не засыпает, а работа идёт. on | off | status")
    sp.add_argument("action", nargs="?", default="status", choices=["on", "off", "status"])
    sp.add_argument("--why", default="работа ассистента", help="зачем — видно в журнале и в status")
    sp.add_argument("--hours", type=float, default=0.0,
                    help="через сколько часов сторож сам вернёт машину (0 — как в настройках)")
    sp.add_argument("--quiet", action="store_true",
                    help="для off: вернуть всё, кроме музыки — её включит человек сам")
    sp = sub.add_parser("night", help="«я спать»: задача уходит работать на ночь в отдельную "
                                     "службу, машина переходит в режим сервера, утром — письмо")
    sp.add_argument("task", nargs="*", help="что сделать за ночь")
    sp.add_argument("--hours", type=float, default=8.0, help="сколько часов на это есть")
    sp.add_argument("--here", action="store_true",
                    help="работать в этом окне, а не в службе (окно нельзя будет закрыть)")
    sp.add_argument("--light", action="store_true",
                    help="не гасить экраны и не глушить звук — только не давать машине заснуть")
    sp.add_argument("--no-letter", action="store_true", help="не писать письмо по окончании")
    sp.add_argument("--status", action="store_true", help="идёт ли ночная работа и где журнал")
    sp.add_argument("--stop", action="store_true", help="остановить работу и вернуть машину")
    sp = sub.add_parser("reach", help="дотянуться до человека, когда его нет за компьютером: "
                                     "письмо — обычное, --urgent — ещё и звонок на телефон")
    sp.add_argument("text", nargs="+")
    sp.add_argument("--urgent", action="store_true", help="телефон зазвонит: только для того, "
                                                         "ради чего не жалко оторвать человека от дела")
    sp.add_argument("--subject", default="", help="тема письма")
    sp.add_argument("--to", default="", help="имя устройства, если их несколько")
    sp = sub.add_parser("call", help="позвонить на номер и сказать: justday call +34612345678 «текст»")
    sp.add_argument("to", help="номер в международном виде, +34…")
    sp.add_argument("text", nargs="*", help="что сказать в трубку")
    sp.add_argument("--seconds", type=int, default=0, help="потолок разговора, по умолчанию 90")
    sp = sub.add_parser("telegram", help="телеграм-бот: голосом или текстом ему на телефон, где бы он ни был")
    sp.add_argument("action", choices=["voice", "send", "status"])
    sp.add_argument("text", nargs="*")
    sp = sub.add_parser("habits", help="what the user usually asks around this hour (for «как обычно»)")
    sp.add_argument("--hour", type=int, help="a different hour of the day (0-23)")
    sp = sub.add_parser("scene", help="сценарии: list | run <имя> | add <имя> | forget <имя>")
    sp.add_argument("action", nargs="?", choices=["list", "run", "add", "forget"], default="list")
    sp.add_argument("which", nargs="*")
    sp.add_argument("--phrase", action="append", default=[], help="фраза, которой зовут сценарий")
    sp.add_argument("--open", action="append", default=[], help="что открыть")
    sp.add_argument("--close", action="append", default=[], help="что закрыть")
    sp.add_argument("--music", default="", help="что включить («моя» = фонотека)")
    sp.add_argument("--say", default="", help="что сказать вслух")
    sp.add_argument("--silent", choices=["on", "off"], help="замолчать на время сценария")
    sp = sub.add_parser("plan", help="планы в Obsidian: add | list | done | open")
    sp.add_argument("action", nargs="?", choices=["add", "list", "done", "open"], default="list")
    sp.add_argument("text", nargs="*")
    sp = sub.add_parser("promise", help="что он кому обещал: add «текст» [--to кому] [--due срок] | list [кому] | find слова | done номер")
    sp.add_argument("action", nargs="?", choices=["add", "list", "find", "done"], default="list")
    sp.add_argument("text", nargs="*")
    sp.add_argument("--to", default="", help="кому обещано")
    sp.add_argument("--due", default="", help="к какому сроку")
    sp = sub.add_parser("nudges", help="что ассистент сказал первым за день (по делу ли): justday nudges [YYYY-MM-DD]")
    sp.add_argument("day", nargs="?", default="")
    sp = sub.add_parser("diary", help="страница дня в Obsidian: чем занимались, что закрыли, во что обошлось")
    sp.add_argument("day", nargs="?", default="", help="YYYY-MM-DD (по умолчанию сегодня)")
    sp.add_argument("--open", action="store_true", help="открыть её в Obsidian")
    sp = sub.add_parser("note", help="заметка в Obsidian: justday note «Заголовок» текст…")
    sp.add_argument("title")
    sp.add_argument("text", nargs="*")
    sp.add_argument("--folder", default="", help="подкаталог внутри хранилища")
    sp = sub.add_parser("inbox", help="сообщения, оставленные с телефона: list | add | clear")
    sp.add_argument("action", nargs="?", choices=["list", "add", "clear"], default="list")
    sp.add_argument("text", nargs="*")
    sp = sub.add_parser("wake", help="кто будит ассистента и сколько раз впустую")
    sp.add_argument("--days", type=int, default=3)
    sp = sub.add_parser("tokens", help="во что обходится разговор: токены и деньги по дням")
    sp.add_argument("--days", type=int, default=7)
    sp.add_argument("--json", action="store_true")
    sp = sub.add_parser("recent", help="recently used files and Claude Code projects")
    sp.add_argument("--hours", type=float, default=48)
    sp = sub.add_parser("history", help="what played lately: «включи то, что я слушал»")
    sp.add_argument("-n", type=int, default=10)
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
    sp = sub.add_parser("video", help="play a video (search words or a link); --where island|window|browser, "
                                      "or say it in the words themselves («в островке»); otherwise the setting decides "
                                      "(Settings → Музыка и видео)")
    sp.add_argument("query", nargs="+")
    sp.add_argument("--where", choices=["island", "window", "browser"], default="",
                    help="where to play it: the island, its own window, or the YouTube page")
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
    sp.add_argument("action", choices=["list", "design", "record", "clone", "delete", "preview", "speed", "tempo",
                                       "volume", "eleven", "key", "mute", "unmute", "games"])
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
    sp = sub.add_parser("hotkey", help="глобальные сочетания: get показывает все, "
                                      "set --clip Meta+V --apps 'Alt+Space' меняет названные "
                                      "(пустая строка снимает клавишу, остальные не трогаются)")
    sp.add_argument("action", choices=["get", "set", "restore"])
    sp.add_argument("--extra", default=None, help="вторая клавиша «говорить» (кнопка мыши, F19)")
    for _name, _label, _default in manage_hotkeys():
        sp.add_argument(f"--{_name}", default=None, dest=f"key_{_name}",
                        help=f"{_label}" + (f" (по умолчанию {_default})" if _default else ""))
    sp = sub.add_parser("autostart", help="start JustDay with the session: on | off | status")
    sp.add_argument("state", nargs="?", choices=["on", "off", "status"], default="status")
    sp = sub.add_parser("setup", help="first-run wizard: model, mail, voice, buttons")
    sp = sub.add_parser("calendar", help="private calendar from iCal links: setup | today | tomorrow | week")
    sp.add_argument("action", choices=["setup", "today", "tomorrow", "week", "test", "forget"])
    sp = sub.add_parser("voiceprint", help="personal voice profile: status | enroll | record KIND INDEX SECONDS | finish | reset | mode off|wake|always")
    sp.add_argument("action", choices=["status", "enroll", "record", "finish", "reset", "mode"])
    sp.add_argument("args", nargs="*")
    sp = sub.add_parser("parts", help="необязательные части окружения (речь, голос, CUDA): "
                                     "`justday parts` показывает, что стоит; add/remove доставляет и убирает")
    sp.add_argument("action", nargs="?", default="list", choices=["list", "add", "remove"])
    sp.add_argument("names", nargs="*", help="speech | voice | cuda")
    # ─── панель управления: эмодзи, буфер обмена, нагрузка ───
    sp = sub.add_parser("emoji", help="выбиралка эмодзи: поиск по-русски, вставка в то окно, где курсор "
                                     "(без запроса открывает сетку на островке)")
    sp.add_argument("query", nargs="*", help="что искать: кот, сердце, флаг россия")
    sp.add_argument("--list", action="store_true", help="показать найденное, ничего не вставляя")
    sp.add_argument("--copy", action="store_true", help="только в буфер обмена, не печатать")
    sp = sub.add_parser("clip", help="история буфера обмена; пароли в неё не попадают")
    sp.add_argument("action", nargs="?", default="list",
                    choices=["list", "use", "forget", "wipe", "pause", "resume", "store", "pin", "unpin", "edit", "show"])
    sp.add_argument("which", nargs="?", default="", help="номер в списке или id записи")
    sp.add_argument("--search", default="", help="искать по содержимому")
    sp.add_argument("--image", action="store_true", help="для store: на входе картинка, а не текст")
    sp.add_argument("--copy", action="store_true", help="только в буфер, не печатать")
    # Имя не «panel»: так уже зовётся запасная полоска на Tk для машин без острова.
    sp = sub.add_parser("tools", help="открыть панель в островке: apps (Spotlight) | emoji | clip | load")
    sp.add_argument("which", nargs="?", default="apps", choices=["apps", "emoji", "clip", "mixer", "load"])
    sp = sub.add_parser("models", help="что держит память: слух, голос; free — отпустить сейчас")
    sp.add_argument("action", nargs="?", default="show", choices=["show", "free"])
    sp = sub.add_parser("menu", help="меню приложений в островке (клавиша Windows)")
    sp.add_argument("action", nargs="?", default="toggle", choices=["toggle", "open", "close"])
    sp = sub.add_parser("popups", help="чьи всплывашки с уведомлениями: island (только остров) | system (ещё и плазмы)")
    sp.add_argument("where", nargs="?", default="show", choices=["show", "island", "system"])
    sp = sub.add_parser("dock", help="док: список, pin/unpin, go N (Meta+N — N-я программа слева направо)")
    sp.add_argument("action", nargs="?", default="show", choices=["show", "pin", "unpin", "go"])
    sp.add_argument("what", nargs="*", help="для pin/unpin — id программы; для go — номер слота 1…N")
    sp = sub.add_parser("launch", help="поиск программ: без запроса открывает лаунчер в островке, "
                                      "с запросом запускает первое подходящее")
    sp.add_argument("query", nargs="*")
    sp.add_argument("--list", action="store_true", help="показать найденное, ничего не запуская")
    sp = sub.add_parser("load", help="нагрузка машины: процессор, память, диск, сеть, температуры, "
                                    "тяжёлые программы")
    sp.add_argument("--json", action="store_true")
    sp.add_argument("--watch", action="store_true", help="обновлять на месте, пока не остановят")
    sp = sub.add_parser("qr", help="QR-код в терминале: `justday qr https://…` · `justday qr --wifi ИМЯ` "
                                   "(пароль спросит скрыто)")
    sp.add_argument("text", nargs="*")
    sp.add_argument("--wifi", metavar="ИМЯ_СЕТИ", help="код для подключения к Wi-Fi")
    sp.add_argument("--hidden", action="store_true", help="сеть скрытая")
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
    elif a.cmd == "chat":
        control("chat_open")
    elif a.cmd == "compose":
        _print(control("compose", text=" ".join(a.text), context={} if a.no_selection else _screen_context()))
    elif a.cmd == "status":
        _print(control("status"))
    elif a.cmd == "new-session":
        _print(control("new_session", timeout=120))
    elif a.cmd == "crashlog":
        from . import crashlog

        if path := crashlog.save(a.service):
            print(path)
    elif a.cmd == "logs":
        _logs(a.n, a.follow)
    elif a.cmd == "doctor" and a.json:
        from . import manage

        _print(manage.doctor())
    elif a.cmd == "doctor":
        print("JustDay doctor")
        skip = {"speed"} | ({"llm", "mcp", "tts", "stt"} if a.quick else set())  # замеры — отдельной командой
        ok = all([_check(n, fn) for n, fn in TESTS.items() if n not in skip])
        print(f"\nlogs: {config.STATE_DIR / 'justday.log'}  events: {config.EVENTS_FILE}")
        sys.exit(0 if ok else 1)
    elif a.cmd == "test":
        sys.exit(0 if _check(a.component, TESTS[a.component]) else 1)
    elif a.cmd == "click":
        from . import desktop

        r = desktop.pointer(a.x, a.y, a.button, a.double)
        _print(r)
        sys.exit(0 if r.get("ok") else 1)
    elif a.cmd == "keys":
        from . import desktop

        r = desktop.keys(a.combo)
        _print(r)
        sys.exit(0 if r.get("ok") else 1)
    elif a.cmd == "parts":
        sys.exit(_parts_cmd(a.action, a.names))
    elif a.cmd == "emoji":
        sys.exit(_emoji_cmd(" ".join(a.query), show=a.list, copy_only=a.copy))
    elif a.cmd == "clip":
        sys.exit(_clip_cmd(a.action, a.which, search=a.search, image=a.image, copy_only=a.copy))
    elif a.cmd == "tools":
        got = control("panel", which=a.which, timeout=5)
        if not got.get("ok"):
            sys.exit(got.get("error") or "островок не отвечает")
    elif a.cmd == "models":
        got = control("models", free=a.action == "free", timeout=20)
        if not got.get("ok"):
            sys.exit(got.get("error") or "демон не отвечает")
        stt, tts, gpu = got["stt"], got.get("tts") or {}, got.get("gpu") or {}
        mark = lambda on: "держит" if on else "отпущено"          # noqa: E731
        print(f"  слух   {mark(stt['loaded']):8} · молчит {stt['idle_minutes']:g} мин "
              f"· отпускать после {stt['unload_after']} мин")
        if not tts.get("ok"):
            print(f"  голос  недоступен ({tts.get('error', '')})")
        elif tts.get("stopped"):
            # Служба вышла совсем и поднимется сама при первой же просьбе. Спрашивать её о том,
            # сколько она молчит, некого — писать «None мин» вместо этого нельзя.
            print("  голос  служба спит · поднимется при первой просьбе")
        else:
            print(f"  голос  {mark(tts.get('loaded')):8} · молчит {tts.get('idle', 0)} мин "
                  f"· отпускать после {tts.get('idle_unload_minutes', '?')} мин")
        mem = got.get("memory") or {}
        print(f"  память машины {mem.get('used', 0)} / {mem.get('total', 0)} МБ"
              + (f" · видеопамять {gpu['mem_used']} / {gpu['mem_total']} МБ" if gpu.get("mem_total") else ""))
    elif a.cmd == "menu":
        got = control("menu", open=a.action != "close", toggle=a.action == "toggle", timeout=5)
        if not got.get("ok"):
            sys.exit(got.get("error") or "островок не отвечает")
    elif a.cmd == "popups":
        from . import notifications as notif

        if a.where != "show":
            notif.system_popups(a.where == "system")
            config.set_value("island", "system_popups", a.where == "system")
        got = notif.system_popups()
        # Keep Plasma volume/brightness/keyboard OSD in sync with island.show_osd
        # (island mode / installer path — durable plasmarc + plasmaparc mute).
        osd = notif.sync_plasma_osd(system_popups=got.get("popups"))
        print("всплывашки плазмы показываются" if got.get("popups")
              else "всплывашки плазмы молчат — уведомления только на острове")
        print("OSD плазмы показывается" if osd.get("osd")
              else "OSD плазмы выкл — громкость/яркость/раскладка только на острове")
    elif a.cmd == "dock":
        sys.exit(_dock_cmd(a.action, " ".join(a.what)))
    elif a.cmd == "launch":
        sys.exit(_launch_cmd(" ".join(a.query), show=a.list))
    elif a.cmd == "load":
        sys.exit(_load_cmd(as_json=a.json, watch=a.watch))
    elif a.cmd == "qr":
        from . import qr

        if a.wifi:
            import getpass

            # Пароль не в аргументах: их видно в `ps` всем на машине.
            pw = getpass.getpass("Пароль сети (пусто — открытая): ") if sys.stdin.isatty() else ""
            text = qr.wifi_payload(a.wifi, pw, hidden=a.hidden)
        else:
            text = " ".join(a.text)
        try:
            print(qr.ascii_art(qr.matrix(text)))
        except ValueError:
            sys.exit("justday qr: нечего кодировать — дайте ссылку или текст, либо --wifi ИМЯ")
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

        _print(desktop.windows(a.action.replace("-", "_"), " ".join(a.query)))
    elif a.cmd == "panel":
        from . import panel
        sys.exit(panel.main())
    elif a.cmd == "shell":
        from . import shell as shell_mod
        sys.exit(shell_mod.run(a.rest))
    elif a.cmd == "terminal":
        from . import terminal as terminal_mod
        sys.exit(terminal_mod.run(a.task, over_night=a.night, hours=a.hours, tell=a.tell,
                                  dark=a.dark))
    elif a.cmd == "work":
        from . import shell as shell_mod
        sys.exit(shell_mod.work(a.rest, force="shell" if a.shell else "claude" if a.claude else ""))
    elif a.cmd == "ui":
        from . import face
        sys.exit(face.run())
    elif a.cmd == "screenshot":
        _print(screenshot(a.all, a.full))
    elif a.cmd == "scene":
        from . import scenes

        if a.action == "run":
            _print(control("scene_run", id=" ".join(a.which), timeout=60))
        elif a.action == "add":
            got = scenes.save({"name": " ".join(a.which), "phrases": a.phrase, "open": a.open,
                               "close": a.close, "music": a.music, "say": a.say,
                               "silent": None if a.silent is None else a.silent == "on"})
            control("reload_settings", timeout=10)
            _print(got)
        elif a.action == "forget":
            got = scenes.forget(" ".join(a.which))
            control("reload_settings", timeout=10)
            _print(got)
        else:
            _print({"scenes": [{"id": s["id"], "name": s["name"], "phrases": s["phrases"],
                                "open": s["open"], "close": s["close"]} for s in scenes.all_scenes()]})
    elif a.cmd == "plan":
        from . import notes

        text = " ".join(a.text)
        if a.action == "add":
            _print(notes.add(text))
        elif a.action == "done":
            _print(notes.mark_done(text))
        elif a.action == "open":
            link = notes.open_in_obsidian(text or str(notes.plans_path()))
            subprocess.Popen(["xdg-open", link], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            _print({"ok": bool(link), "link": link})
        else:
            _print({"file": str(notes.plans_path()), "items": notes.items(only_open=bool(text != "all"))})
    elif a.cmd == "promise":
        from . import promises

        text = " ".join(a.text)
        if a.action == "add":
            _print(promises.add(text, a.to, a.due, source="cli"))
        elif a.action == "done":
            _print(promises.done(text))
        elif a.action == "find":
            _print({"items": promises.find(text)})
        else:
            _print({"items": promises.open_items(text)})
    elif a.cmd == "nudges":
        from . import observer

        got = observer.nudges(a.day)
        print("\n".join(f"{n['at']}  {n['text']}" for n in got) or "первым он сегодня ничего не говорил")
    elif a.cmd == "diary":
        from . import notes

        got = notes.diary(a.day, os.environ.get("JUSTDAY_TEXT", ""))
        if a.open:
            subprocess.Popen(["xdg-open", notes.open_in_obsidian(got["file"])],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        _print(got)
    elif a.cmd == "note":
        from . import notes

        _print(notes.note(a.title, " ".join(a.text) or os.environ.get("JUSTDAY_TEXT", ""), a.folder))
    elif a.cmd == "inbox":
        from . import inbox

        if a.action == "add":
            _print(control("inbox_add", text=" ".join(a.text), source="cli"))
        elif a.action == "clear":
            _print({"ok": True, "removed": inbox.clear()})
        else:
            _print({"pending": len(inbox.pending()), "items": inbox.recent()})
    elif a.cmd == "wake":
        from . import usage

        got = usage.wake_report(a.days)
        names = {"wake": "слово/имя", "button": "кнопка или клавиша", "phone": "телефон",
                 "cli": "командная строка", "?": "неизвестно"}
        print(f"Пробуждения за {a.days} дн.")
        print(f"{'откуда':<24}{'всего':>7}{'впустую':>9}")
        for source, row in sorted(got["sources"].items(), key=lambda kv: -kv[1]["woke"]):
            print(f"{names.get(source, source):<24}{row['woke']:>7}{row['empty']:>9}")
        total = got["total"]
        share = 100 * total["empty"] / max(1, total["woke"])
        print(f"{'всего':<24}{total['woke']:>7}{total['empty']:>9}   ({share:.0f}% впустую)")
        w = config.load()["wakeword"]
        print(f"\nпорог слова пробуждения: {w['threshold']}, при играющем звуке: "
              f"{w.get('threshold_while_playing')}")
        print("ложных много — поднимите порог: justday config set wakeword.threshold 0.6")
    elif a.cmd == "tokens":
        from . import usage

        got = usage.report(a.days)
        if a.json:
            _print(got)
            return
        n = usage.spaced
        print(f"Расход мозга за {a.days} дн.  (шаг — один запрос к модели, их в ответе обычно несколько)")
        print(f"{'дата':<12}{'шагов':>7}{'контекст/шаг':>15}{'ответ':>9}{'≈$':>9}")
        for row in [*got["days"], {"day": "всего", **got["total"]}]:
            day = row["day"][5:] if row["day"][:2].isdigit() else row["day"]
            print(f"{day:<12}{row['steps']:>7}{n(row['per_step']):>15}{n(row['out']):>9}{row['usd']:>9.2f}")
        window = config.load()["brain"]["context_window"]
        print(f"\nстартовый контекст последней сессии: {n(got['start_context'])} токенов")
        if window:
            print(f"потолок разговора: {n(window)} токенов, дальше история сжимается")
        print("разговор с нуля — «начни заново»: короткий контекст стоит в разы дешевле длинного")
    elif a.cmd == "history":
        from . import media

        # «играло» пишется при каждом запуске трека: фонотека и есть журнал, отдельного не заводим
        for i, r in enumerate(media.library()[: a.n], 1):
            when = time.strftime("%d.%m %H:%M", time.localtime(r.get("played", 0)))
            print(f"{i}. {when} — {r.get('artist') + ' — ' if r.get('artist') else ''}{r['title']}")
    elif a.cmd == "recent":
        from . import desktop

        _print(desktop.recent(a.hours))
    elif a.cmd == "guard":
        from . import manage

        _print(manage.guard(a.action))
    elif a.cmd == "session":
        from . import session

        if a.action == "list":
            _print(session.saved() or {"apps": []})
        elif a.action == "save":
            _print(session.save())
        else:
            _print(session.close(a.keep) if a.action == "close" else session.restore())
    elif a.cmd == "portable":
        import getpass

        from . import portable, providers

        keys = {}
        names = [k.strip() for k in a.keys.split(",") if k.strip()]
        for name in names:
            got = providers.secret_get(name)
            if got:
                keys[name] = got
            else:
                print(f"ключа «{name}» нет в связке — пропускаю")
        word = ""
        if keys:
            # Пароль спрашивается у человека и никуда не записывается: ни в файл, ни в журнал, ни
            # в память ассистента. Его знает только тот, кто носит флешку.
            word = getpass.getpass("Пароль для флешки: ")
            if word != getpass.getpass("Ещё раз: "):
                sys.exit("пароли не совпали")
        _print(portable.init(a.where, keys, word))
    elif a.cmd == "server":
        from . import server as server_mod

        _print(server_mod.on(a.why, hours=a.hours) if a.action == "on"
               else server_mod.off(resume=not a.quiet) if a.action == "off"
               else server_mod.status())
    elif a.cmd == "night":
        from . import terminal

        if a.status:
            _print(terminal.nightly_status())
        elif a.stop:
            _print(terminal.nightly_stop())
        else:
            task = " ".join(a.task).strip()
            if not task:
                sys.exit("Ночью нужна задача: justday night \"что сделать\"")
            if a.here:
                import asyncio
                sys.exit(asyncio.run(terminal.night(task, hours=a.hours, tell=not a.no_letter,
                                                    dark=not a.light)))
            sys.exit(terminal.nightly(task, hours=a.hours, tell=not a.no_letter, dark=not a.light))
    elif a.cmd == "reach":
        from . import phone

        _print(phone.reach(" ".join(a.text), urgent=a.urgent, subject=a.subject, which=a.to))
    elif a.cmd == "call":
        from . import telnyx

        text = " ".join(a.text).strip()
        got = telnyx.call(a.to, text, seconds=a.seconds or telnyx.MAX_SECONDS)
        _print(got)
        return 0 if got.get("ok") else 1
    elif a.cmd == "telegram":
        from . import telegram as tg

        try:
            if a.action == "status":
                _print({"ok": tg.ready(), "токен": bool(tg.token()), "кому": bool(tg.chat()),
                        "бот": tg.call("getMe").get("username", "") if tg.token() else ""})
            else:
                text = " ".join(a.text).strip()
                if not text:
                    raise RuntimeError("нечего отправлять")
                _print(tg.voice(text) if a.action == "voice" else tg.send(text))
        except RuntimeError as e:
            _print({"ok": False, "error": str(e)})
            return 1
    elif a.cmd == "phone":
        from . import phone

        try:
            if a.action == "list":
                _print(phone.devices())
            elif a.action == "ring":
                _print(phone.ring(a.to))
            elif a.action == "commands":
                _print(phone.commands(a.install))
            else:
                what = " ".join(a.args)
                _print(phone.notify(what, a.to) if a.action == "notify" else phone.send(what, a.to))
        except RuntimeError as e:  # the phone is off the network, or nothing is paired yet
            _print({"ok": False, "error": str(e)})
            sys.exit(1)
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
        elif a.action == "tempo":  # темп в самом образце голоса: чисто, без призвука растяжения
            voice = config.load()["tts"].get("voice", "jarvis")
            got = manage.voice_tempo(voice, float(args[0]) if args else 1.0)
            if got.get("ok"):
                # Растягивать речь после синтеза больше не нужно — это и был призвук.
                config.set_value("tts", "speed", 1.0)
                subprocess.run(["systemctl", "--user", "restart", "justday-voice.service"], capture_output=True)
                control("reload_settings", timeout=10)
            _print(got)
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
            _print({"ok": True, "stored_in": "keyring", "cleared": not key})
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

        if a.action == "restore":
            print("Возвращено:", ", ".join(manage.restore_shortcuts()) or "ничего (резервной записи нет)")
        elif a.action == "get":
            for row in manage.hotkey_list():
                mark = "✔" if row["live"] else ("·" if not row["key"] else "✘")
                taken = f"  ← занято: {', '.join(row['taken_by'])}" if row["taken_by"] else ""
                print(f"  {mark} {row['label']:<20} {row['key'] or '—'}{taken}")
        else:
            named = {name: getattr(a, f"key_{name}") for name, _, _ in manage.HOTKEYS}
            got = manage.set_hotkeys(extra=a.extra, **named)
            for key, was in got.get("taken_from", {}).items():
                print(f"  отобрал {key} у: {', '.join(was)}")
            for row in manage.hotkey_list():
                if row["key"]:
                    print(f"  {'✔' if row['live'] else '✘'} {row['label']:<20} {row['key']}")
            if not all(r["live"] for r in manage.hotkey_list() if r["key"]):
                print("\n  ✘ — клавишу держит кто-то другой; покажет кто: justday hotkey get")
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
        git_run = lambda *g: subprocess.run(["git", "-C", str(config.REPO_DIR), *g]).returncode  # noqa: E731
        ch = st["branch"]
        if st.get("on") != ch:      # ставились из main, а канал другой: переезжаем на него целиком
            ok = git_run("checkout", "--quiet", "-B", ch, f"origin/{ch}") == 0
        else:
            ok = git_run("pull", "--ff-only", "--quiet", "origin", ch) == 0
        if not ok:
            sys.exit("git pull не удался")
        from . import parts

        # Набор частей при обновлении не меняется и вопросов не задаёт: иначе обновление
        # молча снесло бы распознавание речи или, наоборот, докачало гигабайты без спроса.
        env = {**os.environ, "JUSTDAY_SETUP": "0", "JUSTDAY_YES": "1",
               "JUSTDAY_PARTS": ",".join(parts.installed()) or "-"}
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
            r = control("media_video", timeout=900, query=q, where=getattr(a, "where", "") or kw.get("where", ""))
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
    """The text selected right now (primary selection) — for "explain this", "translate this".

    Wayland answers through wl-paste, X11 through xclip: the shortcut works the same on both."""
    sel = ""
    for cmd in (["wl-paste", "--primary", "--no-newline", "--type", "text/plain"],
                ["xclip", "-o", "-selection", "primary"]):
        try:
            sel = subprocess.run(cmd, capture_output=True, text=True, timeout=1).stdout.strip()
        except (OSError, subprocess.SubprocessError):
            sel = ""
        if sel:
            break
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


def _emoji_cmd(query: str, *, show: bool = False, copy_only: bool = False) -> int:
    """`justday emoji кот` — первый подходящий сразу в то окно, где курсор."""
    from . import glyphs

    if not query:
        # Без запроса открывает сетку на островке: это его работа, а не терминала.
        got = control("panel", which="emoji", timeout=5)
        if got.get("ok"):
            return 0
        print("островок не отвечает; так тоже можно: justday emoji кот")
        return 1
    found = glyphs.search(query, limit=20 if show else 1)
    if not found:
        print(f"ничего не нашлось на «{query}»")
        return 1
    if show:
        for item in found:
            words = ", ".join(item.get("k", [])[:4])
            print(f"{item['c']}  {item['n']}" + (f"  ·  {words}" if words else ""))
        return 0
    got = glyphs.use(found[0]["c"], paste=not copy_only)
    print(glyphs.note_for(found[0]["c"]) + (f"  ({got['note']})" if got["note"] else "  вставлено"))
    return 0 if got["ok"] else 1


def _clip_cmd(action: str, which: str, *, search: str = "", image: bool = False,
              copy_only: bool = False) -> int:
    """История буфера обмена. `store` вызывает не человек, а наблюдатель за буфером."""
    from . import clipboard

    if action == "store":
        # Содержимое приходит на вход, как его отдаёт `wl-paste --watch`. Перед тем как запоминать,
        # спрашиваем сам буфер, не помечен ли он как секрет: так просят менеджеры паролей.
        got = clipboard.store_watched(sys.stdin.buffer.read(), image=image)
        return 0 if got.get("ok") or got.get("why") else 1
    if action == "wipe":
        print(f"забыто записей: {clipboard.wipe()}")
        return 0
    if action in ("pause", "resume"):
        on = action == "pause"
        print("история буфера на паузе" if clipboard.pause(on) else "история буфера снова пишется")
        return 0
    if action == "forget":
        if not which:
            print("что забыть? justday clip forget 3")
            return 1
        ok = clipboard.forget(which)
        print("забыто" if ok else "такой записи нет")
        return 0 if ok else 1
    if action == "use":
        got = clipboard.put_back(which or "1", paste=not copy_only)
        print(got.get("note") or got.get("error") or "вставлено")
        return 0 if got.get("ok") else 1

    if action == "pin":
        if not which:
            print("что закрепить? justday clip pin 3")
            return 2
        got = clipboard.pin(which, True)
        print("закреплено" if got.get("ok") else got.get("error", "не вышло"))
        return 0 if got.get("ok") else 1
    if action == "unpin":
        if not which:
            print("что открепить? justday clip unpin 3")
            return 2
        got = clipboard.pin(which, False)
        print("откреплено" if got.get("ok") else got.get("error", "не вышло"))
        return 0 if got.get("ok") else 1
    if action == "edit":
        if not which:
            print("что править? justday clip edit 3 новый текст")
            return 2
        # remaining words after `which` — or JUSTDAY_TEXT / stdin
        text = os.environ.get("JUSTDAY_TEXT", "")
        if not text:
            # cli passes only one which; extra args live in which if quoted wrongly —
            # prefer env, else stdin.
            import sys as _sys
            if not _sys.stdin.isatty():
                text = _sys.stdin.read()
        if not text:
            print("текст: JUSTDAY_TEXT='...' justday clip edit 3   или через stdin")
            return 2
        got = clipboard.edit(which, text)
        print(got.get("preview") if got.get("ok") else got.get("error", "не вышло"))
        return 0 if got.get("ok") else 1
    if action == "show":
        if not which:
            which = "1"
        got = clipboard.text_of(which)
        if not got.get("ok"):
            print(got.get("error", "нет"))
            return 1
        if got.get("kind") == "image":
            print(got.get("file", ""))
        else:
            print(got.get("text", ""), end="" if str(got.get("text", "")).endswith("\n") else "\n")
        return 0

    items = clipboard.items(int(os.environ.get("JUSTDAY_CLIP_LIMIT", "25")), search)
    if not items:
        print("история пуста" + (f" — по «{search}» ничего" if search else ""))
        return 0
    now = time.time()
    for n, item in enumerate(items, 1):
        ago = now - item["at"]
        when = (f"{int(ago)}с" if ago < 60 else f"{int(ago // 60)}м" if ago < 3600
                else f"{int(ago // 3600)}ч" if ago < 86400 else f"{int(ago // 86400)}д")
        mark = ("📌" if item.get("pinned") else " ") + ("🖼" if item["kind"] == "image" else " ")
        print(f"{n:>3} {when:>4} {mark} {item['preview']}")
    if clipboard.paused():
        print("\n(на паузе: новое не запоминается — justday clip resume)")
    elif (missed := clipboard.skipped()["count"]):
        print(f"\n(пропущено как похожее на пароль или ключ: {missed})")
    return 0


def _dock_cmd(action: str, what: str) -> int:
    """Показать док или изменить его состав. Ключ — идентификатор .desktop-файла без расширения.

    Без идентификатора `pin`/`unpin` действует на программу активного окна (горячая клавиша).
    `go N` — запустить/сфокусировать N-ю программу слева направо (Meta+N).
    """
    from . import dock

    if action == "go":
        n = (what or "1").split()[0] if what else "1"
        got = dock.go(n)
        if not got.get("ok"):
            print(got.get("error") or "не вышло")
            return 1
        act = "фокус" if got.get("action") == "focus" else "запуск"
        print(f"  {act}: {got.get('name') or got.get('id')}  (слот {got.get('n')})")
        return 0
    if action == "show":
        got = dock.catalog()
        if not got["items"]:
            return print("док пуст") or 0
        for item in got["items"]:
            print(f"  {item['name']:28} {item['id']}")
        return 0
    # Через демон — островок сразу увидит новый состав (publish), а не только файл на диске.
    if not what:
        on = None if action == "pin" else False
        got = control("dock_pin", kind="app", id="", on=on, timeout=8)
        # Демон не запущен — сделаем сами; UI обновится при следующем dockRefresh.
        if not got.get("ok") and "daemon is not running" in str(got.get("error") or ""):
            got = dock.pin_focused(on)
        if not got.get("ok"):
            msg = got.get("error") or "не вышло"
            print(msg)
            subprocess.run(["notify-send", "-a", "JustDay", "Док", str(msg)], check=False)
            return 1
        name = got.get("name") or got.get("id") or ""
        line = ("закреплено: " if got.get("on") else "откреплено: ") + str(name)
        print(line)
        subprocess.run(["notify-send", "-a", "JustDay", "Док", line], check=False)
        return 0
    kind, _, ident = what.partition(":")
    if not ident:
        kind, ident = "app", what
    on = action == "pin"
    got = control("dock_pin", kind=kind, id=ident, on=on, timeout=8)
    if not got.get("ok") and "daemon is not running" in str(got.get("error") or ""):
        got = dock.pin(kind, ident, on)
    if not got.get("ok"):
        print(got.get("error") or "не вышло")
        return 1
    print(("закреплено: " if got.get("on") else "откреплено: ") + ident)
    return 0


def _launch_cmd(query: str, *, show: bool = False) -> int:
    """`justday launch` — лаунчер в островке; с запросом запускает первое подходящее."""
    from . import launcher

    if not query:
        got = control("panel", which="apps", timeout=5)
        if got.get("ok"):
            return 0
        print("островок не отвечает; так тоже можно: justday launch дискорд")
        return 1
    found = launcher.items(query, limit=12 if show else 1)
    if not found:
        print(f"ничего не нашлось на «{query}»")
        return 1
    if show:
        for item in found:
            kind = {"app": "программа", "game": "игра", "window": "окно"}.get(item["kind"], item["kind"])
            print(f"{item['name']}  ·  {kind}" + (f"  ·  {item['sub']}" if item["sub"] else ""))
        return 0
    got = launcher.run(found[0]["kind"], found[0]["id"])
    print(found[0]["name"] if got.get("ok") else f"не вышло: {got.get('error')}")
    return 0 if got.get("ok") else 1


def _load_cmd(*, as_json: bool = False, watch: bool = False) -> int:
    """Нагрузка машины. Без --json — то, что читается глазами."""
    from . import sysload

    load = sysload.Load()
    load.snapshot()          # первый взгляд не с чем сравнивать
    while True:
        time.sleep(1.0)
        snap = load.snapshot()
        if as_json:
            print(json.dumps(snap, ensure_ascii=False))
        else:
            cpu, mem, gpu = snap["cpu"], snap["memory"], snap["gpu"]
            if watch:
                print("\033[2J\033[H", end="")
            print(f"процессор  {cpu['percent']:>5.1f}%   ({cpu['count']} ядер, "
                  f"средняя {', '.join(f'{x:.2f}' for x in snap['load'])})")
            print(f"память     {mem['percent']:>5.1f}%   {mem['used'] / 1024:.1f} из {mem['total'] / 1024:.1f} ГБ"
                  + (f", подкачка {mem['swap_used']} МБ" if mem["swap_used"] > 64 else ""))
            if gpu:
                print(f"видеокарта {gpu['percent']:>5.1f}%   {gpu['name']}, "
                      f"{gpu['mem_used']} из {gpu['mem_total']} МБ, {gpu['c']:.0f}°")
            if snap["hot"]:
                print(f"температура      {snap['hot']['c']:.0f}°  ({snap['hot']['label']})")
            print(f"сеть         ↓{snap['net']['rx_kb']:.0f} ↑{snap['net']['tx_kb']:.0f} КБ/с"
                  f"   диск ↓{snap['io']['read_mb']:.1f} ↑{snap['io']['write_mb']:.1f} МБ/с")
            for disk in snap["disks"]:
                print(f"  {disk['where']:<12} {disk['percent']:>5.1f}%  свободно {disk['free_gb']:.0f} ГБ")
            print("тяжелее всех:")
            for proc in snap["top"]:
                print(f"  {proc['cpu']:>5.1f}%  {proc['mem_mb']:>5} МБ  {proc['name']}")
        if not watch:
            return 0


def _parts_cmd(action: str, names: list[str]) -> int:
    """Необязательные части окружения: посмотреть, доставить, убрать."""
    from . import parts

    if action == "list":
        print("Части JustDay\n")
        for name, part in parts.PARTS.items():
            here = parts.have(name)
            mark = "✓" if here else "·"
            print(f"  {mark} {name:<8} {part.size:>8}  {part.what}")
            if not here:
                print(f"    {'':<8} {'':>8}  без неё: {part.without}")
        rest = [n for n in parts.suggested() if not parts.have(n)]
        print()
        if rest:
            print(f"  Доставить: justday parts add {' '.join(rest)}")
        if not parts.gpu() and parts.have("cuda"):
            print("  Видеокарты NVIDIA тут нет — часть cuda занимает место впустую: justday parts remove cuda")
        return 0

    if not names:
        print(f"что именно {action}? {' | '.join(parts.PARTS)}")
        return 2
    add_, drop = (tuple(names), ()) if action == "add" else ((), tuple(names))
    ok, cmd = parts.sync(add_, drop, dry=True)
    if not ok:
        print(cmd)
        return 2
    print(f"{cmd}\n  скачивание может занять минуты — размер частей смотрите в `justday parts`")
    ok, out = parts.sync(add_, drop, show=True)      # шкалу uv лучше видеть своими глазами
    print(out or ("готово" if ok else "не получилось"))
    if ok:
        subprocess.run(["systemctl", "--user", "restart", "justday.service"], capture_output=True)
    return 0 if ok else 1


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
    from . import manage

    value = manage.set_setting(a.key, a.value)
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
        print("\nбесплатно: justday model use openrouter openrouter/free | "
              "justday model use ollama qwen3.5:9b (на вашей видеокарте)"
              "\nплатно: justday model use claude sonnet")
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
