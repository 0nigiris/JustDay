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
