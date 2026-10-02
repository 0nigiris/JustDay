"""Три беды, о которых он сказал голосом: его перебивали, его не слушали и ему не отвечали.

Названия тут — про беду, а не про функции: через полгода важно, что именно сломалось у человека.
"""
from __future__ import annotations

import re
from pathlib import Path

from justday import audio, calendar_lane

ROOT = Path(__file__).resolve().parent.parent


def test_the_speak_button_was_turning_the_voice_off() -> None:
    """Он нажимал «говорить», а Джарвис молчал — и сколько ни нажимай, ничего не менялось.

    Островок посылает `voice_mute` со словом `on`, означающим «пусть говорит». Демон это слово
    отрицал — выходило «молчи». Кнопка при этом сразу отрисовывалась включённой и через миг
    возвращалась обратно, так что со стороны это выглядело как «не нажимается».
    """
    island = (ROOT / "island" / "JD.qml").read_text(encoding="utf-8")
    assert 'send({ cmd: "voice_mute", on: !on })' in island, "островок стал посылать это иначе"

    daemon = (ROOT / "src" / "justday" / "daemon.py").read_text(encoding="utf-8")
    body = daemon.split('elif cmd == "voice_mute"', 1)[1][:600]
    assert "set_voice(bool(" in body
    assert "set_voice(not" not in body, "демон снова понимает «on» наоборот"


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
    assert re.search(r"if \(wins\.length > 1\) \{ dv\.cycle\(wins, 1, 0\); return \}", press), \
        "щелчок по значку больше не ведёт по окнам"
    assert '{ id: "minimize", label: "Свернуть все окна"' in dock, \
        "свернуть всё разом стало нечем: щелчок это больше не делает"
