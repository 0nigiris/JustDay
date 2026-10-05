"""Завершение сеанса: заблокировать, выйти, сон, перезагрузка, выключение.

Это то, что в KDE спрятано под кнопкой питания в меню приложений, и меню островка обязано уметь
то же самое — иначе оно не замена, а половина замены.

Два правила, из которых всё остальное следует.

Первое: просим KDE, а не systemd. `org.kde.Shutdown` даёт программам сохранить несохранённое и
закрыть себя по-человечески; `systemctl poweroff` просто гасит машину вместе с открытым редактором.
К systemd уходим, только если KDE на шине нет (другая оболочка, голый сеанс).

Второе: опасное требует подтверждения. Выход, перезагрузка и выключение теряют работу, поэтому
`run()` без `confirm=True` их не делает вовсе — это не вежливость вида, а запрет в самой функции.
Сон и блокировка ничего не теряют и подтверждения не просят: «Вы уверены?» перед блокировкой
экрана — ровно тот случай, когда защита начинает мешать.
"""
from __future__ import annotations

import getpass
import os
import pwd
import shutil
import socket
import subprocess
from pathlib import Path


# id, подпись, значок, теряет ли несохранённое
def _qdbus_bin() -> str:
    from .desktop import qdbus_bin  # одно место поиска qdbus на всё (Р-68)

    return qdbus_bin()



ACTIONS: tuple[tuple[str, str, str, bool], ...] = (
    ("lock", "Заблокировать", "lock", False),
    ("sleep", "Сон", "moon", False),
    ("logout", "Выйти", "log-out", True),
    ("reboot", "Перезагрузить", "refresh-cw", True),
    ("poweroff", "Выключить", "power", True),
)
DANGEROUS = frozenset(a for a, _, _, danger in ACTIONS if danger)

# Сначала KDE (закрывает программы по-хорошему), потом запасной путь.
_WAYS: dict[str, tuple[list[str], list[str]]] = {
    "lock": (["loginctl", "lock-session"], ["loginctl", "lock-session"]),
    "sleep": (["systemctl", "suspend"], ["systemctl", "suspend"]),
    # Первый аргумент «qdbus» подставляется из _qdbus_bin() в run()/_kde_alive().
    "logout": (["qdbus", "org.kde.Shutdown", "/Shutdown", "logout"], ["loginctl", "terminate-user", ""]),
    "reboot": (["qdbus", "org.kde.Shutdown", "/Shutdown", "logoutAndReboot"], ["systemctl", "reboot"]),
    "poweroff": (["qdbus", "org.kde.Shutdown", "/Shutdown", "logoutAndShutdown"], ["systemctl", "poweroff"]),
}


def actions() -> list[dict]:
    """Что показать в меню. Порядок — от безобидного к необратимому."""
    return [{"id": a, "name": name, "icon": icon, "danger": danger} for a, name, icon, danger in ACTIONS]


def _kde_alive() -> bool:
    bin = _qdbus_bin()
    if not bin:
        return False
    try:
        got = subprocess.run([bin, "org.kde.Shutdown"], capture_output=True, timeout=4)
        return got.returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def run(what: str, *, confirm: bool = False) -> dict:
    """Выполнить действие. Опасное — только с confirm=True."""
    if what not in _WAYS:
        return {"ok": False, "error": f"нет такого действия: {what}"}
    if what in DANGEROUS and not confirm:
        return {"ok": False, "error": "нужно подтверждение", "confirm": True}
    kde, plain = _WAYS[what]
    cmd = kde if _kde_alive() else plain
    if cmd and cmd[0] == "qdbus":
        bin = _qdbus_bin()
        if not bin:
            cmd = plain
        else:
            cmd = [bin, *cmd[1:]]
    if cmd[-1] == "":                                   # loginctl terminate-user <кто>
        import getpass
        cmd = [*cmd[:-1], getpass.getuser()]
    if not shutil.which(cmd[0]):
        return {"ok": False, "error": f"нечем: нет {cmd[0]}"}
    try:
        # Не ждём: выключение завершает и нас самих, а `run` должен успеть ответить островку.
        subprocess.Popen(cmd, start_new_session=True,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError as e:
        return {"ok": False, "error": str(e)}
    return {"ok": True, "did": what}


def user() -> dict:
    """Кто за машиной: имя в шапку меню и картинка, если её когда-то ставили.

    Картинку ищем там же, где её держит KDE, — чтобы меню показывало то же лицо, что и экран входа,
    а не заводило себе второе.
    """
    login = getpass.getuser()
    try:
        full = pwd.getpwnam(login).pw_gecos.split(",")[0].strip()
    except (KeyError, OSError):
        full = ""
    avatar = ""
    for p in (Path.home() / ".face.icon", Path.home() / ".face",
              Path(f"/var/lib/AccountsService/icons/{login}")):
        try:
            if p.is_file() and os.access(p, os.R_OK):
                avatar = str(p)
                break
        except OSError:
            continue
    return {"login": login, "name": full or login, "host": socket.gethostname(), "avatar": avatar}
