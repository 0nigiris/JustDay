"""Один давно законченный работник заставлял демон звать `claude agents --json` каждые 15 секунд навсегда."""
from justday import workers


def test_a_finished_worker_is_not_polled_forever(monkeypatch):
    calls = []
    monkeypatch.setattr(workers, "_registry", lambda: {"9e9d8895": {"reported_state": "done"}})
    monkeypatch.setattr(workers, "agents", lambda *a, **k: calls.append(1) or [])
    assert workers.pending_reports() == ([], 0)
    assert calls == []


def test_a_running_worker_is_still_watched(monkeypatch):
    """Пока работник не доложил конец — опрос нужен, иначе о готовой работе никто не узнает."""
    saved = {}
    monkeypatch.setattr(workers, "_registry", lambda: {"a1": {"reported_state": None, "task": "x"}})
    monkeypatch.setattr(workers, "agents", lambda *a, **k: [{"id": "a1", "state": "done"}])
    monkeypatch.setattr(workers.events, "save_state", lambda **k: saved.update(k))
    out, active = workers.pending_reports()
    assert [r["state"] for r in out] == ["done"] and active == 0
    assert saved["workers"]["a1"]["reported_state"] == "done"
