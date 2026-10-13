"""Модели студии переехали на внешний диск: без диска ComfyUI четыре минуты поднимался и падал на
«модель не найдена». Должно сразу говорить, что диск не подключён, и даже не пытаться запускаться."""
import pytest

from justday import studio


def test_unmounted_models_disk_is_said_at_once(monkeypatch, tmp_path):
    comfy = tmp_path / "ComfyUI"
    comfy.mkdir()
    (comfy / "models").symlink_to("/run/media/нет/TOSHIBA EXT/models")
    monkeypatch.setattr(studio, "settings", lambda: {"comfy": comfy, "python": tmp_path / "py",
                                                     "url": "http://127.0.0.1:1", "rmbg": tmp_path, "free_after": True})
    started = []
    monkeypatch.setattr(studio.subprocess, "run", lambda *a, **k: started.append(a))
    with pytest.raises(RuntimeError, match="не подключён"):
        studio.engine()
    assert not started
