"""Режим сервера: машина выключена для человека и работает для ассистента.

Проверяется то, что ломалось у человека, когда он уходил спать: в пустой комнате продолжал идти
фильм, машина потом не засыпала неделю, а утром её встречал тёмный экран и музыка, которую никто
не просил. Живую машину тесты не трогают — все внешние команды подменены.
"""
from __future__ import annotations

import json

import pytest

from justday import server


@pytest.fixture
def machine(monkeypatch, tmp_path):
    """Поддельная машина: запоминает поданные команды и отвечает за `playerctl`."""
    ran: list[tuple[str, ...]] = []
    playing = {"spotify": "Playing", "firefox": "Playing", "vlc": "Paused"}

    def fake_run(*cmd, timeout=10):
        ran.append(cmd)
        return True

    def fake_out(*cmd, timeout=10):
        if cmd[:2] == ("playerctl", "-l"):
            return "\n".join(playing) + "\n"
        if cmd[:2] == ("playerctl", "-p"):
            return playing.get(cmd[2], "") + "\n"
        return ""

    monkeypatch.setattr(server, "_run", fake_run)
    monkeypatch.setattr(server, "_out", fake_out)
    monkeypatch.setattr(server, "_keep_awake", lambda why: 4242)
    monkeypatch.setattr(server, "STATE", tmp_path / "режим.json")
    monkeypatch.setattr(server, "_opts", lambda: {"screens_off": True, "mute": True,
                                                  "pause_players": True, "hours": 10})
    return ran


def test_muting_the_sound_did_not_stop_the_film_playing_in_an_empty_room(machine) -> None:
    """Глухой звук не останавливал ни фильм, ни ролик: серия шла за серией всю ночь.

    Поэтому играющее ставится на паузу — и ровно оно, по именам: снимать с паузы потом надо тех
    же, а не всё, что нашлось.
    """
    out = server.on("ночная работа")

    assert out["ok"] and out["paused"] == ["spotify", "firefox"], \
        "играющее не остановлено — комната так и осталась с фильмом"
    assert ("playerctl", "-p", "vlc", "pause") not in machine, \
        "остановили то, что человек и так поставил на паузу"
    assert ("wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1") in machine
    assert ("kscreen-doctor", "--dpms=off") in machine, "экраны горят: это не режим сервера"


def test_the_screens_go_dark_last_so_a_failure_still_has_words(machine) -> None:
    """Погасив экран первым, любую беду превращаешь в тёмный экран без объяснения."""
    server.on("работа")
    order = [c for c in machine if c[0] in ("playerctl", "wpctl", "kscreen-doctor")]
    assert order[-1] == ("kscreen-doctor", "--dpms=off"), \
        "экраны погасли раньше остального — беду теперь не прочитать"


def test_a_forgotten_server_mode_used_to_keep_the_machine_awake_for_a_week(machine) -> None:
    """Выключить режим стало некому — работа оборвалась, окно закрыли, человек забыл.

    Сторож — служба systemd, а не наш процесс: наш умрёт вместе с работой, служба доживёт.
    """
    out = server.on("ночная работа", hours=9)

    assert out["watchdog"], "сторожа нет: забытый режим это машина, которая не спит неделю"
    started = next(c for c in machine if c[0] == "systemd-run")
    assert "--on-active=32400" in started, "сторож заведён не на тот срок"
    assert started[-3:] == ("server", "off", "--quiet"), \
        "сторож вернёт машину с музыкой — концерт в пустой комнате никто не просил"


def test_the_morning_returns_exactly_what_the_night_took(machine) -> None:
    """Утром должно вернуться всё: экраны, звук, музыка — и ровно та музыка, что играла."""
    server.on("ночная работа")
    machine.clear()

    out = server.off()

    assert ("kscreen-doctor", "--dpms=on") in machine
    assert ("wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0") in machine
    assert out["resumed"] == ["spotify", "firefox"], "музыку не вернули"
    assert ("playerctl", "-p", "vlc", "play") not in machine, \
        "включили то, что человек сам выключил вечером"
    assert not server.state(), "состояние осталось на диске: режим «включён» уже после выключения"


def test_the_watchdog_returns_the_machine_but_not_the_music(machine) -> None:
    """Сторож срабатывает по сроку, а не потому, что человек пришёл: музыку включать некому."""
    server.on("ночная работа")
    machine.clear()

    out = server.off(resume=False)

    assert ("kscreen-doctor", "--dpms=on") in machine, "экраны так и остались тёмными"
    assert "resumed" not in out, "музыка заиграла сама, в пустой комнате"


def test_turning_it_off_works_even_when_nobody_remembers_it_was_on(machine) -> None:
    """После перезагрузки или сорванной работы файла состояния нет, а экран включать всё равно надо."""
    out = server.off()
    assert out["ok"] and ("kscreen-doctor", "--dpms=on") in machine


def test_the_state_file_must_survive_being_read_back(machine) -> None:
    """Состояние читается другим процессом (`justday server status`, сторож) — значит это JSON."""
    server.on("ночная работа")
    saved = json.loads(server.STATE.read_text(encoding="utf-8"))
    assert saved["on"] and saved["guard"] == 4242 and saved["paused"] == ["spotify", "firefox"]
    assert server.status()["on"] and server.status()["hours_left"] > 9


def test_anyone_who_walks_up_to_the_machine_must_be_asked_for_a_password(machine) -> None:
    """Он подошёл, подвигал мышью — и всё заработало: режим сервера никого не спрашивал.

    Замок ставится **последним**: запереть сеанс раньше — значит не успеть ни погасить экраны, ни
    перейти на свой рабочий стол.
    """
    out = server.on("человек ушёл")

    assert out["locked"], "сеанс не заперт: подошедший сядет за чужую работу"
    order = [c for c in machine if c[0] in ("kscreen-doctor", "loginctl")]
    assert order[-1][:2] == ("loginctl", "lock-session"), \
        "заперлись раньше, чем погасили экраны, — остальное сделать уже некому"


def test_coming_back_for_a_minute_must_not_leave_the_machine_open(machine) -> None:
    """Вернулся, подвигал мышью, снова ушёл — экраны должны погаснуть и замок встать заново."""
    server.on("человек ушёл")
    machine.clear()

    again = server.on("человек ушёл")

    assert again["already"] and again["screens_off"] and again["locked"], \
        "второе «включить» ответило «уже включено» и оставило машину открытой"
