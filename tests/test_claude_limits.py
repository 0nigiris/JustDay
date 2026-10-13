"""Лимит подписки кончался посреди дела без предупреждения: сколько осталось, видно не было (Р2-39)."""
import io
import json

from justday import sessions, statusline


def _run(monkeypatch, payload) -> str:
    out = io.StringIO()
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload)))
    monkeypatch.setattr("sys.stdout", out)
    statusline.main()
    return out.getvalue().strip()


def test_the_status_line_hands_the_limit_to_the_island(monkeypatch, tmp_path):
    """Числа есть только у статусной строки Claude Code — она должна оставить их демону."""
    monkeypatch.setattr(statusline, "FILE", tmp_path / "l.json")
    monkeypatch.setattr(sessions, "LIMITS_FILE", tmp_path / "l.json")
    now = 1_000_000.0
    got = _run(monkeypatch, {"model": {"display_name": "Opus"}, "rate_limits": {
        "five_hour": {"used_percentage": 41.6, "resets_at": now + 3600},
        "seven_day": {"used_percentage": 13, "resets_at": now + 86400}}})
    assert got == "Opus · 5 ч 42% · неделя 13%"
    shown = sessions.limits(now)
    assert shown.startswith("Лимит Claude: 5 ч — 42% (сброс в ") and shown.endswith("· неделя — 13%")


def test_an_old_window_does_not_scare_him_after_the_reset(monkeypatch, tmp_path):
    """«5 ч — 97%» со вчерашнего вечера — неправда: окно уже сбросилось."""
    monkeypatch.setattr(sessions, "LIMITS_FILE", tmp_path / "l.json")
    (tmp_path / "l.json").write_text(json.dumps({"five_hour": {"used": 97, "resets_at": 10}}))
    assert sessions.limits(100) == ""


def test_without_limits_the_line_still_shows_and_keeps_the_old_numbers(monkeypatch, tmp_path):
    """До первого ответа модели `rate_limits` нет — нельзя ни упасть, ни стереть прежние числа."""
    f = tmp_path / "l.json"
    f.write_text("{}")
    monkeypatch.setattr(statusline, "FILE", f)
    assert _run(monkeypatch, {"model": {"display_name": "Haiku"}}) == "Haiku"
    assert f.read_text() == "{}"
