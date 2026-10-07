"""Сессия стояла с вопросом к человеку, а в списке горела «работает» (Р2-39)."""
import json

from justday import sessions


def _use(i, name):
    return json.dumps({"message": {"content": [{"type": "tool_use", "id": i, "name": name, "input": {}}]}})


def _res(i):
    return json.dumps({"message": {"content": [{"type": "tool_result", "tool_use_id": i}]}})


def _log(tmp_path, monkeypatch, *lines):
    monkeypatch.setattr(sessions, "HOME", tmp_path)
    d = tmp_path / ".claude" / "projects" / "p"
    d.mkdir(parents=True)
    (d / "s1.jsonl").write_text("\n".join(lines) + "\n")


def test_вопрос_без_ответа_это_ожидание(tmp_path, monkeypatch):
    _log(tmp_path, monkeypatch, _use("a", "Read"), _res("a"), _use("b", "AskUserQuestion"))
    assert sessions.asking("s1") == "AskUserQuestion"


def test_отвеченный_вопрос_не_ожидание(tmp_path, monkeypatch):
    _log(tmp_path, monkeypatch, _use("b", "AskUserQuestion"), _res("b"), _use("c", "Bash"))
    assert sessions.asking("s1") == ""
