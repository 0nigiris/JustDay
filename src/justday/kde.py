"""Имена утилит настроек KDE: на Plasma 5 нет `kreadconfig6`, есть `kreadconfig5`.

Мастер первой настройки на школьном компьютере с Plasma 5 падал с FileNotFoundError на
`kreadconfig6`. Если нет ни той, ни другой, остаётся имя «6»: вызов тогда даёт OSError,
который места вызова и так умеют ловить.
"""
import shutil


def _pick(name: str) -> str:
    for v in (6, 5):
        if shutil.which(f"{name}{v}"):
            return f"{name}{v}"
    return f"{name}6"


KREAD = _pick("kreadconfig")
KWRITE = _pick("kwriteconfig")


def session() -> tuple[str, str]:
    """(версия Plasma, тип сеанса) этой машины: («6», «wayland»), («5», «x11»).

    Персона и навыки раньше говорили «Plasma 6, Wayland» всем: на X11 мозг тянулся к инструментам, которых
    там нет, и не перезапускал бы `kwin_x11`, потому что ему сказали про `kwin_wayland` (issue 5)."""
    import os
    kind = (os.environ.get("XDG_SESSION_TYPE") or "wayland").lower()
    return ("5" if KWRITE.endswith("5") else "6"), ("x11" if kind == "x11" else "wayland")
