"""Необязательные части: что считается установленным и какая команда это меняет."""
from justday import parts


def test_every_part_has_a_size_and_a_reason():
    for name, part in parts.PARTS.items():
        assert part.name == name
        assert part.size.startswith("~")
        assert part.what and part.without


def test_have_checks_the_module_not_the_settings(monkeypatch):
    monkeypatch.setattr(parts.importlib.util, "find_spec", lambda mod: object() if mod == "torch" else None)
    assert parts.have("voice")
    assert not parts.have("speech")
    assert not parts.have("нет такой части")


def test_suggested_asks_for_cuda_only_with_an_nvidia_card(monkeypatch):
    monkeypatch.setattr(parts, "gpu", lambda: False)
    assert parts.suggested() == ["speech", "voice"]
    monkeypatch.setattr(parts, "gpu", lambda: True)
    assert parts.suggested() == ["speech", "voice", "cuda"]


def test_add_keeps_what_is_already_there(monkeypatch):
    monkeypatch.setattr(parts, "installed", lambda: ["speech"])
    ok, cmd = parts.sync(add=("voice",), dry=True)
    assert ok and cmd.endswith("--extra speech --extra voice")   # порядок как в PARTS, а не как в аргументах


def test_remove_drops_only_the_named_part(monkeypatch):
    monkeypatch.setattr(parts, "installed", lambda: ["speech", "voice", "cuda"])
    ok, cmd = parts.sync(drop=("cuda",), dry=True)
    assert ok and "--extra cuda" not in cmd and "--extra speech" in cmd and "--extra voice" in cmd


def test_unknown_part_is_refused_before_anything_runs(monkeypatch):
    monkeypatch.setattr(parts, "installed", lambda: [])
    ok, why = parts.sync(add=("gpu",))
    assert not ok and "gpu" in why


def test_missing_note_tells_the_command(monkeypatch):
    assert "justday parts add speech" in parts.missing_note("speech")


def test_the_usb_stick_was_built_without_anything_to_run() -> None:
    """Флешка собиралась и не запускалась: окружения на ней не было вовсе.

    Запускалка звала `app/.venv/bin/justday`, а сборка его не делала — и на чужом компьютере
    скрипт умирал первой же строкой. Собрать venv прямо на флешке тоже нельзя: он заводит ссылку
    lib64 → lib, а флешки обычно в exfat, где ссылок не бывает («Operation not permitted»).
    Поэтому нужное ставится в обычную папку рядом.
    """
    from justday import portable

    assert ".venv" not in portable.SCRIPT, "запускалка снова зовёт окружение, которого нет"
    assert "--target" in portable.SCRIPT, "нужное ставится не в папку — на exfat это не заведётся"
    assert "PYTHONPATH" in portable.SCRIPT, "поставленное некуда подключить"
    assert "PIP_CACHE_DIR" in portable.SCRIPT, "кэш установки остался бы на чужой машине следом"


def test_the_tray_icon_could_not_bring_back_a_minimized_window() -> None:
    """Telegram пропал совсем: значок в лотке есть, окна нет, войти некуда.

    Программа честно получала Activate и честно пыталась показать себя — но под Wayland поднять
    своё окно может только тот, у кого фокус, а фокус был у островка. Поэтому после activate()
    окно поднимаем мы сами, через KWin. Две вещи при этом нельзя потерять:

    * значок и окно зовутся по-разному («TelegramDesktop» против «org.telegram.desktop») — без
      сведения имён мы не найдём то самое окно;
    * поднимать можно только **свёрнутое**: если программа щелчком по значку сама спрятала окно,
      вернуть его нашими руками — значит отнять у значка право прятать.
    """
    import json

    from justday import desktop

    js = desktop._KWIN_JS % {"query": json.dumps("telegramdesktop"), "action": json.dumps("wake"),
                             "tag": json.dumps("T "), "wid": json.dumps("")}
    assert "squash" in js, "имена сравниваются буква в букву — значок своего окна не найдёт"
    assert 'action === "wake" && !w.minimized' in js, \
        "wake хватает любое окно: программа больше не может спрятать себя щелчком по значку"


def test_free_rungs_were_silently_dropped_from_the_ladder() -> None:
    """Бесплатные модели OpenCode лестница считала ступенями «нечем войти» и выбрасывала.

    Ключа им не нужно вовсе — они отвечают без всякого входа, — но проверка смотрела только на
    местных поставщиков и на имена из связки ключей. В итоге человек ставил бесплатную ступень,
    а работа после кончившейся подписки всё равно падала сразу на платную.
    """
    from justday import shell

    live = [r for r in ("opencode/nemotron-3.5-lightning-free", "ollama/qwen3.5:9b")
            if r.split("/", 1)[0] in shell.LOCAL | shell.FREE]
    assert len(live) == 2, "бесплатная ступень снова считается недоступной"


def test_the_dock_tip_printed_the_app_name_twice() -> None:
    """Подсказка показывала «Equibop», а под ней списком снова «Equibop».

    Список окон под именем программы существует, чтобы сказать что-то новое: какое окно открыто и
    не свёрнуто ли оно. У Equibop, Discord и десятка других единственное окно называется ровно так
    же, как сама программа, — и подсказка повторяла имя само под собой.
    """
    import pathlib
    import re

    qml = pathlib.Path("island/DockView.qml").read_text(encoding="utf-8")
    adds = re.search(r"readonly property bool winListAdds: \{(.+?)\n        \}", qml, re.S)
    assert adds, "правило «список должен добавлять новое» пропало из подсказки"
    body = adds.group(1)
    assert "minimized" in body, "свёрнутое окно перестало считаться новостью — пометка пропадёт"
    assert "plain(text)" in body, "имя окна снова сравнивается с именем программы как попало"
    assert "wins.length !== 1" in body, "несколько окон должны перечисляться всегда"


def test_the_dock_tip_hung_over_a_dragged_icon() -> None:
    """Значок несли рукой, а подпись называла соседа и висела не над ним."""
    import pathlib
    import re

    qml = pathlib.Path("island/DockView.qml").read_text(encoding="utf-8")
    want = re.search(r"property bool want: dv\.labelMode(.+?)readonly property string text", qml, re.S)
    assert want, "условие показа подписи пропало"
    assert 'dv.dragKey === ""' in want.group(1), "подпись снова всплывает во время перетаскивания"
    start = re.search(r"function startDrag\(key\) \{(.+?)\n    \}", qml, re.S)
    assert start and "tipShown = false" in start.group(1), "взяли значок — старая подпись осталась висеть"


def test_jarvis_kept_retelling_the_inbox_instead_of_opening_a_letter() -> None:
    """«Открой это письмо в браузере» — а он снова пересказывал ящик."""
    import inspect

    from justday import mail

    src = inspect.getsource(mail.MailAssistant.handle)
    assert 'if action == "not_mail":' in src, "not_mail снова проверяет слова о почте и глотает чужую просьбу"
    assert 'if action == "open":' in src, "команды «открой письмо» в дорожке опять нет"
    assert "open" in mail.INTENT_PROMPT, "местная модель не знает про «открой» — вернёт not_mail"
    letter = mail.Letter("1", "Spotify", "no-reply@spotify.com", "Код", "", "", "<abc@spotify.com>")
    link = mail.web_link(letter)
    assert link == "" or "rfc822msgid:abc%40spotify.com" in link, "ссылка на письмо в вебе собрана неверно"


def test_icons_jumped_under_the_hand_while_being_dragged() -> None:
    """Значок при переносе метался между местами и ложился поверх соседа."""
    import pathlib
    import re

    qml = pathlib.Path("island/DockView.qml").read_text(encoding="utf-8")
    move = re.search(r"function moveDrag\(sceneX\) \{(.+?)\n    \}", qml, re.S)
    assert move, "правило перестановки пропало"
    body = move.group(1)
    assert "hole" in body, "порядок снова меряют по соседу, а не по собственной дырке — будет дребезг"
    assert "0.18" in body, "запас на границе пропал: шаг защёлкает от дрожи руки"
    assert "for (let pass" in body, "шаг перестал повторяться — быстрый рывок значок не догонит"
    assert "readonly property real carried:" in qml, "значок в руке снова улетает из своей дырки на соседа"
