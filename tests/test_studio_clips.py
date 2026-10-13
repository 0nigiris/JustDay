"""Нарезка клипов через autoclip: по умолчанию он ходит в платный Anthropic API, а студия обещает
бесплатно и без отправки наружу. Должен запускаться только с ollama, а готовые клипы — оказываться
в папке видео человека, а не в недрах ~/.local/state."""
import json
import os
import stat

import pytest

from justday import studio

FAKE = """#!/usr/bin/env python3
import json, os, sys, pathlib
home = pathlib.Path(os.environ["AUTOCLIP_HOME"])
(home / "args.json").write_text(json.dumps(sys.argv[1:]))
d = home / "exports" / "job1"
d.mkdir(parents=True)
(d / "01.mp4").write_bytes(b"x")
"""


@pytest.fixture
def fake(monkeypatch, tmp_path):
    exe = tmp_path / "autoclip"
    exe.write_text(FAKE)
    exe.chmod(exe.stat().st_mode | stat.S_IEXEC)
    monkeypatch.setattr(studio, "AUTOCLIP", exe)
    monkeypatch.setattr(studio.config, "STATE_DIR", tmp_path / "state")
    monkeypatch.setattr(studio, "out_dir", lambda kind: tmp_path / "Videos")
    (tmp_path / "Videos").mkdir()
    return tmp_path


def test_clips_never_go_to_a_paid_provider_and_land_in_videos(fake):
    r = studio.clips("~/стрим.mp4", count=3)
    home = fake / "state/autoclip"
    args = json.loads((home / "args.json").read_text())
    assert args[args.index("-p") + 1] == "ollama" and args[args.index("-n") + 1] == "3"
    assert args[-1] == os.path.expanduser("~/стрим.mp4")
    assert json.loads((home / "config.json").read_text())["active_provider"] == "ollama"
    assert r["folder"] == str(fake / "Videos/стрим клипы")
    assert [os.path.basename(f) for f in r["files"]] == ["01.mp4"]
    assert os.path.exists(r["files"][0])


def test_missing_autoclip_is_said_plainly(monkeypatch, tmp_path):
    monkeypatch.setattr(studio, "AUTOCLIP", tmp_path / "нет")
    with pytest.raises(RuntimeError, match="не установлен"):
        studio.clips("видео.mp4")
