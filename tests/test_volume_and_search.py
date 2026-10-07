"""Р-48: две громкости одной фразой («Discord на 50, музыку на 20») раньше доходили до мозга, и тот терял вторую.
Р-56: YouTube на точную фразу «mili peach pit and cyanide» молча отдавал ноль результатов — трек «не находился»."""
from __future__ import annotations

import subprocess

from justday import media, volume

ПОТОКИ = [
    {"index": 7, "properties": {"application.name": "Discord", "application.process.binary": "electron"}},
    {"index": 9, "properties": {"application.name": "Firefox"}},
]


def виды(фраза: str) -> list[tuple[str, int]] | None:
    got = volume.plan(фраза, ПОТОКИ)
    return None if got is None else [(a.kind, a.level) for a in got]


def test_две_громкости_одной_фразой() -> None:
    assert виды("громкость Discord 50, а музыку 20") == [("stream", 50), ("music", 20)]
    assert виды("сделай дискорд на 50 и музыку на 20") == [("stream", 50), ("music", 20)]
    assert виды("поставь музыку на 20 и звук на 60") == [("music", 20), ("system", 60)]


def test_одна_часть_не_разобрана_значит_не_делается_ничего() -> None:
    """Половина команды хуже никакой: пусть её разберёт мозг целиком."""
    assert виды("громкость дискорда 50 и телепорта на 20") is None


def test_чужие_фразы_с_числом_не_перехватываются() -> None:
    for фраза in ("поставь будильник на 7", "включи музыку на 20 минут", "открой дискорд", "что будет в 5 часов"):
        assert виды(фраза) is None, фраза


def test_громкость_программы_идёт_в_её_поток() -> None:
    calls = []

    def fake(cmd, *a, **kw):
        calls.append(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    old, volume.subprocess.run = volume.subprocess.run, fake
    try:
        [act] = volume.plan("громкость Discord 40 и музыка 10", ПОТОКИ)[:1]
        assert volume.apply(act)
    finally:
        volume.subprocess.run = old
    assert calls == [["pactl", "set-sink-input-volume", "7", "40%"]]


def test_пустой_ответ_ютуба_переспрашивается(monkeypatch) -> None:
    asked = []

    def ytdlp(*args, timeout=60):
        q = args[-1]
        asked.append(q)
        entries = [] if q == "ytsearch8:mili peach pit and cyanide" else [{"id": "abc", "title": "Mili - Peach Pit and Cyanide"}]
        import json
        return subprocess.CompletedProcess(args, 0, json.dumps({"entries": entries}), "")

    monkeypatch.setattr(media, "_ytdlp", ytdlp)
    found = media.search("mili peach pit and cyanide")
    assert [e["id"] for e in found] == ["abc"]
    assert len(asked) == 2


def test_упавшая_громкость_не_объявляется_выполненной(monkeypatch) -> None:
    """wpctl/pactl вернули ошибку, а ассистент говорил «готово»: теперь фраза уходит мозгу, а не в историю успехов."""
    import asyncio
    from types import SimpleNamespace

    from justday import daemon, volume

    monkeypatch.setattr(volume, "apply", lambda a: False)
    said = []
    fake = SimpleNamespace(say=lambda t: said.append(t))
    levels = [volume.Action("stream", 50, "discord", (1,))]
    assert asyncio.run(daemon.Daemon._set_volumes(fake, "громкость дискорд 50", levels)) is None
    assert said == []


def test_просил_130_а_ставилось_100() -> None:
    """«Громкость Discord 130» срезалось до 100: тихую программу нельзя было усилить (Р2-48)."""
    assert виды("громкость Discord 130") == [("stream", 130)]
    assert виды("громкость Discord 150 и музыка 200") == [("stream", 150), ("music", 200)]
    assert виды("громкость Discord 250 и музыка 10") is None  # выше потолка — не наше дело, уходит мозгу
