#!/usr/bin/env python3
"""Тонкая панель Plasma под сплошной верхней полосой.

Исключительная зона layer-shell двигает окна, но «Вид папки» на рабочем столе ужимается только
под настоящую панель. Эта панель и есть распорка, сверху по ней рисует полоса JustDay. Режим off
убирает её, иначе после возврата к островку или вырезу наверху остаётся полоска пустоты.

Номер поколения нужен, чтобы запоздавшее «on» от прежнего вида проиграло пришедшему позже «off».
"""
import fcntl
import os
import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    mode = sys.argv[1] if len(sys.argv) > 1 else "off"
    height = int(sys.argv[2]) if len(sys.argv) > 2 else 44
    sx = int(sys.argv[3]) if len(sys.argv) > 3 else 0
    sy = int(sys.argv[4]) if len(sys.argv) > 4 else 0
    try:
        gen = int(float(sys.argv[5])) if len(sys.argv) > 5 else 0
    except ValueError:
        gen = 0
    height = max(28, min(96, height))
    # drop — панель убрана и отступ рабочего стола пересчитан; только при уходе со сплошной полосы.
    refresh = mode == "drop"
    on = "true" if mode == "on" else "false"
    runtime = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp"))
    lock_path = runtime / "justday-bar-strut.lock"
    gen_path = runtime / "justday-bar-strut.gen"
    runtime.mkdir(parents=True, exist_ok=True)
    with lock_path.open("a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        try:
            current = int(gen_path.read_text() or "0")
        except (OSError, ValueError):
            current = 0
        if gen and gen < current:
            print("stale")
            return 0
        if gen:
            gen_path.write_text(str(gen))
        js = f"""
var wantX = {sx};
var wantY = {sy};
var screenIndex = 0;
for (var i = 0; i < screenCount; i++) {{
  var g = screenGeometry(i);
  if (g.x === wantX && g.y === wantY) screenIndex = i;
}}
function marked(p) {{
  var v = p.readConfig("justdayBar", "");
  return v === "1" || v === 1 || v === true || String(v) === "1";
}}
var mine = null;
var ps = panels();
for (var i = 0; i < ps.length; i++) {{
  if (!marked(ps[i])) continue;
  if (mine) ps[i].remove();
  else mine = ps[i];
}}
if (!{on}) {{
  var removed = mine ? 1 : 0;
  if (mine) mine.remove();
  ps = panels();
  for (var j = 0; j < ps.length; j++) if (marked(ps[j])) {{ ps[j].remove(); removed++; }}
  print("off " + removed);
}} else {{
  if (!mine) {{
    mine = new Panel;
    mine.writeConfig("justdayBar", "1");
  }}
  mine.screen = screenIndex;
  mine.location = "top";
  mine.floating = false;
  mine.hiding = "none";
  mine.lengthMode = "fill";
  mine.height = {height};
  mine.opacity = "translucent";
  mine.backgroundHints = 0;
  if (!mine.widgetIds || mine.widgetIds.length === 0)
    mine.addWidget("org.kde.plasma.panelspacer");
  print("on " + mine.id + " " + mine.height);
}}
"""
        # В Fedora это qdbus-qt6, в Arch qdbus6. Здесь стояло одно имя, и на Fedora распорка не
        # создавалась никогда: скрипт падал, а рабочий стол уезжал под сплошную полосу.
        qdbus = next(filter(None, map(shutil.which, ("qdbus6", "qdbus-qt6", "qdbus"))), "")
        if not qdbus:
            print("нет qdbus: распорку не создать", file=sys.stderr)
            return 1
        r = subprocess.run(
            [qdbus, "org.kde.plasmashell", "/PlasmaShell", "org.kde.PlasmaShell.evaluateScript", js],
            capture_output=True, text=True,
        )
    sys.stdout.write(r.stdout)
    sys.stderr.write(r.stderr)
    if r.returncode == 0 and refresh and "off 0" not in r.stdout:
        subprocess.run(
            [qdbus, "org.kde.plasmashell", "/PlasmaShell", "org.kde.PlasmaShell.refreshCurrentShell"],
            check=False,
        )
    return r.returncode


if __name__ == "__main__":
    raise SystemExit(main())
