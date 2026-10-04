#!/usr/bin/python3
"""Снимок экрана через портал рабочего стола. Запускается СИСТЕМНЫМ python3.

Почему отдельный файл, а не функция в demon'е: на KWin единственный путь к
снимку — `org.freedesktop.portal.Screenshot`, а для разговора с ним нужен
GLib (`gi`), которого в нашем venv нет и не будет: venv собран uv'ом под свою
сборку питона, а `gi` ставится системным пакетом под системный. Поэтому демон
зовёт этот файл как `python3 portal_shot.py <куда.png>`.

Почему именно портал: grim требует wlr-screencopy, которого KWin не говорит;
`org.kde.KWin.ScreenShot2` отвечает NoAuthorized (интерфейс разрешён только
программам, у которых в .desktop прописан X-KDE-DBUS-Restricted-Interfaces —
порталу он там прописан, нам нет); spectacle пишет файл и падает в KCrash.
Портал KDE снимает молча, без диалога и без подтверждений.
"""
import os
import shutil
import sys
import urllib.parse

import gi

gi.require_version("Gio", "2.0")
from gi.repository import Gio, GLib  # noqa: E402


def capture(dest: str, timeout_s: int = 15) -> str:
    bus = Gio.bus_get_sync(Gio.BusType.SESSION, None)
    loop = GLib.MainLoop()
    box: dict[str, object] = {}

    def on_response(_c, _s, _p, _i, _sig, params):
        box["r"] = params.unpack()
        loop.quit()

    # Подписаться НАДО до вызова: ответ приходит сигналом и может опередить нас.
    bus.signal_subscribe("org.freedesktop.portal.Desktop", "org.freedesktop.portal.Request",
                         "Response", None, None, Gio.DBusSignalFlags.NONE, on_response)
    bus.call_sync("org.freedesktop.portal.Desktop", "/org/freedesktop/portal/desktop",
                  "org.freedesktop.portal.Screenshot", "Screenshot",
                  GLib.Variant("(sa{sv})", ("", {"interactive": GLib.Variant("b", False),
                                                 "modal": GLib.Variant("b", False)})),
                  GLib.VariantType("(o)"), Gio.DBusCallFlags.NONE, timeout_s * 1000, None)
    GLib.timeout_add_seconds(timeout_s, lambda: (loop.quit(), False)[1])
    loop.run()

    got = box.get("r")
    if not got:
        raise RuntimeError("портал не ответил")
    code, results = got[0], got[1]
    if code != 0:
        raise RuntimeError(f"портал отказал (код {code})")
    uri = str(results.get("uri") or "")
    if not uri.startswith("file://"):
        raise RuntimeError(f"портал вернул не файл: {uri[:80]}")
    src = urllib.parse.unquote(uri[len("file://"):])
    # Портал кладёт снимок в ~/Pictures. Уносим к себе, иначе каждое наведение
    # на значок в доке оставляло бы человеку файл в папке с картинками.
    os.makedirs(os.path.dirname(os.path.abspath(dest)) or ".", exist_ok=True)
    shutil.move(src, dest)
    return dest


if __name__ == "__main__":
    if len(sys.argv) < 2:
        sys.exit("укажите путь к png")
    try:
        print(capture(sys.argv[1]))
    except Exception as e:  # наружу важен текст ошибки, а не её тип
        sys.exit(str(e))
