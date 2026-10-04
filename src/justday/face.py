"""Что видно на экране в этом сеансе: остров или запасная полоска.

Раньше это решал установщик — один раз, по тому сеансу, из которого его запустили. На компьютере,
где на экране входа есть и Wayland, и X11 (школьный, рабочий, да любой с выбором), это выходило так:

* поставил из Wayland, вошёл через X11 — служба честно запускала остров, а запасная полоска была
  отключена, так что при осечке не оставалось ничего;
* поставил из X11, вошёл через Wayland — получал полоску, а острова не было вовсе: Quickshell в
  этом случае даже не ставился, и появиться ему было откуда.

Теперь решение принимается при каждом входе. Служба одна — `justday-ui.service`; она смотрит, в
какой сеанс вошли, и запускает то, что в нём работает. Переключился на другой сеанс — при
следующем входе увидишь то, что ему подходит, и ничего переустанавливать не нужно.

Выбор можно закрепить: `ui.face` = auto (по сеансу) | island | panel.

    justday ui               # обычно её запускает justday-ui.service
"""
from __future__ import annotations

import os
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

from . import config

ISLAND_DIR: Path = config.REPO_DIR / "island"


def session() -> str:
    """Тип сеанса: "wayland", "x11" или "" — не опознан.

    Порядок неслучаен. WAYLAND_DISPLAY — самый надёжный признак: он есть только там, где есть
    вейландовый сокет. XDG_SESSION_TYPE говорит то же словами. Если служба поднялась раньше, чем
    сеанс донёс переменные до systemd, спрашиваем logind — он знает тип точно."""
    if os.environ.get("WAYLAND_DISPLAY"):
        return "wayland"
    kind = (os.environ.get("XDG_SESSION_TYPE") or "").lower()
    if kind in ("wayland", "x11"):
        return kind
    try:
        got = subprocess.run(["loginctl", "show-session", os.environ.get("XDG_SESSION_ID") or "self",
                              "-p", "Type", "--value"], capture_output=True, text=True, timeout=5)
        kind = got.stdout.strip().lower()
        if kind in ("wayland", "x11"):
            return kind
    except (OSError, subprocess.SubprocessError):
        pass
    return "x11" if os.environ.get("DISPLAY") else ""


def quickshell() -> str:
    """Чем запускать остров. Пакет зовётся по-разному: `qs` в Fedora и Arch, `quickshell` местами."""
    return shutil.which("qs") or shutil.which("quickshell") or ""


def pick() -> tuple[str, str]:
    """Что показывать и почему. Причину печатаем в журнал и в `justday doctor`: «почему у меня
    полоска вместо острова» — первый вопрос, и отвечать на него должна сама программа."""
    want = str(config.load()["ui"].get("face", "auto")).lower()
    qs, kind = quickshell(), session()

    if want == "island":
        return ("island", "задано в настройках") if qs else \
               ("panel", "в настройках остров, но Quickshell не установлен")
    if want == "panel":
        return "panel", "задано в настройках"
    if kind == "wayland":
        return ("island", "сеанс Wayland") if qs else \
               ("panel", "сеанс Wayland, но Quickshell не установлен")
    # Остров рисуется через wlr-layer-shell, которого на X11 нет. Quickshell там всё же
    # запускается и делает окно-док, но клавиатуру оно не захватывает — поле «написать» осталось
    # бы мёртвым. Поэтому по умолчанию полоска, а попробовать остров можно через ui.face.
    return "panel", f"сеанс {kind or 'не опознан'}: острову нужен wlr-layer-shell (только Wayland)"



def wait_daemon(timeout: float = 12.0) -> bool:
    path = config.SOCKET_PATH
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as s:
                s.settimeout(0.4)
                s.connect(str(path))
            return True
        except OSError:
            time.sleep(0.25)
    return False

def run() -> int:
    """Запустить то, что подходит этому сеансу. Остров подменяет собой этот же процесс, чтобы
    systemd следил за ним самим, а не за обёрткой."""
    os.environ.setdefault("QS_DISABLE_FILE_WATCHER", "1")
    os.environ.setdefault("QS_NO_RELOAD_POPUP", "1")
    what, why = pick()
    print(f"justday ui: {what} — {why}", file=sys.stderr, flush=True)
    if what == "island":
        if wait_daemon():
            print("justday ui: daemon socket ready", file=sys.stderr, flush=True)
        else:
            print("justday ui: socket missing, attaching live", file=sys.stderr, flush=True)
        exe = quickshell()
        # Цикл отрисовки Qt. «basic» (его Qt выбирает сам) крутит анимации таймером на 16 мс —
        # шестьдесят шагов в секунду при любой развёртке, и на 165 герцах движение идёт ступеньками.
        # «threaded» привязывает их к развёртке, но заставляет оболочку рисоваться в два-три раза
        # чаще; на видеокарте, занятой игрой, это ощущается хуже ступенек. Правильного ответа нет —
        # поэтому по умолчанию решает Qt, а island.render_loop отдаёт выбор человеку.
        loop = str((config.load()["island"] or {}).get("render_loop", "auto")).lower()
        if loop in ("threaded", "basic") and "QSG_RENDER_LOOP" not in os.environ:
            os.environ["QSG_RENDER_LOOP"] = loop
        os.execvp(exe, [exe, "-p", str(ISLAND_DIR)])
    from . import panel
    return panel.main()
