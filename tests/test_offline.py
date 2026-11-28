"""Джарвис без облака: что он делает сам и что говорит."""
from justday import offline


def test_no_brain_says_so(monkeypatch):
    """Без нейросети Джарвис говорил «облако не отвечает, работаю сам» (28 нояб.) — казалось, что он думает."""
    from justday import freellm

    monkeypatch.setattr(freellm, "ready", lambda: [])
    got = offline._guess("как дела")
    assert got["nobrain"] and "мозга у меня нет" in got["answer"]
