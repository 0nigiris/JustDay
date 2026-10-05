"""Silero жил в демоне и держал там torch всю жизнь (Р-35); теперь его держит служба голоса.

Главное, что нельзя сломать: если службы нет — Джарвис говорит сам, а не молчит."""
from __future__ import annotations

import socket
import struct
import threading

import numpy as np

from justday import config
from justday import tts as tts_mod


def голос(tmp_path, monkeypatch) -> tts_mod.TTS:
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)
    (tmp_path / "v5_ru.pt").write_bytes(b"x")  # сама модель службе нужна по пути; здесь служба подставная
    cfg = {"engine": "silero", "speaker": "eugene", "sample_rate": 48000, "speed": 1.0, "lang": "ru",
           "silero_model_url": "https://example.test/v5_ru.pt"}
    t = tts_mod.TTS(cfg)
    monkeypatch.setattr(t, "SOCKET", tmp_path / "voice.sock")
    return t


def служба(path, samples: np.ndarray, asked: list) -> None:
    srv = socket.socket(socket.AF_UNIX)
    srv.bind(str(path))
    srv.listen(1)

    def serve() -> None:
        conn, _ = srv.accept()
        with conn:
            asked.append(conn.makefile("rb").readline())
            data = samples.astype("<i2").tobytes()
            conn.sendall(struct.pack("<I", len(data)) + data + struct.pack("<I", 0))
        srv.close()

    threading.Thread(target=serve, daemon=True).start()


def test_фраза_берётся_из_службы_голоса(tmp_path, monkeypatch) -> None:
    t = голос(tmp_path, monkeypatch)
    asked: list = []
    служба(tmp_path / "voice.sock", np.arange(1000, dtype=np.int16), asked)
    monkeypatch.setattr(t, "_silero", lambda: (_ for _ in ()).throw(AssertionError("torch поднят в демоне")))
    pcm = t.synth("Привет")
    assert len(pcm) == 1000 and b'"silero"' in asked[0]


def test_нет_службы_говорит_демон_сам(tmp_path, monkeypatch) -> None:
    t = голос(tmp_path, monkeypatch)

    class Модель:
        def apply_tts(self, **kw):
            import torch
            return torch.zeros(480)

    monkeypatch.setattr(t, "_silero", lambda: Модель())
    assert len(t.synth("Привет")) == 480


def test_при_запуске_демон_просит_службу_а_не_грузит_torch(tmp_path, monkeypatch) -> None:
    t = голос(tmp_path, monkeypatch)
    sent: list = []
    monkeypatch.setattr(t, "nudge", lambda cmd, **kw: sent.append((cmd, kw)) or True)
    monkeypatch.setattr(t, "_silero", lambda: (_ for _ in ()).throw(AssertionError("torch поднят в демоне")))
    t.load()
    assert sent and sent[0][0] == "warm" and sent[0][1]["engine"] == "silero"
