"""Окна на Windows: список, фокус, сворачивание и закрытие через user32, без powershell.

На Linux то же делает скрипт KWin (desktop.windows). Здесь отдаются те же поля и понимаются те же
действия, поэтому «закрой дискорд», «сверни браузер», док и сцены работают без своих веток.
Powershell не берём: каждый его запуск из отсоединённого демона мигал окном консоли и стоил
полсекунды, а окна спрашивают часто (док, «я ушёл»).
"""
import ctypes
from ctypes import wintypes

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
dwmapi = ctypes.windll.dwmapi

WM_CLOSE = 0x0010
SW_MINIMIZE, SW_RESTORE = 6, 9
GW_OWNER = 4
GWL_EXSTYLE = -20
WS_EX_TOOLWINDOW, WS_EX_APPWINDOW = 0x80, 0x40000
DWMWA_CLOAKED = 14
VK_MENU, KEYEVENTF_KEYUP = 0x12, 2


class _MONITORINFO(ctypes.Structure):
    _fields_ = [("cbSize", wintypes.DWORD), ("rcMonitor", wintypes.RECT), ("rcWork", wintypes.RECT),
                ("dwFlags", wintypes.DWORD)]


user32.GetWindowLongPtrW.restype = ctypes.c_ssize_t
user32.MonitorFromWindow.restype = wintypes.HANDLE
kernel32.OpenProcess.restype = wintypes.HANDLE


def _exe(pid: int) -> str:
    h = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION: хватает и для чужих
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(len(buf))
        if not kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return ""
        return buf.value.rsplit("\\", 1)[-1].removesuffix(".exe").removesuffix(".EXE")
    finally:
        kernel32.CloseHandle(h)


def _is_app_window(hwnd) -> bool:
    """То, что видно на панели задач: видимое, своё (не диалог чужого окна), не служебное, не спрятанное.

    Спрятанные (cloaked) — это открытые «на всякий случай» окна программ из Store и окна с других
    рабочих столов: видимыми они считаются, а на экране их нет."""
    if not user32.IsWindowVisible(hwnd) or not user32.GetWindowTextLengthW(hwnd):
        return False
    ex = user32.GetWindowLongPtrW(hwnd, GWL_EXSTYLE)
    if ex & WS_EX_TOOLWINDOW or (user32.GetWindow(hwnd, GW_OWNER) and not ex & WS_EX_APPWINDOW):
        return False
    cloaked = wintypes.DWORD()
    dwmapi.DwmGetWindowAttribute(hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked))
    return not cloaked.value


def _info(hwnd, active) -> dict:
    title = ctypes.create_unicode_buffer(user32.GetWindowTextLengthW(hwnd) + 1)
    user32.GetWindowTextW(hwnd, title, len(title))
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    mi = _MONITORINFO(cbSize=ctypes.sizeof(_MONITORINFO))
    user32.GetMonitorInfoW(user32.MonitorFromWindow(hwnd, 2), ctypes.byref(mi))
    m = mi.rcMonitor
    minimized = bool(user32.IsIconic(hwnd))
    full = not minimized and (r.left, r.top, r.right, r.bottom) == (m.left, m.top, m.right, m.bottom)
    # ponytail: программы из Store все называются ApplicationFrameHost; настоящее имя — через
    # дочернее окно CoreWindow, если «закрой калькулятор» понадобится.
    return {"id": str(int(hwnd)), "app": _exe(pid.value), "title": title.value, "pid": pid.value,
            "active": int(hwnd) == int(active or 0), "minimized": minimized, "full": full,
            "x": r.left, "y": r.top, "w": r.right - r.left, "h": r.bottom - r.top}


def _focus(hwnd) -> None:
    if user32.IsIconic(hwnd):
        user32.ShowWindow(hwnd, SW_RESTORE)
    # Windows отдаёт фокус только тому, кто сам последним получил ввод. Демон в фоне его не получал,
    # и без отпущенного Alt окно лишь мигало на панели задач вместо того, чтобы выйти вперёд.
    user32.keybd_event(VK_MENU, 0, 0, 0)
    user32.keybd_event(VK_MENU, 0, KEYEVENTF_KEYUP, 0)
    user32.SetForegroundWindow(hwnd)


def windows(action: str = "list", query: str = "", wid: str = "") -> list[dict]:
    """Те же действия, что у KWin-скрипта: list, active, focus, wake, minimize, close, close_app, close_active."""
    found = []
    cb = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)(
        lambda h, _: found.append(h) or True)
    user32.EnumWindows(cb, 0)  # сверху вниз по стопке: первым идёт то, что ближе к человеку
    active = user32.GetForegroundWindow()
    q = query.lower()
    out = []
    for hwnd in found:
        if not _is_app_window(hwnd):
            continue
        w = _info(hwnd, active)
        if wid and w["id"] != wid:
            continue
        if action in ("active", "close_active") and not w["active"]:
            continue
        hay = (w["app"] if action == "close_app" else f"{w['app']} {w['title']}").lower()
        if q and q not in hay and q != w["id"]:  # поиск переходит к окну по его номеру (launcher.run)
            continue
        if action == "wake" and not w["minimized"]:
            continue
        if action in ("close", "close_app", "close_active"):
            user32.PostMessageW(hwnd, WM_CLOSE, 0, 0)  # как крестик: программа может спросить «сохранить?»
        elif action in ("focus", "wake"):
            _focus(hwnd)
        elif action == "minimize":
            user32.ShowWindow(hwnd, SW_MINIMIZE)
        out.append(w)
        if action in ("focus", "wake"):
            break
    return out
