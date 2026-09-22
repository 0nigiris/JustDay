"""JustDay neural voice service (Qwen3-TTS via faster-qwen3-tts, CUDA graphs, streaming).

Runs in its own virtualenv (CUDA PyTorch) and serves the daemon over a user-only Unix socket:
  request  : one JSON line
     {"cmd": "say", "text": "...", "voice": "butler"}           → binary stream of PCM frames
     {"cmd": "voices"}                                           → JSON line
     {"cmd": "design", "name": "...", "description": "...", "sample": "..."}  → JSON line (creates a voice)
     {"cmd": "clone", "name": "...", "audio": "/path.wav", "text": "transcript"} → JSON line
  PCM frame: 4-byte little-endian length + int16 mono samples at 24 kHz; a zero length ends the stream.

A voice is a folder <voices>/<id>/ with ref.wav (10–20 s of speech), ref.txt (its transcript) and voice.json.
"""
from __future__ import annotations

import gc
import json
import os
import re
import shutil
import socket
import struct
import sys
import threading
import time
from pathlib import Path

import numpy as np
import soundfile as sf
import torch

DATA = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")) / "justday"
VOICES = DATA / "voices"
BUILTIN = Path(__file__).resolve().parent / "voices"
SOCKET = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}")) / "justday-voice.sock"
def _quality() -> str:
    try:
        import tomllib

        cfg = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "justday" / "config.toml"
        return tomllib.loads(cfg.read_text(encoding="utf-8")).get("tts", {}).get("neural_quality", "fast")
    except (OSError, ValueError):
        return "fast"


# fast: 0.6B (~2.5 GB VRAM) · best: 1.7B (~4.5 GB VRAM, cleaner timbre); both stream faster than real time on an RTX 3060
BASE_MODEL = os.environ.get("JUSTDAY_VOICE_MODEL") or ("Qwen/Qwen3-TTS-12Hz-1.7B-Base" if _quality() == "best"
                                                        else "Qwen/Qwen3-TTS-12Hz-0.6B-Base")
DESIGN_MODEL = "Qwen/Qwen3-TTS-12Hz-1.7B-VoiceDesign"
RATE = 24000

lock = threading.Lock()
model = None


def log(*a) -> None:
    print(time.strftime("%H:%M:%S"), *a, file=sys.stderr, flush=True)


def voice_dirs() -> dict[str, Path]:
    out = {}
    for root in (BUILTIN, VOICES):  # user voices override built-in ones with the same id
        if root.is_dir():
            for d in sorted(root.iterdir()):
                if (d / "ref.wav").exists() and (d / "ref.txt").exists():
                    out[d.name] = d
    return out


def voice_list() -> list[dict]:
    items = []
    for vid, d in voice_dirs().items():
        meta = json.loads((d / "voice.json").read_text(encoding="utf-8")) if (d / "voice.json").exists() else {}
        items.append({"id": vid, "name": meta.get("name", vid), "description": meta.get("description", ""),
                      "kind": meta.get("kind", ""), "builtin": d.parent == BUILTIN})
    return items


def load_base():
    global model
    if model is None:
        from faster_qwen3_tts import FasterQwen3TTS

        t = time.time()
        model = FasterQwen3TTS.from_pretrained(BASE_MODEL)
        model.warmup(prefill_len=120)
        log(f"model {BASE_MODEL} ready in {time.time() - t:.1f}s")
    return model


def to_pcm16(chunk: np.ndarray) -> bytes:
    return (np.clip(chunk, -1.0, 1.0) * 32767).astype("<i2").tobytes()


def say(conn: socket.socket, text: str, voice: str) -> None:
    voices = voice_dirs()
    d = voices.get(voice) or next(iter(voices.values()))
    ref_text = (d / "ref.txt").read_text(encoding="utf-8").strip()
    with lock:
        m = load_base()
        for chunk, sr, _timing in m.generate_voice_clone_streaming(
                text=text, language="Russian" if re.search(r"[а-яё]", text, re.I) else "Auto",
                ref_audio=str(d / "ref.wav"), ref_text=ref_text, chunk_size=12):  # ~1 s chunks: fewer seams
            if sr != RATE:
                chunk = np.interp(np.linspace(0, len(chunk), int(len(chunk) * RATE / sr), endpoint=False),
                                  np.arange(len(chunk)), chunk)
            data = to_pcm16(chunk)
            conn.sendall(struct.pack("<I", len(data)) + data)
    conn.sendall(struct.pack("<I", 0))


def save_voice(name: str, wav: np.ndarray, sr: int, text: str, meta: dict) -> dict:
    vid = re.sub(r"[^a-z0-9а-яё_-]+", "-", name.lower()).strip("-") or f"voice-{int(time.time())}"
    d = VOICES / vid
    d.mkdir(parents=True, exist_ok=True)
    sf.write(d / "ref.wav", wav, sr)
    (d / "ref.txt").write_text(text, encoding="utf-8")
    (d / "voice.json").write_text(json.dumps({"name": name, **meta}, ensure_ascii=False, indent=1), encoding="utf-8")
    return {"ok": True, "id": vid}


def design(name: str, description: str, sample: str) -> dict:
    """Create a voice from a text description (loads the 1.7B VoiceDesign model temporarily)."""
    from qwen_tts import Qwen3TTSModel

    with lock:
        t = time.time()
        dm = Qwen3TTSModel.from_pretrained(DESIGN_MODEL, device_map="cuda:0", dtype=torch.bfloat16, attn_implementation="sdpa")
        wavs, sr = dm.generate_voice_design(text=sample, language="Russian", instruct=description)
        del dm
        gc.collect()
        torch.cuda.empty_cache()
        log(f"designed voice {name!r} in {time.time() - t:.1f}s")
    return save_voice(name, wavs[0], sr, sample, {"description": description, "kind": "описание"})


def clone(name: str, audio: str, text: str) -> dict:
    wav, sr = sf.read(audio, dtype="float32")
    if wav.ndim > 1:
        wav = wav.mean(axis=1)
    seconds = len(wav) / sr
    if not 3 <= seconds <= 30:
        return {"ok": False, "error": f"нужна запись от 3 до 30 секунд (сейчас {seconds:.1f} с)"}
    return save_voice(name, wav, sr, text, {"description": "клон из записи", "kind": "запись"})


def handle(conn: socket.socket) -> None:
    with conn:
        f = conn.makefile("rb")
        try:
            req = json.loads(f.readline() or b"{}")
            cmd = req.get("cmd")
            if cmd == "say":
                say(conn, req["text"], req.get("voice", ""))
                return
            if cmd == "voices":
                resp = {"ok": True, "voices": voice_list()}
            elif cmd == "design":
                resp = design(req["name"], req["description"], req.get("sample") or
                              "Добрый вечер. Я ваш ассистент. Все системы работают штатно, чем могу помочь?")
            elif cmd == "clone":
                resp = clone(req["name"], req["audio"], req["text"])
            elif cmd == "delete":
                d = VOICES / req["id"]
                ok = d.is_dir() and d.parent == VOICES
                if ok:
                    shutil.rmtree(d)
                resp = {"ok": ok}
            elif cmd == "ping":
                resp = {"ok": True, "loaded": model is not None}
            else:
                resp = {"ok": False, "error": f"unknown command {cmd}"}
        except Exception as e:
            log("request failed:", repr(e))
            resp = {"ok": False, "error": str(e)}
        try:
            conn.sendall((json.dumps(resp, ensure_ascii=False) + "\n").encode())
        except OSError:
            pass


def main() -> None:
    VOICES.mkdir(parents=True, exist_ok=True)
    if SOCKET.exists():
        SOCKET.unlink()
    srv = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    srv.bind(str(SOCKET))
    os.chmod(SOCKET, 0o600)
    srv.listen(8)
    threading.Thread(target=load_base, daemon=True).start()  # warm up in the background
    log(f"listening on {SOCKET}")
    while True:
        conn, _ = srv.accept()
        threading.Thread(target=handle, args=(conn,), daemon=True).start()


if __name__ == "__main__":
    main()
