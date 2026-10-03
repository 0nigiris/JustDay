"""Музыка так, как он говорит. Громкая ошибка здесь — «просил свет, а он врубил музыку»."""
import pytest

from justday import media

LIB = [
    {"title": "Группа крови", "artist": "Кино", "file": "/x/1"},
    {"title": "Smells Like Teen Spirit", "artist": "Nirvana", "file": "/x/2"},
    {"title": "Девочка с картинки", "artist": "Пошлая Молли", "file": "/x/3"},
]


@pytest.fixture
def lib(monkeypatch):
    monkeypatch.setattr(media, "library", lambda kind="music": LIB)
    monkeypatch.setattr(media, "_is_app", lambda q: q in ("дискорд", "discord", "ютуб"))


@pytest.mark.parametrize("phrase", [
    "включи музыку", "Включи музыку.", "включи", "врубай", "вруби", "врубани музыку", "запусти музыку",
    "поставь музыку", "поставь-ка музыку", "давай музыку", "музыку давай", "музыка давай", "можно музыку",
    "хочу музыку", "хочу послушать музыку", "музончик", "включи музончик", "музычку", "запили музыку",
    "включи что-нибудь", "поставь чё-нибудь", "включи какую-нибудь песню", "поставь песенку", "музло",
    "джарвис, врубай музон", "включи мою музыку", "играй", "погнали",
])
def test_these_mean_music_from_the_library(lib, phrase):
    assert media.live_music(phrase) == ("library", "")


@pytest.mark.parametrize("phrase,query", [
    ("Кино — Группа крови", "кино группа крови"),
    ("поставь Nirvana", "nirvana"),
    ("включи Nirvana", "nirvana"),
    ("Пошлая Молли", "пошлая молли"),
    ("включи песню Группа крови", "группа крови"),
    ("поставь трек от Nirvana", "nirvana"),
    ("сыграй Пошлая Молли", "пошлая молли"),
    ("поставь Radiohead", "radiohead"),        # нет в фонотеке, но похоже на имя: ищем снаружи
])
def test_a_title_without_a_command_is_a_track(lib, phrase, query):
    assert media.live_music(phrase) == ("music", query)


@pytest.mark.parametrize("phrase", [
    "включи свет", "включи телевизор", "включи телик", "поставь будильник на семь", "поставь будильник",
    "поставь на зарядку", "поставь чайник", "поставь таймер на пять минут", "включи видео про котов",
    "включи дискорд", "включи ютуб", "выключи свет", "включи кондиционер", "включи звук",
    "поставь чай",                              # не имя: строчные, латиницы нет
    "который час", "как дела", "что ты умеешь", "открой дискорд", "включи в комнате свет",
    "да", "нет", "спасибо", "расскажи про Nirvana", "найди Nirvana",
])
def test_these_are_not_music(lib, phrase):
    assert media.live_music(phrase) is None, phrase


def test_empty_library_never_breaks_anything(monkeypatch):
    """Пустая фонотека: «включи» уходит мозгу, а не падает; название без команды — не музыка."""
    monkeypatch.setattr(media, "library", lambda kind="music": [])
    monkeypatch.setattr(media, "_is_app", lambda q: False)
    assert media.parse("включи") is None
    assert media.parse("включи музыку") is None
    assert media.parse("Пошлая Молли") is None
    assert media.live_music("поставь Nirvana") == ("music", "nirvana")


@pytest.mark.parametrize("phrase,act", [
    ("стоп", "pause"), ("хватит", "pause"), ("стопани", "pause"), ("дальше", "next"), ("скипни", "next"),
    ("следующую", "next"), ("предыдущую", "prev"), ("назад", "prev"), ("туши", "stop"), ("выключай", "stop"),
    ("давай", "resume"), ("врубай", "resume"), ("включи", "resume"),
])
def test_controls(phrase, act):
    assert media.control_word(phrase) == act


def test_louder_and_quieter():
    from justday import fastpath
    for p in ("громче", "погромче", "чуть громче", "потише", "тише", "немного тише"):
        assert any(rx.match(fastpath._clean(p)) for rx, _c, _d in fastpath.MEDIA), p
