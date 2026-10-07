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


def test_модель_берётся_из_последнего_ответа(tmp_path, monkeypatch):
    """В списке сессий не было видно, на какой модели идёт каждая, а лимит у семейств разный (Р2-39)."""
    row = lambda m: json.dumps({"message": {"model": m, "content": []}})  # noqa: E731
    _log(tmp_path, monkeypatch, row("claude-opus-5-5"), row("claude-sonnet-5-5"))
    assert sessions.model_of("s1") == "sonnet"


def test_правка_без_результата_это_ожидание_разрешения(tmp_path, monkeypatch):
    """Сессия ждала разрешения на правку, а в списке горела «работает» (Р2-39)."""
    import time
    old = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime(time.time() - 60))
    fresh = time.strftime("%Y-%m-%dT%H:%M:%S+00:00", time.gmtime())

    def edit(i, ts):
        return json.dumps({"timestamp": ts, "message": {"content": [{"type": "tool_use", "id": i, "name": "Edit", "input": {}}]}})

    _log(tmp_path, monkeypatch, edit("a", old))
    assert sessions.asking("s1") == "Edit"
    _log2 = tmp_path / ".claude" / "projects" / "p" / "s1.jsonl"
    _log2.write_text(edit("b", fresh) + "\n")
    assert sessions.asking("s1") == ""            # только что начала — это ещё работа
