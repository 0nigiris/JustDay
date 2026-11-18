"""Звук и плеер на Windows теми же командами, что на Linux.

Голосовые команды и демон говорят `wpctl set-volume …` и `playerctl next`; на Windows этих программ
нет, и «громче» молча не работало. Вместо того чтобы учить каждый вызов двум системам, здесь
переводятся сами команды: громкость — через pycaw (Core Audio), плеер — мультимедийными клавишами,
которые слушает любой плеер Windows (Spotify, браузер, «Медиаплеер»)."""
from __future__ import annotations

# Виртуальные мультимедийные клавиши Windows.
# ponytail: play и pause обе жмут «играть/пауза» — без SMTC не узнать, играет ли сейчас; SMTC, если
# «пауза» начнёт включать музыку.
KEYS = {"play-pause": 0xB3, "play": 0xB3, "pause": 0xB3, "next": 0xB0, "previous": 0xB1, "stop": 0xB2}


def _endpoint():
    from pycaw.pycaw import AudioUtilities

    return AudioUtilities.GetSpeakers().EndpointVolume


def volume_value(cur: float, arg: str) -> float:
    """`50%`, `10%+`, `10%-` (как у wpctl) → новая громкость 0..1."""
    if arg.endswith(("%+", "%-")):
        step = float(arg[:-2]) / 100
        new = cur + step if arg[-1] == "+" else cur - step
    else:
        new = float(arg.rstrip("%")) / 100
    return max(0.0, min(1.0, new))


def run(cmd: tuple[str, ...] | list[str]) -> bool:
    """Выполнить `wpctl`/`playerctl` по-виндовски. False — не вышло или такой команды нет."""
    try:
        if cmd[0] == "playerctl" and cmd[-1] in KEYS:
            import ctypes

            vk = KEYS[cmd[-1]]
            ctypes.windll.user32.keybd_event(vk, 0, 0, 0)
            ctypes.windll.user32.keybd_event(vk, 0, 2, 0)  # 2 = KEYEVENTF_KEYUP
            return True
        if cmd[0] == "wpctl":
            args = list(cmd[1:])
            if "-l" in args:  # предел громкости и его значение: на Windows выше 100% и так нельзя
                del args[args.index("-l"):args.index("-l") + 2]
            args = [a for a in args if not a.startswith("@")]
            ep = _endpoint()
            if args[0] == "set-volume":
                ep.SetMasterVolumeLevelScalar(volume_value(ep.GetMasterVolumeLevelScalar(), args[-1]), None)
                return True
            if args[0] == "set-mute":
                on = not ep.GetMute() if args[-1] == "toggle" else args[-1] == "1"
                ep.SetMute(int(on), None)
                return True
    except Exception:
        return False
    return False


if __name__ == "__main__":
    assert volume_value(0.5, "10%+") == 0.6
    assert volume_value(0.95, "10%+") == 1.0
    assert volume_value(0.05, "10%-") == 0.0
    assert volume_value(0.3, "40%") == 0.4
    print("ok")
