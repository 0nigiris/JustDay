"""Игра в фокусе часами, а Джарвис молчит или, наоборот, твердит раз в минуту."""
import asyncio
import time

from justday import guardian

CFG = {"watch": {"apps": ["roblox"], "after_minutes": 10}, "user": {"address_as": "сэр"}}
GAME = [{"app": "RobloxPlayer", "title": "Roblox", "active": True, "minimized": False}]


def run(windows, now, path, said):
    async def deliver(t):
        said.append(t)
    return asyncio.run(guardian.tick(windows, deliver, CFG, now, path))


def test_speaks_once_a_day_after_the_wait(tmp_path):
    p, said, t0 = tmp_path / "g.json", [], time.time()
    run(GAME, t0, p, said)
    run(GAME, t0 + 300, p, said)
    assert said == []                      # пять минут — ещё рано
    run(GAME, t0 + 700, p, said)
    run(GAME, t0 + 800, p, said)
    assert len(said) == 1 and said[0].startswith("Сэр, ")


def test_leaving_the_game_resets_the_wait(tmp_path):
    p, said, t0 = tmp_path / "g.json", [], time.time()
    run(GAME, t0, p, said)
    run([], t0 + 500, p, said)             # свернул игру
    run(GAME, t0 + 700, p, said)           # вернулся: отсчёт заново
    assert said == []
