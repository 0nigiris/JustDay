"""Видео → текст (п.24): ролик, который требует входа, давал трассировку yt-dlp вместо понятной фразы,
а страница с текстом должна ложиться на диск даже без местной модели."""
import subprocess
from pathlib import Path

import pytest

from justday import transcript


def test_login_wall_is_said_in_words(monkeypatch, tmp_path):
    monkeypatch.setattr(transcript.shutil, "which", lambda _: "/usr/bin/yt-dlp")
    err = "ERROR: [Instagram] abc: Requested content is not available, rate-limit reached or login required."
    monkeypatch.setattr(transcript.subprocess, "run",
                        lambda *a, **k: subprocess.CompletedProcess(a, 1, "", err))
    with pytest.raises(transcript.NeedsLogin):
        transcript.fetch_audio("https://www.instagram.com/reel/abc/", tmp_path)


def test_page_lands_without_local_model(monkeypatch, tmp_path):
    clip = tmp_path / "Как убрать нейрослоп?.mp4"
    clip.write_bytes(b"")
    monkeypatch.setattr(transcript, "transcribe", lambda audio: "Первая мысль.\nВторая мысль.")
    import justday.localllm as localllm
    monkeypatch.setattr(localllm, "available", lambda: False)
    path = transcript.run(str(clip), out=tmp_path / "видео")
    assert path.name.endswith("-как-убрать-нейрослоп.md")
    body = Path(path).read_text(encoding="utf-8")
    assert "Вторая мысль." in body and "## Выжимка" in body


def test_queue_keeps_network_failures_and_links_sent_meanwhile(monkeypatch, tmp_path):
    """Цикл разбирает присланные ролики без него: сбой сети не должен терять ссылку, «нужен вход» не
    должен крутиться каждые три часа, а ссылка, присланная во время разбора, не должна пропасть."""
    monkeypatch.setattr(transcript, "QUEUE", tmp_path / "очередь.txt")
    for link in ("ok", "login", "net", "ok"):
        transcript.enqueue(link)
    assert transcript.queued() == ["ok", "login", "net"]

    def fake_run(source, out):
        if source == "ok":
            transcript.enqueue("новая")  # пришла с телефона, пока качался ролик
            return out / "готово.md"
        if source == "login":
            raise transcript.NeedsLogin("вход")
        raise RuntimeError("нет сети")

    monkeypatch.setattr(transcript, "run", fake_run)
    report = transcript.drain(out=tmp_path)
    assert len(report) == 3
    assert transcript.queued() == ["net", "новая"]


def test_video_dropped_in_the_inbox_folder_is_transcribed_once(tmp_path, monkeypatch) -> None:
    """Ролик, скачанный руками, бросают в папку: разобрать и убрать в «Готово», а не слушать каждые три часа."""
    from justday import transcript
    inbox = tmp_path / "in"
    inbox.mkdir()
    (inbox / "a.mp4").write_bytes(b"x")
    (inbox / "note.txt").write_text("не видео")
    monkeypatch.setattr(transcript, "INBOX", inbox)
    monkeypatch.setattr(transcript, "QUEUE", tmp_path / "q.txt")
    monkeypatch.setattr(transcript, "run", lambda source, out=None, **kw: tmp_path / "out.md")
    got = transcript.drain(out=tmp_path)
    assert len(got) == 1 and "a.mp4" in got[0]
    assert (inbox / "Готово" / "a.mp4").exists() and not (inbox / "a.mp4").exists()
    assert (inbox / "note.txt").exists() and transcript.drain(out=tmp_path) == []
