"""Speech-to-text with faster-whisper (CTranslate2). GPU if available, CPU fallback."""
from __future__ import annotations

import ctypes
import glob
import logging
import os
import time

import re

import numpy as np

log = logging.getLogger("justday.stt")


def _preload_cuda_libs() -> None:
    """CTranslate2 needs cuBLAS/cuDNN 12; we ship them as pip wheels, so load them explicitly."""
    try:
        import nvidia.cublas
        import nvidia.cudnn
    except ImportError:
        return
    for mod in (nvidia.cublas, nvidia.cudnn):
        for so in sorted(glob.glob(os.path.join(list(mod.__path__)[0], "lib", "*.so*"))):
            try:
                ctypes.CDLL(so, mode=ctypes.RTLD_GLOBAL)
            except OSError:
                pass


HALLUCINATION = re.compile(
    r"субтитры\s+(сделал|создавал|подготовил|делал|созданы)|dimatorzok|диматорзок|редактор субтитров|корректор субтитров|"
    r"^\W*(продолжение следует|спасибо за просмотр|подписывайтесь на канал)\W*$|amara\.org", re.I)


class STT:
    def __init__(self, cfg: dict):
        self.cfg = cfg
        self._model = None

    def load(self):
        if self._model is not None:
            return self._model
        from faster_whisper import WhisperModel

        t = time.monotonic()
        if self.cfg["device"] == "cuda":
            _preload_cuda_libs()
            try:
                self._model = WhisperModel(self.cfg["model"], device="cuda", compute_type=self.cfg["compute_type"])
            except Exception as e:  # no GPU / driver problem → CPU
                log.warning("CUDA whisper failed (%s), falling back to CPU", e)
        if self._model is None:
            self._model = WhisperModel(self.cfg["model"], device="cpu", compute_type="int8")
        log.info("whisper %s loaded in %.1fs", self.cfg["model"], time.monotonic() - t)
        return self._model

    vocabulary = ""  # set by the daemon: base prompt + names the user actually says (contacts, apps, assistant)

    def transcribe(self, pcm16: np.ndarray) -> str:
        model = self.load()
        audio = pcm16.astype(np.float32) / 32768.0
        segments, _info = model.transcribe(
            audio,
            language=self.cfg["language"] or None,
            beam_size=1,
            vad_filter=True,
            initial_prompt=self.vocabulary or self.cfg.get("initial_prompt") or None,
            condition_on_previous_text=False,
        )
        text = " ".join(s.text.strip() for s in segments).strip()
        # Whisper hallucinates YouTube-subtitle credits and outros on near-silence
        if not text.strip(" .!?") or HALLUCINATION.search(text):
            return ""
        return text
