"""A virtual relative mouse via Linux uinput (no dependencies).

KWin's EIS only offers an *absolute* pointer, but games that lock the pointer (camera control in Roblox/Sober,
shooters) read *relative* motion. A uinput device looks like a real mouse to the compositor and to games.
Needs write access to /dev/uinput (Fedora grants it to the active seat user).
"""
from __future__ import annotations

import fcntl
import os
import struct
import time

EV_SYN, EV_KEY, EV_REL = 0, 1, 2
REL_X, REL_Y, REL_WHEEL = 0, 1, 8
BTN = {"left": 0x110, "right": 0x111, "middle": 0x112}
UI_SET_EVBIT, UI_SET_KEYBIT, UI_SET_RELBIT = 0x40045564, 0x40045565, 0x40045566
UI_DEV_SETUP, UI_DEV_CREATE, UI_DEV_DESTROY = 0x405C5503, 0x5501, 0x5502

_fd: int | None = None


def _device() -> int:
    global _fd
    if _fd is None:
        fd = os.open("/dev/uinput", os.O_WRONLY | os.O_NONBLOCK)
        fcntl.ioctl(fd, UI_SET_EVBIT, EV_KEY)
        fcntl.ioctl(fd, UI_SET_EVBIT, EV_REL)
        for code in BTN.values():
            fcntl.ioctl(fd, UI_SET_KEYBIT, code)
        for code in (REL_X, REL_Y, REL_WHEEL):
            fcntl.ioctl(fd, UI_SET_RELBIT, code)
        name = b"JustDay virtual mouse"
        setup = struct.pack("HHHH80sI", 0x06, 0x1D6B, 0x0104, 1, name, 0)  # BUS_VIRTUAL, Linux Foundation ids
        fcntl.ioctl(fd, UI_DEV_SETUP, setup)
        fcntl.ioctl(fd, UI_DEV_CREATE)
        time.sleep(0.4)  # let libinput/KWin pick the new device up
        _fd = fd
    return _fd


def _emit(events: list[tuple[int, int, int]]) -> None:
    fd = _device()
    now = time.time()
    sec, usec = int(now), int((now % 1) * 1e6)
    data = b"".join(struct.pack("qqHHi", sec, usec, t, c, v) for t, c, v in events)
    os.write(fd, data + struct.pack("qqHHi", sec, usec, EV_SYN, 0, 0))


def move(dx: float, dy: float, duration: float = 0.0) -> None:
    """Relative motion; with a duration it is spread over ~120 Hz steps (smooth camera turns)."""
    steps = max(1, int(duration * 120))
    fx, fy = dx / steps, dy / steps
    ax = ay = 0.0
    for _ in range(steps):
        ax += fx
        ay += fy
        ix, iy = int(round(ax)), int(round(ay))
        ax -= ix
        ay -= iy
        if ix or iy:
            _emit([(EV_REL, REL_X, ix), (EV_REL, REL_Y, iy)])
        if steps > 1:
            time.sleep(duration / steps)


def button(name: str, down: bool) -> None:
    _emit([(EV_KEY, BTN[name], 1 if down else 0)])


def close() -> None:
    global _fd
    if _fd is not None:
        fcntl.ioctl(_fd, UI_DEV_DESTROY)
        os.close(_fd)
        _fd = None
