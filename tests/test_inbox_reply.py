"""Поручение уходило на ПК и пропадало: тот, кто его передал, не узнавал, чем дело кончилось."""
from justday import inbox


def test_reply_is_stored_and_visible(tmp_path, monkeypatch):
    monkeypatch.setattr(inbox, "FILE", tmp_path / "inbox.jsonl")
    item = inbox.add("поставь сборку на утро")
    assert inbox.reply(item["id"], "сборка запущена на 07:00")
    assert inbox.recent()[0]["reply"] == "сборка запущена на 07:00"
    assert item["id"] in inbox.summary([item])


def test_reply_to_unknown_or_empty_is_refused(tmp_path, monkeypatch):
    monkeypatch.setattr(inbox, "FILE", tmp_path / "inbox.jsonl")
    item = inbox.add("дело")
    assert not inbox.reply("нет-такого", "ответ")
    assert not inbox.reply(item["id"], "  ")


def test_photo_is_copied_and_queued_and_junk_refused(tmp_path, monkeypatch):
    """Фото-доказательство с телефона: временный файл агента удаляется, поэтому нужна копия."""
    import pytest
    monkeypatch.setattr(inbox, "FILE", tmp_path / "inbox.jsonl")
    monkeypatch.setattr(inbox, "PHOTOS", tmp_path / "proofs")
    shot = tmp_path / "x.jpg"
    shot.write_bytes(b"\xff\xd8")
    item = inbox.add_photo(str(shot))
    kept = item["text"].split(": ", 1)[1]
    shot.unlink()
    assert (tmp_path / "proofs").glob("*.jpg") and kept.startswith(str(tmp_path / "proofs"))
    (tmp_path / "evil.sh").write_text("x")
    with pytest.raises(ValueError):
        inbox.add_photo(str(tmp_path / "evil.sh"))
