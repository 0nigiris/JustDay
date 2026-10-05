"""Р-11: журнал сказанного и конфиг с токенами MCP лежали читаемыми для любого процесса пользователя."""
import json
import stat

from justday import config, events, shell


def mode(path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_the_event_journal_is_private_even_when_it_was_created_open(tmp_path, monkeypatch) -> None:
    """Там всё, что сказано вслух, и начало аргументов инструментов; старый файл с 0644 подтягивается."""
    journal = tmp_path / "events.jsonl"
    journal.write_text("")
    journal.chmod(0o644)
    monkeypatch.setattr(config, "STATE_DIR", tmp_path)
    monkeypatch.setattr(config, "EVENTS_FILE", journal)
    monkeypatch.setattr(events, "_tightened", False)
    events.emit("heard", text="секрет")
    assert mode(journal) == 0o600
    assert json.loads(journal.read_text().splitlines()[-1])["text"] == "секрет"

    fresh = tmp_path / "new" / "events.jsonl"
    monkeypatch.setattr(config, "STATE_DIR", fresh.parent)
    monkeypatch.setattr(config, "EVENTS_FILE", fresh)
    events.emit("heard", text="ещё")
    assert mode(fresh) == 0o600


def test_write_private_replaces_an_open_file_without_a_readable_moment(tmp_path) -> None:
    target = tmp_path / "secrets.env"
    target.write_text("old")
    target.chmod(0o644)
    config.write_private(target, "new=1\n")
    assert target.read_text() == "new=1\n" and mode(target) == 0o600
    assert not [p for p in tmp_path.iterdir() if p.name.endswith(".tmp")], "временный файл остался"


def test_opencode_json_with_mcp_tokens_is_private(tmp_path, monkeypatch) -> None:
    conf = tmp_path / "opencode.json"
    conf.write_text("{}")
    conf.chmod(0o644)
    monkeypatch.setattr(shell, "SETTINGS", conf)
    monkeypatch.setattr(shell, "LADDER", tmp_path / "ladder.json")
    monkeypatch.setattr(shell, "mcp_from_claude", lambda: {"x": {"env": {"TOKEN": "t"}}})
    monkeypatch.setattr(shell, "skill_paths", lambda: [])
    shell.ensure()
    assert "TOKEN" in conf.read_text() and mode(conf) == 0o600
