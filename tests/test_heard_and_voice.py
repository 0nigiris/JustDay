"""Три беды, о которых он сказал голосом: его перебивали, его не слушали и ему не отвечали.

Названия тут — про беду, а не про функции: через полгода важно, что именно сломалось у человека.
"""
from __future__ import annotations

import importlib.util
import re
import sys
import types
from pathlib import Path

from justday import audio, calendar_lane

ROOT = Path(__file__).resolve().parent.parent


def test_the_speak_button_was_turning_the_voice_off(monkeypatch) -> None:
    """Он нажимал «говорить», а Джарвис молчал — и сколько ни нажимай, ничего не менялось.

    Островок посылает `voice_mute` со словом `on`, означающим «пусть говорит». Демон это слово
    отрицал — выходило «молчи». Кнопка при этом сразу отрисовывалась включённой и через миг
    возвращалась обратно, так что со стороны это выглядело как «не нажимается».
    """
    import asyncio
    import json
    import types

    from justday import daemon, events

    class Reader:
        async def readline(self):
            return b'{"cmd":"voice_mute","on":true}\n'

    class Writer:
        data = b""

        def write(self, data):
            self.data += data

        async def drain(self):
            pass

        def close(self):
            pass

    d = daemon.Daemon.__new__(daemon.Daemon)
    d.cfg = {"tts": {"muted": True}}
    d._state = "idle"
    d.brain = types.SimpleNamespace(busy=False, note=lambda _text: None)
    d.publish = lambda **_message: None
    spoken = []
    d.say = lambda text: spoken.append(text) or asyncio.sleep(0)
    writer = Writer()
    monkeypatch.setattr(daemon.config, "set_value", lambda *_args: None)
    monkeypatch.setattr(events, "emit", lambda *_args, **_kwargs: None)
    asyncio.run(d._client(Reader(), writer))

    reply = json.loads(writer.data)
    assert d.cfg["tts"]["muted"] is False, "команда «говори» снова выключила голос"
    assert reply["muted"] is False, "ответ островку сказал, что голос выключен"
    assert spoken == ["голос включён"]


def test_a_long_story_was_answered_with_the_calendar() -> None:
    """Он надиктовывал беду, а в ответ услышал, что на сегодня в календаре ничего нет.

    Слово «встреча» или «что у меня сегодня» может попасться внутри рассказа. Короткий вопрос
    про календарь — это просьба; длинный рассказ, где слово просто мелькнуло, — работа для мозга.
    """
    assert calendar_lane.wants("что у меня сегодня")
    assert calendar_lane.wants("какие встречи завтра")
    assert not calendar_lane.wants(
        "короче смотри какая проблема у меня тут была встреча с одним человеком и он сказал "
        "что нужно переделать весь экран инструментов потому что там кнопки висят в пустоте")


def test_a_pause_in_the_middle_of_a_thought_cut_him_off() -> None:
    """Он говорил долго, задумался на секунду — и запись оборвалась на полуслове.

    Огрызок уходил дальше как готовая просьба, и ассистент отвечал на половину сказанного.
    Короткая команда при этом должна обрываться быстро, иначе ассистент кажется тугим, — поэтому
    терпение к паузам растёт вместе с тем, как долго человек говорит.
    """
    rec = audio.UtteranceRecorder.__new__(audio.UtteranceRecorder)
    audio.UtteranceRecorder.__init__(rec, None, 1.0, 7, 40, 2.2, 5.0)

    assert rec.patience(1.5) == 1.0          # «открой дискорд» — обрываем сразу
    assert rec.patience(12.0) == 2.2         # рассказ на полминуты — даём додумать


def test_pause_tolerance_never_shrinks_below_the_short_one() -> None:
    """Настройка «долгая пауза меньше короткой» означала бы, что чем дольше говоришь, тем быстрее
    тебя обрывают. Такое человек мог написать в конфиге только по ошибке."""
    rec = audio.UtteranceRecorder.__new__(audio.UtteranceRecorder)
    audio.UtteranceRecorder.__init__(rec, None, 1.5, 7, 40, 0.5, 5.0)
    assert rec.patience(30.0) >= rec.patience(0.5)


def test_the_dock_icon_walks_through_the_windows() -> None:
    """Он просил: нажал на значок — первое окно, нажал ещё — второе, и так по кругу.

    Раньше второй щелчок по значку сворачивал все окна программы сразу, и до второго окна
    добраться щелчками было нельзя вовсе.
    """
    dock = (ROOT / "island" / "DockView.qml").read_text(encoding="utf-8")
    press = dock.split("function press(e, wins)", 1)[1].split("\n    function ", 1)[0]
    assert re.search(r"wins\.length > 1[^\n]*cycle\(wins, 1, 0\)", press), \
        "щелчок по значку больше не ведёт по окнам"
    assert '{ id: "minimize", label: "Свернуть все окна"' in dock, \
        "свернуть всё разом стало нечем: щелчок это больше не делает"


def test_he_was_cut_off_exactly_on_the_fortieth_second() -> None:
    """Самая долгая просьба обрывалась по секундомеру — ровно на сороковой секунде, посреди слова.

    В журнале это видно как `heard … "seconds": 40.0` и оборванный на полуслове текст: половина
    сказанного уходила в работу как целая просьба. Срок остался, но он больше не нож: после него
    ждём ближайшей паузы. Жёсткий потолок нужен только против микрофона, который «говорит» сам —
    включённого телевизора или зависшей гарнитуры.
    """
    rec = audio.UtteranceRecorder.__new__(audio.UtteranceRecorder)
    audio.UtteranceRecorder.__init__(rec, None, 0.6, 7, 40, 2.2, 5.0)

    assert rec.patience(41.0) < rec.patience(20.0), "после срока надо ждать паузы, а не рубить"
    assert rec.hard_max_s > 40, "потолок совпал со сроком — значит нож остался"
    assert rec.hard_max_s <= 300, "без разумного потолка запись не кончится никогда"


def test_jarvis_stopped_hearing_because_warming_the_voice_crashed_the_listening() -> None:
    """«Почему Джарвис теперь меня не слышит?» — заход в прослушивание падал на прогреве голоса.

    Прогрев отправлялся в сторону через `run_in_executor`, а тот отдаёт Future; задачу делают из
    корутины, и получался TypeError прямо в присваивании состояния. Падало не «греть голос», а
    весь заход в прослушивание — слушать было больше некому.
    """
    import asyncio
    import types
    import typing

    from justday import daemon

    class Fake:
        cfg: typing.ClassVar = {"tts": {"engine": "qwen"}}
        stt = types.SimpleNamespace(warm=lambda: None)
        tts = types.SimpleNamespace(nudge=lambda what: None)

        def silent(self) -> bool:
            return False

    async def go() -> None:
        daemon.Daemon._warm_models(Fake(), "listening")   # падало здесь
        await asyncio.sleep(0.05)

    asyncio.run(go())


def test_an_ordinary_request_was_swallowed_by_the_mail_lane() -> None:
    """«Прошу обычный запрос — а он сразу лезет в локальную почту».

    После любого разговора о почте дорожка оставалась открытой две минуты и забирала всё, что
    человек скажет следующим. Длинная просьба — это уже другая задача, и место ей у мозга: ровно
    та же беда, что была с календарём, который отвечал на рассказ «сегодня ничего не запланировано».
    """
    import time

    from justday import mail

    box = mail.MailAssistant()
    box.active_until = time.monotonic() + 120        # только что говорили о почте

    assert box.wants("да"), "короткий ответ в разговоре о почте должен остаться в почте"
    assert box.wants("прочитай второе")
    assert not box.wants("сделай мне, пожалуйста, режим сервера и запусти работу на ночь"), \
        "обычная просьба опять уехала в почту"
    # Его настоящий случай: длинный рассказ про спор с GitHub, в котором попалось «пиши письма».
    story = ("у меня проблемка с GitHub, я подаю заявку на студента, а мне отказывают, я уже писал "
             "репорт и мне не ответили, реши это как-нибудь, если хочешь — сам пиши письма, "
             "даю тебе полный контроль")
    assert not box.wants(story), "рассказ со словом «письма» опять уехал в почту вместо мозга"
    assert box.wants("проверь почту"), "просьба про почту без окна всё равно почтовая"
    assert box.wants("напиши письмо маме, что задержусь до восьми"), \
        "короткая просьба написать письмо — это всё-таки почта"


def test_the_voice_that_did_not_fit_on_the_card_used_to_leave_jarvis_silent(monkeypatch) -> None:
    """Голос грузился, пока судья ещё держал шесть гигабайт: CUDA out of memory — и Джарвис молчал.

    Теперь при нехватке памяти голос просит Ollama отпустить модели и пробует снова; если и после
    этого не вышло — говорит человеку словами, что мешает.
    """
    class OOM(Exception):
        pass

    attempts, freed = [], []

    class Fake:
        @staticmethod
        def from_pretrained(_name):
            attempts.append(1)
            if len(attempts) < 3:
                raise OOM()
            return types.SimpleNamespace(warmup=lambda **_k: None)

    torch = types.SimpleNamespace(cuda=types.SimpleNamespace(OutOfMemoryError=OOM, empty_cache=lambda: None))
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "numpy", types.ModuleType("numpy"))
    monkeypatch.setitem(sys.modules, "soundfile", types.ModuleType("soundfile"))
    monkeypatch.setitem(sys.modules, "faster_qwen3_tts", types.SimpleNamespace(FasterQwen3TTS=Fake))
    path = Path(__file__).resolve().parent.parent / "voice" / "server.py"
    spec = importlib.util.spec_from_file_location("justday_voice_under_test", path)
    assert spec and spec.loader
    service = importlib.util.module_from_spec(spec)
    monkeypatch.setitem(sys.modules, "justday_voice_under_test", service)
    spec.loader.exec_module(service)
    service.time = types.SimpleNamespace(time=lambda: 0.0, sleep=lambda _s: None)
    service._free_ollama = lambda: freed.append(1) or 1
    service.log = lambda *_args: None
    assert service.load_base() is not None
    assert len(attempts) == 3 and len(freed) == 2, "голос не просил освободить память между попытками"
    attempts.clear()
    service.model = None
    Fake.from_pretrained = staticmethod(lambda _n: (_ for _ in ()).throw(OOM()))
    try:
        service.load_base()
    except RuntimeError as e:
        assert "видеопамяти" in str(e)
    else:
        raise AssertionError("после трёх неудач человеку должны сказать словами")


def test_phrase_cut_on_a_preposition_is_not_finished():
    """Беда: «поставь таймер на…» — пауза на секунду, и уходил огрызок. Фраза на «на»/«и» не закончена, «да» — закончена."""
    from justday import fastpath
    assert fastpath.unfinished("поставь таймер на")
    assert fastpath.unfinished("включи музыку, и")
    assert not fastpath.unfinished("поставь таймер на пять минут")
    assert not fastpath.unfinished("да")
