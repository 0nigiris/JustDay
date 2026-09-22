"""Run the Dynamic Island inside an isolated, headless KWin (kwin-mcp) for screenshots and clicks.

    $(uv tool dir)/kwin-mcp/bin/python tests/ui/island_session.py /tmp/jd
    echo "shot name" > /tmp/jd/ctl      → /tmp/jd/name.png (1600×900)
    echo "click 800 40" > /tmp/jd/ctl   ·  "scroll 800 400 -5"  ·  "key Escape"  ·  "type text"  ·  "quit"
IPC into that island: qs ipc --pid <pid from `qs list --all`, display wayland-mcp-*> call island settingsPage voice
"""
import os
import shutil
import subprocess
import sys
from pathlib import Path

from kwin_mcp import server

work = Path(sys.argv[1])
work.mkdir(parents=True, exist_ok=True)
repo = Path(__file__).resolve().parents[2]
eng = server._engine
print(eng.session_start(screen_width=1600, screen_height=900), flush=True)
env = eng._session_env()
env.update(JUSTDAY_SOCKET=str(work / "fake.sock"), HOME=os.path.expanduser("~"), JUSTDAY_ISLAND_MUTE="1",
           JUSTDAY_ISLAND_WALLPAPER=os.environ.get("JUSTDAY_ISLAND_WALLPAPER", "1"))  # or a picture for screenshots
for k in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME"):
    env.pop(k, None)
if os.environ.get("JUSTDAY_SHOTS_CONFIG_HOME"):  # README shots: Settings read a fresh config, not this machine's
    env["XDG_CONFIG_HOME"] = os.environ["JUSTDAY_SHOTS_CONFIG_HOME"]
qs = subprocess.Popen(["qs", "-p", str(repo / "island")], env=env, stdout=open(work / "qs.log", "w"), stderr=subprocess.STDOUT)
ctl = work / "ctl"
if not ctl.exists():
    os.mkfifo(ctl)
while True:
    with open(ctl) as f:
        for line in f:
            cmd = line.split()
            if not cmd:
                continue
            if cmd[0] == "shot":
                out = eng.screenshot()
                shutil.copy(out.split("Screenshot saved: ")[1].split(" (")[0], work / f"{cmd[1]}.png")
            elif cmd[0] == "click":
                eng.mouse_click(int(cmd[1]), int(cmd[2]))
            elif cmd[0] == "scroll":  # scroll X Y DELTA (negative = down)
                eng.mouse_scroll(int(cmd[1]), int(cmd[2]), delta=int(cmd[3]))
            elif cmd[0] == "drag":  # drag X1 Y1 X2 Y2 (flick a list)
                eng.mouse_drag(int(cmd[1]), int(cmd[2]), int(cmd[3]), int(cmd[4]))
            elif cmd[0] == "key":
                eng.keyboard_key(cmd[1])
            elif cmd[0] == "type":
                eng.keyboard_type(" ".join(cmd[1:]))
            elif cmd[0] == "quit":
                qs.terminate()
                eng.session_stop()
                sys.exit(0)
