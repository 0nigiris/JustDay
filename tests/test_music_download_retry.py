"""Песня не попадала в медиатеку из-за разового 403 от YouTube.

13 октября фоновая загрузка дважды за минуту упала с «HTTP Error 403: Forbidden», хотя та же ссылка
через минуту качалась без ошибок. Теперь на 403 — одна повторная попытка без параллельных кусков; на
другие ошибки повторов нет, чтобы не долбить сайт попусту."""
import io
import json

import pytest

from justday import media


class FakeProc:
    def __init__(self, cmd, out: str, err: str, code: int) -> None:
        self.cmd, self.stdout, self.stderr, self.returncode = cmd, io.StringIO(out), io.StringIO(err), code

    def wait(self, timeout=None) -> int:
        return self.returncode

    def kill(self) -> None:
        pass


@pytest.fixture
def fake(tmp_path, monkeypatch):
    monkeypatch.setattr(media, "INDEX", tmp_path / "media.json")
    monkeypatch.setattr(media, "THUMBS", tmp_path / "thumbs")
    monkeypatch.setattr(media, "music_dir", lambda: tmp_path)
    monkeypatch.setattr(media, "DOWNLOAD_RETRY_PAUSE", 0)
    song = tmp_path / "song.m4a"
    song.write_bytes(b"x")
    ok = "JDINFO " + json.dumps({"id": "v1", "title": "Песня", "channel": "Автор", "filepath": str(song)}) + "\n"
    calls: list[list[str]] = []

    def run(answers):
        def popen(cmd, **kw):
            calls.append(list(cmd))
            err, code = answers[len(calls) - 1]
            return FakeProc(cmd, ok if code == 0 else "", err, code)
        monkeypatch.setattr(media.subprocess, "Popen", popen)
        return calls
    return run


ENTRY = {"id": "v1", "title": "Песня", "channel": "Автор", "url": "https://www.youtube.com/watch?v=v1"}
FORBIDDEN = "ERROR: unable to download video data: HTTP Error 403: Forbidden\n"


def test_one_forbidden_answer_does_not_lose_the_song(fake) -> None:
    calls = fake([(FORBIDDEN, 1), ("", 0)])
    track = media.download_audio(ENTRY)
    assert track["id"] == "v1" and len(calls) == 2
    assert calls[1][calls[1].index("-N") + 1] == "1"


def test_other_errors_are_not_retried(fake) -> None:
    calls = fake([("ERROR: Video unavailable\n", 1)])
    with pytest.raises(RuntimeError, match="unavailable"):
        media.download_audio(ENTRY)
    assert len(calls) == 1


def test_forbidden_twice_gives_up_after_the_second_try(fake) -> None:
    calls = fake([(FORBIDDEN, 1), (FORBIDDEN, 1)])
    with pytest.raises(RuntimeError, match="403"):
        media.download_audio(ENTRY)
    assert len(calls) == 2
