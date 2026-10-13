"""«Включи ~/» обходил папку прямо в цикле событий демона: на это время замирали и голос, и остров."""
import asyncio
import time
import types

from justday import media, music_lane


def test_playing_a_big_folder_does_not_freeze_the_daemon(monkeypatch, tmp_path):
    (tmp_path / "a.mp3").write_bytes(b"")
    monkeypatch.setattr(music_lane.memory, "resolve", lambda q: q)

    def slow(path):                      # теги сотни файлов на медленном диске
        time.sleep(0.3)
        return {"title": "a", "path": path}

    monkeypatch.setattr(media, "local_track", slow)

    async def nothing(*a, **k):
        return True

    music = types.SimpleNamespace(active=False, ensure=nothing, load=nothing, remember=lambda: None)
    lane = types.SimpleNamespace(music=music, _pause_videos=lambda: None)

    async def go():
        ticks = 0

        async def tick():
            nonlocal ticks
            while True:
                await asyncio.sleep(0.02)
                ticks += 1

        t = asyncio.create_task(tick())
        got = await music_lane.MusicMixin.play_music(lane, str(tmp_path))
        t.cancel()
        return got, ticks

    got, ticks = asyncio.run(go())
    assert got["ok"] and got["title"] == "a"
    assert ticks >= 5
