"""Джарвис без Claude Code (Windows у друга) должен думать бесплатной моделью, а не двумя регулярками."""
from justday import desktop, freellm, offline


def test_free_model_answers_and_remembers(monkeypatch):
    """Ответ в ```json``` и с памятью: «а погромче» без прошлой реплики не понять."""
    seen = []

    def chat(messages, **_):
        seen.append(messages)
        return '```json\n{"action": "volume", "query": "+", "answer": "Громче."}\n```'

    monkeypatch.setattr(freellm, "ready", lambda: [{"id": "groq"}])
    monkeypatch.setattr(freellm, "chat", chat)
    monkeypatch.setattr(desktop, "list_apps", lambda: [])
    offline._history.clear()
    got = offline.decide("сделай громче")
    assert got["action"] == "volume" and got["query"] == "+" and got["cloud"]
    offline.decide("ещё")
    assert any(m["content"] == "сделай громче" for m in seen[1])


def test_free_model_silent_falls_back(monkeypatch):
    """Все бесплатные молчат (лимит, сеть) — не падать, а уйти к местной модели и регуляркам."""
    def dead(*a, **k):
        raise RuntimeError("groq: HTTPError")

    monkeypatch.setattr(freellm, "ready", lambda: [{"id": "groq"}])
    monkeypatch.setattr(freellm, "chat", dead)
    monkeypatch.setattr(desktop, "list_apps", lambda: [])
    assert not offline.decide("открой блокнот").get("cloud")
