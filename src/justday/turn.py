"""Smart Turn (pipecat, BSD-2): по звуку, а не по тишине, решает, договорил ли человек.

Беда, ради которой он здесь: одна фиксированная пауза либо тугая (команда ждёт полторы секунды
после последнего слова), либо рубит на полуслове («поставь таймер на… пять минут»). Модель слушает
хвост записи и отвечает, закончена ли мысль: закончена — отвечаем сразу, не закончена — ждём
обычную паузу. Файл лежит в ~/.local/share/justday/models; нет файла или onnxruntime — молча
остаётся старое поведение.
"""
from __future__ import annotations

import logging

import numpy as np

from . import config

log = logging.getLogger(__name__)
FILE = "smart-turn-v3.2-cpu.onnx"
SECONDS = 8
RATE = 16000
_state: dict = {}


def _load():
    if "session" not in _state:
        _state["session"] = None
        path = config.MODELS_DIR / FILE
        try:
            if path.exists():
                import onnxruntime as ort
                from faster_whisper.feature_extractor import FeatureExtractor

                so = ort.SessionOptions()
                so.inter_op_num_threads = so.intra_op_num_threads = 1
                _state["session"] = ort.InferenceSession(str(path), sess_options=so, providers=["CPUExecutionProvider"])
                _state["fe"] = FeatureExtractor(chunk_length=SECONDS)
        except Exception as e:
            log.warning("smart turn недоступен: %s", e)
    return _state["session"]


def complete(pcm: np.ndarray) -> float | None:
    """Вероятность, что фраза закончена (int16 или float32, 16 кГц); None — модели нет."""
    session = _load()
    if session is None:
        return None
    x = pcm.astype(np.float32) / 32768.0 if pcm.dtype == np.int16 else pcm.astype(np.float32)
    x = x[-SECONDS * RATE:]
    x = np.pad(x, (SECONDS * RATE - len(x), 0))  # короткое — нулями в начало, как учили
    x = (x - x.mean()) / np.sqrt(x.var() + 1e-7)
    feats = _state["fe"](x, chunk_length=SECONDS)[:, :SECONDS * 100][None].astype(np.float32)
    return float(np.ravel(session.run(None, {"input_features": feats})[0])[0])
