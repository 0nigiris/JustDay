import json, subprocess

def out(args):
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=4).stdout
    except (OSError, subprocess.SubprocessError):
        return ""

net = False
kind = ""
name = ""
for line in out(["nmcli", "-t", "-f", "TYPE,STATE,CONNECTION", "dev"]).splitlines():
    parts = line.split(":")
    if len(parts) < 2:
        continue
    if parts[0] in ("wifi", "ethernet") and parts[1] == "connected":
        net = True
        kind = "wifi" if parts[0] == "wifi" else "ethernet"
        name = parts[2] if len(parts) > 2 else ""
        if parts[0] == "wifi":
            break

vpn = ""
for line in out(["nmcli", "-t", "-f", "NAME,TYPE", "connection", "show", "--active"]).splitlines():
    parts = line.split(":")
    if len(parts) >= 2 and parts[1] in ("vpn", "wireguard", "tun"):
        vpn = parts[0]
        break

bt = out(["bluetoothctl", "show"]).lower()
print(json.dumps({"net": net, "kind": kind, "name": name, "vpn": vpn, "bt": "powered: yes" in bt}, ensure_ascii=False))
