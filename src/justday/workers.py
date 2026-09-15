"""Claude Code worker sessions — thin wrapper over the official `claude --bg` / `claude agents` CLI.

JustDay's brain calls these via `justday claude …` shell commands. We only add what the CLI lacks:
  * a registry of sessions JustDay started (so the daemon can report when they finish),
  * reading the final answer / edited files from the session transcript,
  * "send a follow-up" = stop the idle process, then `--bg --resume` the same session.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import time
from pathlib import Path

from . import config, events, providers

WORKER_SETTINGS = json.dumps({"worktree": {"bgIsolation": "none"}})
WORKER_RULES = (
    "\n\n(Правила от JustDay: работай прямо в этой рабочей копии; не делай git commit/push, "
    "не переписывай историю — git оставь пользователю. В конце кратко перечисли, что изменил и как проверить.)"
)


def _claude() -> str:
    return shutil.which(config.load()["brain"]["claude_cli"]) or "claude"


def agents(include_done: bool = True) -> list[dict]:
    cmd = [_claude(), "agents", "--json"] + (["--all"] if include_done else [])
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=30).stdout
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return []


def _registry() -> dict:
    return events.load_state().get("workers", {})


def _register(short_id: str, **info) -> None:
    reg = _registry()
    reg[short_id] = {**reg.get(short_id, {}), **info}
    events.save_state(workers=reg)


def _find(ident: str) -> dict | None:
    for a in agents():
        if a.get("id") == ident or a.get("sessionId") == ident or (a.get("sessionId") or "").startswith(ident):
            return a
    return None


def _bg(cwd: str, prompt: str, resume: str | None = None, model: str | None = None) -> str:
    cfg = config.load()
    wcfg = cfg["workers"]
    # auto mode needs a Claude model; with other providers edits are auto-accepted and shell commands wait for you
    mode = wcfg["permission_mode"] if providers.is_claude(cfg) else "acceptEdits"
    cmd = [_claude(), "--bg", "--permission-mode", mode, "--settings", WORKER_SETTINGS]
    model = model or wcfg.get("model") or (None if providers.is_claude(cfg) else cfg["brain"]["model"])
    if model:
        cmd += ["--model", model]
    if resume:
        cmd += ["--resume", resume]
    cmd.append(prompt)
    p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=120,
                       env={**os.environ, **providers.env(cfg)})
    m = re.search(r"backgrounded\s*·\s*([0-9a-f]{8})", p.stdout + p.stderr)
    if not m:
        raise RuntimeError(f"claude --bg failed: {(p.stdout + p.stderr).strip()[:500]}")
    return m.group(1)


def start(cwd: str, prompt: str, model: str | None = None) -> dict:
    cwd = str(Path(cwd).expanduser().resolve())
    sid = _bg(cwd, prompt + WORKER_RULES, model=model)
    time.sleep(1.5)
    info = _find(sid) or {"id": sid}
    _register(sid, cwd=cwd, task=prompt, session_id=info.get("sessionId"), started=time.time(), reported_state=None)
    events.emit("worker_start", id=sid, cwd=cwd, task=prompt)
    return {"id": sid, "session_id": info.get("sessionId"), "cwd": cwd}


def send(ident: str, message: str) -> dict:
    a = _find(ident)
    if not a:
        raise RuntimeError(f"no Claude session {ident}")
    if a.get("pid") and a.get("state") == "working":
        raise RuntimeError("session is still working; wait for it or stop it first")
    if a.get("pid"):
        subprocess.run([_claude(), "stop", a["id"]], capture_output=True, timeout=60)
        time.sleep(1)
    sid = _bg(a["cwd"], message + WORKER_RULES, resume=a["sessionId"])
    _register(sid, cwd=a["cwd"], task=message, session_id=a["sessionId"], started=time.time(), reported_state=None)
    events.emit("worker_send", id=sid, message=message)
    return {"id": sid, "session_id": a["sessionId"]}


def transcript_path(session_id: str) -> Path | None:
    hits = list((Path.home() / ".claude" / "projects").glob(f"*/{session_id}.jsonl"))
    return max(hits, key=lambda p: p.stat().st_mtime) if hits else None


def result(ident: str) -> dict:
    a = _find(ident) or {}
    session_id = a.get("sessionId") or _registry().get(ident, {}).get("session_id") or ident
    path = transcript_path(session_id)
    if not path:
        raise RuntimeError(f"no transcript for {ident}")
    last_text, edited, tools, errors = "", [], 0, 0
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            rec = json.loads(line)
        except json.JSONDecodeError:
            continue
        msg = rec.get("message") or {}
        content = msg.get("content")
        if not isinstance(content, list):
            continue
        texts = []
        for c in content:
            if c.get("type") == "text" and rec.get("type") == "assistant":
                texts.append(c["text"])
            elif c.get("type") == "tool_use":
                tools += 1
                fp = (c.get("input") or {}).get("file_path")
                if c.get("name") in ("Edit", "Write", "NotebookEdit") and fp and fp not in edited:
                    edited.append(fp)
            elif c.get("type") == "tool_result" and c.get("is_error"):
                errors += 1
        if texts:
            last_text = "\n".join(texts)
    return {
        "id": a.get("id", ident), "state": a.get("state"), "status": a.get("status"),
        "waiting_for": a.get("waitingFor"), "cwd": a.get("cwd"), "final_message": last_text,
        "files_edited": edited, "tool_calls": tools, "tool_errors": errors, "transcript": str(path),
    }


def stop(ident: str) -> str:
    a = _find(ident)
    p = subprocess.run([_claude(), "stop", a["id"] if a else ident], capture_output=True, text=True, timeout=60)
    events.emit("worker_stop", id=ident)
    return (p.stdout + p.stderr).strip()


def open_terminal(ident: str | None, cwd: str | None = None) -> None:
    """Show a worker (claude attach) or a fresh interactive Claude Code in a visible terminal."""
    term = shutil.which("kitty") or shutil.which("konsole")
    if ident:
        a = _find(ident)
        args, wd = [_claude(), "attach", a["id"] if a else ident], (a or {}).get("cwd") or str(Path.home())
    else:
        args, wd = [_claude()], str(Path(cwd or Path.home()).expanduser())
    if term and term.endswith("kitty"):
        cmd = [term, "--detach", "--directory", wd, *args]
    elif term:
        cmd = [term, "--workdir", wd, "-e", *args]
    else:
        raise RuntimeError("no terminal emulator found (kitty/konsole)")
    subprocess.Popen(cmd, start_new_session=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def pending_reports() -> tuple[list[dict], int]:
    """Workers started by JustDay whose state changed to something the brain should react to,
    plus how many of them are still working."""
    reg = _registry()
    if not reg:
        return [], 0
    live = {a.get("id"): a for a in agents()}
    active = sum(1 for sid in reg if (live.get(sid) or {}).get("state") == "working")
    out = []
    for sid, info in reg.items():
        a = live.get(sid)
        state = a.get("state") if a else "gone"
        if state in ("working", None) or state == info.get("reported_state"):
            continue
        info["reported_state"] = state
        out.append({"id": sid, "state": state, "waiting_for": (a or {}).get("waitingFor"), **info})
    if out:
        events.save_state(workers=reg)
    return out, active
