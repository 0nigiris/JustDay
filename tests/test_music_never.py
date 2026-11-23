"""Он не выносит лоу-фай, а запрет держался только на памяти модели: быстрый путь его не видел и включал."""
import asyncio
import types

from justday import config, media, music_lane


def test_banned_word_in_title_is_never_played(monkeypatch):
    monkeypatch.setattr(music_lane.memory, "resolve", lambda q: q)
    monkeypatch.setattr(media, "find_local", lambda q, limit=1: [])
    monkeypatch.setattr(media, "find", lambda q, kind, n: [{"title": "Chill LoFi beats to study"}])
    real = config.load()
    monkeypatch.setattr(config, "load", lambda: {**real, "media": {**real["media"], "never": ["lofi"]}})
    loaded = []

    async def nothing(*a, **k):
        loaded.append(a)
        return True

    music = types.SimpleNamespace(active=False, ensure=lambda: asyncio.sleep(0), load=nothing,
                                  set_loading=lambda v: None)
    lane = types.SimpleNamespace(music=music, _pause_videos=lambda: None)
    got = asyncio.run(music_lane.MusicMixin.play_music(lane, "музыка для учёбы"))
    assert not got["ok"] and not loaded
