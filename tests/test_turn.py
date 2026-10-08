"""Нет файла Smart Turn — запись должна кончаться по тишине, как раньше, а не падать."""
import numpy as np

from justday import config, turn


def test_без_модели_ответа_нет_и_ошибки_нет(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "MODELS_DIR", tmp_path)
    monkeypatch.setattr(turn, "_state", {})
    assert turn.complete(np.zeros(16000, dtype=np.int16)) is None
