"""Personal voice profile (like "Hey Siri" training), all on this computer:

  * voiceprint — a speaker embedding (3D-Speaker CAM++, ONNX) averaged over enrollment phrases; utterances whose
    embedding is too far from it can be ignored ("answer only my voice");
  * wake word — an openWakeWord custom verifier trained on the user's own "Hey Jarvis" recordings;
  * pace — the pause that ends a phrase, estimated from how the user pauses inside sentences.
"""
from __future__ import annotations

import json
import time
import urllib.request
import wave
from pathlib import Path

import numpy as np

from . import config

DIR = config.DATA_DIR / "voiceprint"
PROFILE = DIR / "profile.json"
MODEL = config.DATA_DIR / "models" / "campplus_sv.onnx"
MODEL_URL = ("https://github.com/k2-fsa/sherpa-onnx/releases/download/speaker-recongition-models/"
             "3dspeaker_speech_campplus_sv_zh_en_16k-common_advanced.onnx")
RATE = 16000

WAKE_PHRASES = ["Hey Jarvis"] * 5
PHRASES = [
    "Джарвис, открой калькулятор",
    "Посчитай, сколько будет двадцать пять умножить на четыре",
    "Какая погода будет завтра утром?",
    "Напиши маме, что я приеду вечером",
    "Включи на Ютубе что-нибудь спокойное",
    "Запомни, что мой любимый браузер — Хелиум",
]

_session = None


# ---------------- features & embedding ----------------
def _mel_filters(n_fft: int = 512, n_mels: int = 80, low: float = 20.0, high: float = RATE / 2) -> np.ndarray:
    mel = lambda f: 1127.0 * np.log(1.0 + f / 700.0)  # noqa: E731 — Kaldi's mel scale
    edges = np.linspace(mel(low), mel(high), n_mels + 2)
    bins = mel(np.linspace(0, RATE / 2, n_fft // 2 + 1))
    fb = np.zeros((n_mels, n_fft // 2 + 1), dtype=np.float32)
    for m in range(n_mels):
        left, center, right = edges[m], edges[m + 1], edges[m + 2]
        up = (bins - left) / (center - left)
        down = (right - bins) / (right - center)
        fb[m] = np.maximum(0.0, np.minimum(up, down))
    return fb


_FB = _mel_filters()


def fbank(pcm: np.ndarray) -> np.ndarray:
    """80-dim log-mel filterbank, Kaldi-style (25 ms Povey window, 10 ms shift, pre-emphasis 0.97)."""
    x = pcm.astype(np.float32)
    if x.dtype != np.float32 or np.abs(x).max() > 1.5:
        x = x / 32768.0
    flen, shift = 400, 160
    if len(x) < flen:
        x = np.pad(x, (0, flen - len(x)))
    n = 1 + (len(x) - flen) // shift
    frames = np.stack([x[i * shift:i * shift + flen] for i in range(n)])
    frames = frames - frames.mean(axis=1, keepdims=True)
    frames = np.concatenate([frames[:, :1], frames[:, 1:] - 0.97 * frames[:, :-1]], axis=1)
    window = (0.5 - 0.5 * np.cos(2 * np.pi * np.arange(flen) / (flen - 1))) ** 0.85
    spec = np.abs(np.fft.rfft(frames * window, n=512)) ** 2
    feats = np.log(np.maximum(spec @ _FB.T, np.finfo(np.float32).eps))
    return feats - feats.mean(axis=0, keepdims=True)  # global mean normalisation (model metadata)


def _model():
    global _session
    if _session is None:
        import onnxruntime as ort

        if not MODEL.exists():
            MODEL.parent.mkdir(parents=True, exist_ok=True)
            urllib.request.urlretrieve(MODEL_URL, MODEL)
        _session = ort.InferenceSession(str(MODEL), providers=["CPUExecutionProvider"])
    return _session


def embed(pcm: np.ndarray) -> np.ndarray:
    feats = fbank(trim_silence(pcm))[None].astype(np.float32)
    e = _model().run(None, {"x": feats})[0][0]
    return e / (np.linalg.norm(e) + 1e-9)


# ---------------- audio helpers ----------------
def rms_frames(pcm: np.ndarray, frame: int = 480) -> np.ndarray:
    x = pcm.astype(np.float32) / 32768.0
    n = len(x) // frame
    return np.sqrt((x[:n * frame].reshape(n, frame) ** 2).mean(axis=1)) if n else np.zeros(0)


def trim_silence(pcm: np.ndarray) -> np.ndarray:
    r = rms_frames(pcm)
    if not len(r):
        return pcm
    thr = max(0.01, np.percentile(r, 20) * 3)
    idx = np.where(r > thr)[0]
    return pcm[idx[0] * 480:(idx[-1] + 1) * 480] if len(idx) else pcm


def save_wav(path: Path, pcm: np.ndarray) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(RATE)
        w.writeframes(pcm.astype(np.int16).tobytes())


def load_wav(path: Path) -> np.ndarray:
    with wave.open(str(path), "rb") as w:
        return np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16)


def inner_pauses(pcm: np.ndarray) -> list[float]:
    """Pauses between words inside one phrase (seconds)."""
    r = rms_frames(pcm)  # 30 ms frames
    if not len(r):
        return []
    speech = r > max(0.012, np.percentile(r, 30) * 2.5)
    idx = np.where(speech)[0]
    if len(idx) < 2:
        return []
    gaps, run = [], 0
    for v in speech[idx[0]:idx[-1] + 1]:
        if not v:
            run += 1
        elif run:
            gaps.append(run * 0.03)
            run = 0
    return [g for g in gaps if g >= 0.09]


# ---------------- enrollment ----------------
def enroll_finish() -> dict:
    """Build the profile from DIR/phrase_*.wav and DIR/wake_*.wav."""
    phrases = sorted(DIR.glob("phrase_*.wav"))
    wakes = sorted(DIR.glob("wake_*.wav"))
    if len(phrases) < 3:
        return {"ok": False, "error": "нужно записать хотя бы 3 фразы"}
    clips = [load_wav(p) for p in phrases + wakes]
    embs = np.stack([embed(c) for c in clips])
    center = embs.mean(axis=0)
    center /= np.linalg.norm(center)
    sims = embs @ center
    # accept a bit below the worst enrollment clip, but never so low that other voices pass
    threshold = float(np.clip(sims.min() - 0.12, 0.35, 0.65))

    pauses = [g for c in (load_wav(p) for p in phrases) for g in inner_pauses(c)]
    silence = float(np.clip((np.percentile(pauses, 90) if pauses else 0.5) + 0.45, 0.6, 1.6))

    verifier = ""
    if len(wakes) >= 3:
        verifier = train_wake_verifier(wakes, phrases)

    profile = {"embedding": center.round(6).tolist(), "threshold": round(threshold, 3), "enroll_scores": sims.round(3).tolist(),
               "silence_seconds": round(silence, 2), "wake_verifier": verifier, "created": time.strftime("%Y-%m-%d %H:%M")}
    PROFILE.write_text(json.dumps(profile), encoding="utf-8")
    return {"ok": True, "threshold": profile["threshold"], "silence_seconds": profile["silence_seconds"],
            "wake_verifier": bool(verifier), "clips": len(clips)}


def train_wake_verifier(positives: list[Path], negatives: list[Path]) -> str:
    """openWakeWord custom verifier: a tiny classifier on top of hey_jarvis that learns *your* voice saying it."""
    import os

    import openwakeword
    from openwakeword.custom_verifier_model import train_custom_verifier

    model = os.path.join(os.path.dirname(openwakeword.__file__), "resources", "models", "hey_jarvis_v0.1.onnx")
    if not os.path.exists(model):
        from openwakeword.utils import download_models

        download_models(model_names=["hey_jarvis"])
    out = DIR / "hey_jarvis_verifier.pkl"
    try:  # the function takes *lists of wav paths* (its docstring says directories, the code iterates items)
        train_custom_verifier(positive_reference_clips=[str(p) for p in positives],
                              negative_reference_clips=[str(p) for p in negatives],
                              output_path=str(out), model_name=model, inference_framework="onnx")
    except Exception:  # noqa: BLE001 — too few detections in the clips etc.: keep the plain model
        return ""
    return str(out) if out.exists() else ""


# ---------------- runtime ----------------
def profile() -> dict | None:
    try:
        return json.loads(PROFILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def score(pcm: np.ndarray) -> float | None:
    p = profile()
    if not p:
        return None
    return float(embed(pcm) @ np.asarray(p["embedding"], dtype=np.float32))


def reset() -> None:
    import shutil

    shutil.rmtree(DIR, ignore_errors=True)
