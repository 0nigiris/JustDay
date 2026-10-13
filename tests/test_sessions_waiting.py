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


def _err(kind, text):
    return json.dumps({"type": "assistant", "isApiErrorMessage": True, "error": kind,
                       "message": {"content": [{"type": "text", "text": text}]}})


def test_упёршаяся_в_лимит_сессия_не_выглядит_спокойно_ждущей(tmp_path, monkeypatch):
    """Сессия упиралась в лимит посреди работы, а `claude agents` показывал её «idle» — как закончившую.
    Человек думал, что дело сделано (Р2-39 «упала»)."""
    user = json.dumps({"type": "user", "message": {"content": "продолжай"}})
    _log(tmp_path, monkeypatch, user, _err("rate_limit", "You've hit your session limit · resets 2:30am (Europe/Madrid)"))
    assert sessions.failed("s1") == "упёрлась в лимит · до 2:30am"


def test_ошибка_после_которой_он_написал_дальше_уже_история(tmp_path, monkeypatch):
    later = json.dumps({"type": "user", "message": {"content": "давай ещё раз"}})
    meta = json.dumps({"type": "system", "subtype": "turn_duration"})
    _log(tmp_path, monkeypatch, _err("server_error", "API Error: Server error"), later, meta)
    assert sessions.failed("s1") == ""


def test_a_click_on_a_session_raises_its_own_terminal_and_never_someone_elses(monkeypatch):
    """Карточка «ждёт ответа» без перехода заставляла искать нужный терминал среди окон.

    Claude Code — внук окна: kitty → zsh → claude. Окно находится подъёмом по родителям; сессия в
    фоне или в tmux (родитель — служба или сервер tmux) окна не получает, а не чужое первое попавшееся.
    """
    from justday import sessions

    parents = {300: 200, 200: 100, 100: 1, 700: 600, 600: 1}
    monkeypatch.setattr(sessions, "_parent", lambda pid: parents.get(pid, 0))
    windows = [{"id": "{kitty}", "pid": 100}, {"id": "{firefox}", "pid": 500}, {"id": "{нет pid}"}]
    assert sessions.window_of(300, windows) == "{kitty}"
    assert sessions.window_of(700, windows) == ""
    assert sessions.window_of(0, windows) == ""
