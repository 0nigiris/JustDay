"""9 нояб.: «давай подключим Fish Audio». Голос должен говорить с ключом из связки, а кончившийся
ключ не должен глушить ассистента, если рядом лежит запасной."""
import asyncio
import io
import json
import urllib.error
import urllib.request

from justday import config, tts


def test_fish_speaks_with_the_next_key_when_the_first_ran_out(monkeypatch):
    monkeypatch.setattr(config, "secrets", lambda name: ["dead", "alive"] if name == "FISH_API_KEY" else [])
    tts.TTS._eleven_dead.clear()
    seen = []

    def fake_urlopen(req, timeout=0):
        seen.append((req.full_url, dict(req.header_items()), json.loads(req.data)))
        if "dead" in req.get_header("Authorization"):
            raise urllib.error.HTTPError(req.full_url, 402, "no credits", {}, io.BytesIO())
        return io.BytesIO(b"\x01\x00" * 100)

    monkeypatch.setattr(urllib.request, "urlopen", fake_urlopen)
    t = tts.TTS({"sample_rate": 48000, "engine": "fish", "fish_voice": "abc", "fish_model": "s2.1-pro-free"})

    async def run():
        return b"".join([c async for c in t.fish_stream("Привет")])

    assert asyncio.run(run()) == b"\x01\x00" * 100
    url, headers, body = seen[-1]
    assert url == tts.TTS.FISH_URL and headers["Authorization"] == "Bearer alive" and headers["Model"] == "s2.1-pro-free"
    assert body["reference_id"] == "abc" and body["format"] == "pcm" and body["sample_rate"] == 24000
    tts.TTS._eleven_dead.clear()
