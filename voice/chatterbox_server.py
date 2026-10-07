"""Голос Chatterbox (Resemble AI, многоязычный, MIT) — отдельная служба со своим venv.

Свой venv потому, что chatterbox-tts тянет torch 2.6, а служба Qwen живёт на 2.14: в одном
окружении они друг другу ломают зависимости.

Протокол тот же, что у voice/server.py:
  {"cmd": "say", "text": "...", "voice": "jarvis"} → кадры PCM16 24 кГц (<I длина> + данные, 0 — конец)
  {"cmd": "warm"} / {"cmd": "sleep"} / {"cmd": "ping"} → строка JSON

Chatterbox не умеет отдавать речь по кускам: фраза готовится целиком (~1 с на секунду речи на
RTX 3060), поэтому кадр на фразу один. Демон режет ответ на предложения, так что первое слово
слышно примерно через секунду.
"""
from __future__ import annotations

import gc
import json
import os
import socket
import struct
import threading
import time
from pathlib import Path

import numpy as np
import torch

DATA = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "justday"
BUILTIN = Path(__file__).resolve().parent / "voices"
SOCKET = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "justday-chatterbox.sock"
RATE = 24000
IDLE_UNLOAD = 10 * 60   # 3,3 ГБ видеопамяти не держим, когда не разговаривают
IDLE_QUIT = 30 * 60     # процесс выходит совсем; гнездо systemd поднимет его на следующую фразу

lock = threading.Lock()
model = None
last_use = time.time()
_from_socket = (os.environ.get("LISTEN_PID") == str(os.getpid())
                and int(os.environ.get("LISTEN_FDS") or 0) >= 1)


def log(*a) -> None:
    print("[chatterbox]", *a, flush=True)


def load():
    global model
    if model is None:
        from chatterbox.mtl_tts import ChatterboxMultilingualTTS

        t = time.time()
        model = ChatterboxMultilingualTTS.from_pretrained(device="cuda" if torch.cuda.is_available() else "cpu")
        log(f"модель поднята за {time.time() - t:.1f} с")
    return model


def warm() -> None:
    with lock:
        load()


def unload() -> bool:
    global model
    if model is None:
        return False
    model = None
    gc.collect()
    torch.cuda.empty_cache()
    return True


def ref_audio(voice: str) -> str | None:
    """Голос — та же папка, что у Qwen: ref.wav. Нет такого — говорит своим голосом модели."""
    for root in (DATA / "voices", BUILTIN):
        p = root / (voice or "jarvis") / "ref.wav"
        if p.exists():
            return str(p)
    return None


def say(conn: socket.socket, text: str, voice: str) -> None:
    global last_use
    last_use = time.time()
    with lock:
        m = load()
        wav = m.generate(text, language_id="ru", audio_prompt_path=ref_audio(voice)).squeeze(0).cpu().numpy()
    if m.sr != RATE:
        wav = np.interp(np.linspace(0, len(wav), int(len(wav) * RATE / m.sr), endpoint=False),
                        np.arange(len(wav)), wav)
    data = (np.clip(wav, -1.0, 1.0) * 32767).astype("<i2").tobytes()
    last_use = time.time()
    conn.sendall(struct.pack("<I", len(data)) + data + struct.pack("<I", 0))


def handle(conn: socket.socket) -> None:
    with conn:
        try:
            req = json.loads(conn.makefile("rb").readline() or b"{}")
            cmd = req.get("cmd")
            if cmd == "say":
                try:
                    say(conn, req["text"], req.get("voice", ""))
                except Exception as e:  # закрытое соединение демон понимает как «голоса нет» и говорит Silero
                    log("say failed:", repr(e))
                    # Нехватка видеопамяти посреди загрузки оставляла полмодели в памяти навсегда —
                    # 2,7 ГБ, которые не нужны ни нам, ни игре.
                    if isinstance(e, torch.cuda.OutOfMemoryError):
                        with lock:
                            unload()
                return
            if cmd == "warm":
                threading.Thread(target=warm, daemon=True).start()
                resp = {"ok": True, "loaded": model is not None}
            elif cmd == "sleep":
                with lock:
                    resp = {"ok": True, "freed": unload()}
            elif cmd == "ping":
                resp = {"ok": True, "loaded": model is not None}
            else:
                resp = {"ok": False, "error": f"unknown command {cmd}"}
        except Exception as e:
            resp = {"ok": False, "error": str(e)}
        try:
            conn.sendall((json.dumps(resp, ensure_ascii=False) + "\n").encode())
        except OSError:
            pass


def watchdog() -> None:
    while True:
        time.sleep(20)
        idle = time.time() - last_use
        if _from_socket and idle > IDLE_QUIT and model is None:
            log("молчим — выходим, гнездо разбудит")
            os._exit(0)
        if idle > IDLE_UNLOAD and model is not None and lock.acquire(blocking=False):
            try:
                if unload():
                    log("молчим — видеопамять отпущена")
            finally:
                lock.release()


def main() -> None:
    if _from_socket:
        srv = socket.socket(family=socket.AF_UNIX, type=socket.SOCK_STREAM, fileno=3)
    else:
        SOCKET.unlink(missing_ok=True)
        srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        srv.bind(str(SOCKET))
        os.chmod(SOCKET, 0o600)
        srv.listen(8)
    threading.Thread(target=watchdog, daemon=True).start()
    log(f"слушаю {SOCKET}")
    while True:
        conn, _ = srv.accept()
        threading.Thread(target=handle, args=(conn,), daemon=True).start()


if __name__ == "__main__":
    main()
