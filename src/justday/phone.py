"""The phone, through KDE Connect — it is already paired with Plasma, so JustDay just uses it.

Sending only: a note, a link or a file goes to the phone in one command («скинь это себе на телефон»).
Nothing is polled and nothing is stored; if the phone is not on the network, the command says so."""
from __future__ import annotations

import json
import subprocess

TIMEOUT = 10


def _qdbus(*args: str) -> str:
    from .desktop import qdbus_bin
    bin = qdbus_bin()
    if not bin:
        return ""
    try:
        return subprocess.run([bin, "org.kde.kdeconnect", *args],
                              capture_output=True, text=True, timeout=TIMEOUT).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


def devices() -> list[dict]:
    """Paired phones and tablets, with the one that is online first."""
    out = []
    for path in _qdbus().splitlines():
        path = path.strip()
        if not path.startswith("/modules/kdeconnect/devices/") or path.count("/") != 4:
            continue

        def prop(name: str, path: str = path) -> str:
            return _qdbus(path, f"org.kde.kdeconnect.device.{name}")

        out.append({"id": path.rsplit("/", 1)[1], "name": prop("name"), "type": prop("type"),
                    "reachable": prop("isReachable") == "true", "paired": prop("isPaired") == "true"})
    return sorted(out, key=lambda d: (not d["reachable"], d["name"]))


def _target(which: str = "") -> dict:
    """The named device, or the first one that is online."""
    found = devices()
    if not found:
        raise RuntimeError("no device is paired with KDE Connect yet")
    if which:
        hit = next((d for d in found if which.lower() in (d["name"].lower(), d["id"])), None)
        if not hit:
            raise RuntimeError(f"no paired device called '{which}'")
    else:
        hit = found[0]
    if not hit["reachable"]:
        raise RuntimeError(f"{hit['name']} is not on the network right now")
    return hit


def notify(text: str, which: str = "") -> dict:
    """A note on the phone's lock screen (KDE Connect shows it as a notification)."""
    dev = _target(which)
    r = subprocess.run(["kdeconnect-cli", "-d", dev["id"], "--ping-msg", text],
                       capture_output=True, text=True, timeout=TIMEOUT)
    if r.returncode:
        raise RuntimeError(r.stderr.strip() or "KDE Connect refused the message")
    return {"ok": True, "to": dev["name"], "text": text}


def send(what: str, which: str = "") -> dict:
    """A file or a link: the phone offers to open it."""
    dev = _target(which)
    r = subprocess.run(["kdeconnect-cli", "-d", dev["id"], "--share", what],
                       capture_output=True, text=True, timeout=60)
    if r.returncode:
        raise RuntimeError(r.stderr.strip() or "KDE Connect refused the file")
    return {"ok": True, "to": dev["name"], "sent": what}


if __name__ == "__main__":  # a quick look without the CLI
    print(json.dumps(devices(), ensure_ascii=False, indent=1))


def ring(which: str = "") -> dict:
    """Позвонить на телефон: он зазвонит, даже если стоит на беззвучном.

    Это и есть «срочно». Уведомление человек увидит, когда возьмёт телефон в руки, — то есть
    когда-нибудь; звонок слышно из другой комнаты. Поэтому звонок стоит дороже уведомления, и
    тратить его можно только на то, ради чего не жалко оторвать человека от дела.
    """
    dev = _target(which)
    r = subprocess.run(["kdeconnect-cli", "-d", dev["id"], "--ring"],
                       capture_output=True, text=True, timeout=TIMEOUT)
    if r.returncode:
        raise RuntimeError(r.stderr.strip() or "KDE Connect refused to ring")
    return {"ok": True, "to": dev["name"], "rang": True}


def reach(text: str, urgent: bool = False, subject: str = "", which: str = "") -> dict:
    """Дотянуться до человека, когда его нет за компьютером.

    Обычное дело — письмо: оно подождёт, пока он сам до него дойдёт, и ничего не прервёт. Срочное —
    звонок: телефон звонит, и он узнаёт об этом сразу.

    Почему не всегда звонок. Ассистент, который звонит по каждому поводу, перестаёт звонить вовсе —
    его отключают. Разделение существует ровно для того, чтобы звонок остался слышным.

    Что бы ни вышло со звонком, письмо всё равно уходит: телефон может быть выключен, не в сети,
    или KDE Connect не запущен, и тогда единственный след разговора — письмо.
    """
    from . import config, mail

    out: dict = {"ok": False, "urgent": bool(urgent), "sent": []}
    text = str(text or "").strip()
    if not text:
        return {"ok": False, "error": "нечего передавать"}

    if urgent:
        try:
            ring(which)
            out["sent"].append("звонок")
        except (RuntimeError, OSError, subprocess.SubprocessError) as e:
            out["ring_error"] = str(e)
        try:
            notify(text[:200], which)
            out["sent"].append("уведомление")
        except (RuntimeError, OSError, subprocess.SubprocessError) as e:
            out["notify_error"] = str(e)

    to = (config.load().get("mail") or {}).get("address") or ""
    if to:
        try:
            mail.send(to, subject or ("Срочно" if urgent else "JustDay"), text)
            out["sent"].append("письмо")
        except Exception as e:          # почта ломается десятью разными способами, и каждый — повод сказать
            out["mail_error"] = str(e)[:200]
    else:
        out["mail_error"] = "почта не настроена"

    out["ok"] = bool(out["sent"])
    return out
