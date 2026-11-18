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


def test_windows_vad_hears_end_of_phrase():
    """Без Silero VAD на Windows запись не кончалась бы никогда: тишина после речи должна быть тишиной."""
    import numpy as np

    from justday.audio import LoudnessVAD

    vad, rng = LoudnessVAD(), np.random.default_rng(0)
    room = lambda: (rng.normal(0, 30, 1280)).astype(np.int16)  # noqa: E731
    voice = lambda: (rng.normal(0, 3000, 1280)).astype(np.int16)  # noqa: E731
    for _ in range(20):
        vad.predict(room())
    assert vad.predict(voice()) == 1.0
    assert vad.predict(room()) == 0.0


def test_speech_goes_to_groq_whisper(monkeypatch):
    """Распознавание на Windows — бесплатный Whisper у Groq: в запросе должен быть сам звук и язык."""
    import io
    import json

    import numpy as np

    from justday import providers

    sent = {}

    def urlopen(req, timeout):
        sent["url"], sent["body"] = req.full_url, req.data
        return io.BytesIO(json.dumps({"text": "открой блокнот"}).encode())

    monkeypatch.setattr(providers, "secret_get", lambda name: "k" if name == "groq" else "")
    monkeypatch.setattr(freellm.urllib.request, "urlopen", urlopen)
    assert freellm.transcribe(np.zeros(16000, dtype=np.int16)) == "открой блокнот"
    assert sent["url"].endswith("/audio/transcriptions") and b"RIFF" in sent["body"] and b"\r\nru\r\n" in sent["body"]
