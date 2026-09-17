"""Fake JustDay daemon for UI work: serves the island's socket and forwards JSON lines typed into a FIFO.

    python3 tests/ui/fake_daemon.py /tmp/jd/fake.sock /tmp/jd/events.fifo [hello.json]
    echo '{"state":"listening","level":0.5}' > /tmp/jd/events.fifo
hello.json replaces the first message (settings, history…); a heartbeat keeps the island from reconnecting.
"""
import json
import os
import socket
import sys
import threading
import time

path, fifo = sys.argv[1], sys.argv[2]
if os.path.exists(path):
    os.unlink(path)
if not os.path.exists(fifo):
    os.mkfifo(fifo)
subs = []
hello = {"state": "idle", "workers": 0, "history": [],
         "settings": {"provider": "claude", "model": "sonnet", "assistant_name": "JustDay", "island": {"animations": "spring"}}}
if len(sys.argv) > 3:
    with open(sys.argv[3]) as f:
        hello = json.load(f)
srv = socket.socket(socket.AF_UNIX)
srv.bind(path)
srv.listen()


def accept():
    while True:
        c, _ = srv.accept()
        req = json.loads(c.makefile().readline() or "{}")
        if req.get("cmd") == "subscribe":
            c.sendall((json.dumps(hello, ensure_ascii=False) + "\n").encode())
            subs.append(c)
        else:
            print(json.dumps(req, ensure_ascii=False), flush=True)  # what the island sent
            c.sendall(b'{"ok": true}\n')
            c.close()


def heartbeat():
    while True:
        time.sleep(4)
        for c in list(subs):
            try:
                c.sendall(b"{}\n")
            except OSError:
                subs.remove(c)


threading.Thread(target=accept, daemon=True).start()
threading.Thread(target=heartbeat, daemon=True).start()
while True:
    with open(fifo) as f:
        for line in f:
            for c in list(subs):
                try:
                    c.sendall((line.rstrip("\n") + "\n").encode())
                except OSError:
                    subs.remove(c)
