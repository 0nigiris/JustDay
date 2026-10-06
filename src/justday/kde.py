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
