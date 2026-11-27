import sys


def _hide_consoles(subprocess) -> None:
    """На Windows демон живёт без консоли (DETACHED_PROCESS, host.py), и каждый консольный ребёнок —
    powershell, where, ffmpeg — открывал своё чёрное окно поверх островка (27 нояб.: «никаких лишних
    окон»). Вызовов subprocess полсотни в разных файлах, asyncio идёт через тот же Popen, поэтому
    прятать здесь, один раз, а не в каждом вызове. Кто сам просит консоль или отсоединение — тому не мешаем."""
    init = subprocess.Popen.__init__
    own = subprocess.CREATE_NEW_CONSOLE | subprocess.DETACHED_PROCESS

    def quiet(self, *args, creationflags=0, **kw):
        if not creationflags & own:
            creationflags |= subprocess.CREATE_NO_WINDOW
        init(self, *args, creationflags=creationflags, **kw)

    subprocess.Popen.__init__ = quiet


if sys.platform == "win32":
    import subprocess

    _hide_consoles(subprocess)
