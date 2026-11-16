#!/usr/bin/env python3
"""Сети Wi‑Fi и устройства Bluetooth для подробного вида плиток пульта (долгое нажатие).

  radios.py wifi              — список сетей JSON
  radios.py bt                — список известных устройств JSON
  radios.py wifi-up SSID      — подключиться: к сохранённой или открытой сети
  radios.py bt-up MAC / bt-down MAC

Пароль от новой сети сюда не попадает и не должен: для закрытой несохранённой сети ответ
`need_password`, и островок открывает настройки KDE, где пароль вводит сам человек.
"""
import json
import subprocess
import sys


def run(args, timeout=12):
    try:
        r = subprocess.run(args, capture_output=True, text=True, timeout=timeout)
        return r.returncode, r.stdout
    except (OSError, subprocess.SubprocessError):
        return 1, ""


def split(line):
    # nmcli -t экранирует двоеточие в имени как «\:»
    out, cur, esc = [], "", False
    for ch in line:
        if esc:
            cur += ch
            esc = False
        elif ch == "\\":
            esc = True
        elif ch == ":":
            out.append(cur)
            cur = ""
        else:
            cur += ch
    return [*out, cur]


def saved_wifi():
    _, txt = run(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show"])
    return {p[0] for p in map(split, txt.splitlines()) if len(p) > 1 and p[1] == "802-11-wireless"}


def wifi():
    saved = saved_wifi()
    _, txt = run(["nmcli", "-t", "-f", "IN-USE,SSID,SIGNAL,SECURITY", "dev", "wifi", "list"])
    seen = {}
    for p in map(split, txt.splitlines()):
        if len(p) < 4 or not p[1]:
            continue
        n = {"id": p[1], "name": p[1], "on": p[0] == "*", "signal": int(p[2] or 0),
             "lock": p[3] not in ("", "--"), "saved": p[1] in saved}
        old = seen.get(n["name"])
        if not old or n["on"] or (n["signal"] > old["signal"] and not old["on"]):
            seen[n["name"]] = n
    return sorted(seen.values(), key=lambda n: (not n["on"], not n["saved"], -n["signal"]))


def bt():
    _, txt = run(["bluetoothctl", "devices"])
    out = []
    for line in txt.splitlines():
        parts = line.split(" ", 2)
        if len(parts) < 3 or parts[0] != "Device":
            continue
        _, info = run(["bluetoothctl", "info", parts[1]], timeout=4)
        out.append({"id": parts[1], "name": parts[2], "on": "Connected: yes" in info,
                    "paired": "Paired: yes" in info})
    return sorted(out, key=lambda n: (not n["on"], n["name"].lower()))


def main(argv):
    cmd = argv[1] if len(argv) > 1 else ""
    arg = argv[2] if len(argv) > 2 else ""
    if cmd == "wifi":
        res = {"items": wifi()}
    elif cmd == "bt":
        res = {"items": bt()}
    elif cmd == "wifi-up":
        net = next((n for n in wifi() if n["name"] == arg), None)
        if net and net["lock"] and not net["saved"]:
            res = {"ok": False, "need_password": True}
        else:
            code, _ = run(["nmcli", "connection", "up", "id", arg] if net and net["saved"] else ["nmcli", "dev", "wifi", "connect", arg], 30)
            res = {"ok": code == 0}
    elif cmd in ("bt-up", "bt-down"):
        code, _ = run(["bluetoothctl", "connect" if cmd == "bt-up" else "disconnect", arg], 20)
        res = {"ok": code == 0}
    else:
        res = {"ok": False, "error": "команда?"}
    print(json.dumps(res, ensure_ascii=False))


if __name__ == "__main__":
    main(sys.argv)
