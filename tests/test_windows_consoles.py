import types

from justday import _hide_consoles


def _fake():
    class Popen:
        def __init__(self, *args, creationflags=0, **kw):
            self.flags = creationflags

    return types.SimpleNamespace(Popen=Popen, CREATE_NEW_CONSOLE=0x10, DETACHED_PROCESS=0x8, CREATE_NO_WINDOW=0x08000000)


def test_child_of_daemon_does_not_pop_a_black_window():
    """На Windows каждый powershell/ffmpeg из демона открывал своё консольное окно поверх островка."""
    sp = _fake()
    _hide_consoles(sp)
    assert sp.Popen(["where", "ffmpeg"]).flags == sp.CREATE_NO_WINDOW
    assert sp.Popen(["x"], creationflags=0x200).flags == 0x200 | sp.CREATE_NO_WINDOW


def test_detached_launch_keeps_its_own_flags():
    """Запуск демона отсоединённым (host.py) нельзя ломать лишним флагом: Windows их не сочетает."""
    sp = _fake()
    _hide_consoles(sp)
    assert sp.Popen(["daemon"], creationflags=sp.DETACHED_PROCESS).flags == sp.DETACHED_PROCESS
