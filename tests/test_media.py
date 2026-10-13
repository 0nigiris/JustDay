"""«Включи музыку, любую» уходило к мозгу и думало полминуты: простая просьба без выбора
должна ловиться быстрым путём, а «погромче» и вопросы — нет."""

import pytest

from justday import media

ЛЮБАЯ = ["включи музыку", "включи музыку, любую", "включи что-нибудь", "любую музыку", "музыку включи",
         "включи любую музыку", "поставь какую-нибудь музыку", "включи музыку любую", "давай музыку",
         "включи что нибудь послушать", "включи музончик", "включи любую песню", "музыку давай любую",
         "поставь что-нибудь"]
НЕ_ОНА = ["включи музыку погромче", "какая музыка играет", "включи свет", "поставь будильник на семь",
          "включи телевизор", "сделай музыку потише"]


@pytest.mark.parametrize("фраза", ЛЮБАЯ)
def test_просьба_без_выбора_быстрый_путь(фраза):
    assert media.live_music(фраза) == ("library", "")


@pytest.mark.parametrize("фраза", НЕ_ОНА)
def test_остальное_не_музыка_без_выбора(фраза):
    assert media.live_music(фраза) != ("library", "")


def test_пустая_медиатека_не_уводит_к_мозгу(monkeypatch):
    monkeypatch.setattr(media, "library", lambda *a, **k: [])
    assert media.parse("включи музыку, любую")[0] == "music"


def test_микшер_подписывал_песню_из_youtube_хвостом_адреса(monkeypatch):
    """Поток JustDay в микшере был подписан «mp4&rqh=1&gir=yes&clen=…»: mpv отдаёт звуковой системе
    имя файла, а у потоковой песни это адрес googlevideo. Название должно уходить в mpv при загрузке,
    и запятая в нём не должна резать его как разделитель опций."""
    import asyncio
    sent = []
    p = media.MusicPlayer(lambda s: None)

    async def ensure():
        pass

    async def command(*cmd):
        sent.append(cmd)

    monkeypatch.setattr(p, "ensure", ensure)
    monkeypatch.setattr(p, "command", command)
    monkeypatch.setattr(media, "_remember_tracks", lambda *a: None)
    t = {"file": "https://rr1.googlevideo.com/videoplayback?mime=audio/mp4&rqh=1",
         "title": "Привет, мир", "artist": "Кто-то"}
    asyncio.run(p.load([t]))
    load = next(c for c in sent if c[0] == "loadfile")
    name = "Кто-то — Привет, мир"
    assert load[-1] == f"force-media-title=%{len(name.encode())}%{name}"
