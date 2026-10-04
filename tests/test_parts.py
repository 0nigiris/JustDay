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
    """Значок при переносе метался между местами и ложился поверх соседа.

    Место значка мерили по живой полосе, а полоса в это время жила своей жизнью: под курсором
    росло увеличение, соседи разъезжались, граница между ячейками уезжала — и порядок защёлкивало
    туда-сюда на каждом кадре. Лечится это одним: пока значок в руке, полоса стоит. Поэтому тест
    проверяет не формулу, а то, что во время жеста ничего живого под руку не попадает.
    """
    import pathlib
    import re

    qml = pathlib.Path("island/DockView.qml").read_text(encoding="utf-8")
    move = re.search(r"function moveDrag\(sceneX\) \{(.+?)\n    \}", qml, re.S)
    assert move, "правило перестановки пропало"
    body = move.group(1)
    assert "dragBase" in body, "место значка снова меряют по живой полосе — она едет под рукой"
    assert not re.search(r"\bgeom\[", body), "в перестановку вернулась живая геометрия: будет дребезг"
    phys = re.search(r"function stepPhysics\(dt\) \{(.+?)\n    \}", qml, re.S)
    assert phys, "шаг физики пропал"
    assert re.search(r'dragKey\s*!==\s*""', phys.group(1)), \
        "пружина увеличения снова работает во время жеста — полоса поедет под рукой"
    assert re.search(r"function startDrag\(\w+\) \{(?:.|\n)+?dragBase = ", qml), \
        "геометрию перестали замораживать в начале жеста"


def test_jarvis_answered_that_there_was_nothing_to_grab_the_screen_with() -> None:
    """«Нечем снять экран» — и ради снимка Джарвис перезапустил kwin, убив сессию."""
    import inspect
    import pathlib
    import py_compile

    from justday import cli, desktop

    src = inspect.getsource(desktop.capture_screen)
    assert "portal_shot.py" in src, "путь через портал пропал — снимать на KWin снова нечем"
    assert "spectacle" not in src.lower().split('"""')[-1], "spectacle вернулся в снимки: он падает в KCrash"
    helper = pathlib.Path(desktop.__file__).with_name("portal_shot.py")
    assert helper.exists(), "помощник для портала пропал"
    py_compile.compile(str(helper), doraise=True)
    assert "capture_screen" in inspect.getsource(cli._capture), "у CLI снова свой список средств — разойдутся"


def test_the_brain_restarted_the_window_manager_and_killed_the_session() -> None:
    """Джарвис сделал killall kwin_wayland — стол умер вместе с окнами человека."""
    import json
    import pathlib

    rules = json.loads(pathlib.Path("brain/settings.json").read_text(encoding="utf-8"))["permissions"]
    assert "Bash(killall:*)" in rules["ask"] and "Bash(pkill:*)" in rules["ask"], \
        "мозг снова может убить kwin без спроса, а ночью — вообще молча"
    persona = pathlib.Path("brain/PERSONA.md").read_text(encoding="utf-8")
    assert "kwin_wayland" in persona, "в правилах мозга не сказано, что перезапуск стола убивает сессию"


def test_the_dock_was_empty_right_after_the_computer_was_turned_on(monkeypatch) -> None:
    """Включил компьютер — док без значков, и помогал только перезапуск оболочки.

    Список программ кешировался на тридцать секунд по time.monotonic(), а она считает секунды
    с загрузки системы. Пустой начальный кеш с отметкой 0.0 первые полминуты выглядел свежим:
    list_apps() отдавал пустоту, не читая ни одного .desktop, и каталог дока сохранялся без
    закреплённых значков — ровно в то время, когда стол и поднимается.
    """
    from justday import desktop

    monkeypatch.setattr(desktop, "_apps_cache", None)
    monkeypatch.setattr(desktop.time, "monotonic", lambda: 5.0)
    assert desktop.list_apps(), "сразу после загрузки список программ снова пуст"


def test_flatpak_programs_did_not_start_from_the_dock(monkeypatch, tmp_path) -> None:
    """Щелчок по значку flatpak-программы не делал ничего: gtk-launch отвечал «no such application».

    У обычной программы id — это имя файла без суффикса (firefox → firefox.desktop). У flatpak id
    сам кончается на .desktop (com.ayugram.desktop), а файл называется com.ayugram.desktop.desktop.
    Проверка «кончается на .desktop» тут врёт, и gtk-launch искал файл, которого нет.
    """
    from justday import desktop

    (tmp_path / "com.ayugram.desktop.desktop").write_text("[Desktop Entry]\n", encoding="utf-8")
    (tmp_path / "firefox.desktop").write_text("[Desktop Entry]\n", encoding="utf-8")
    monkeypatch.setattr(desktop, "_app_dirs", lambda: [tmp_path])
    assert desktop._gtk_name("com.ayugram.desktop") == "com.ayugram.desktop.desktop"
    assert desktop._gtk_name("firefox") == "firefox.desktop"


def test_the_top_strip_was_polling_the_network_even_when_it_was_not_shown() -> None:
    """Сеть, VPN и Bluetooth опрашивались тремя программами каждые пять секунд круглые сутки.

    Пятьдесят тысяч запусков в день ради значка, который меняется раз в час, — и это при любом
    виде верхней полосы, даже когда правого края у неё нет вовсе (островок, вырез).
    """
    import pathlib
    import re

    jd = pathlib.Path("island/JD.qml").read_text(encoding="utf-8")
    probe = re.search(r"readonly property bool linksWanted:([^\n]+)", jd)
    assert probe, "условие «есть кому показывать» пропало — опрос снова идёт всегда"
    assert 'islandStyle === "bar"' in probe.group(1), "опрос не привязан к сплошной полосе"
    timer = re.search(r"Timer \{\s*interval: (\d+)\s*running: jd\.linksWanted", jd, re.S)
    assert timer and int(timer.group(1)) >= 15000, "опрос снова чаще раза в пятнадцать секунд"


def test_the_island_showed_music_only_to_those_who_use_spotify() -> None:
    """У друга плеер в полоске пустовал: источник был жёстко вписанным Spotify.

    Полоска искала среди MPRIS имя или desktop entry со словом «spotify» и больше ничего не
    признавала музыкой — YouTube в браузере, VLC и местный плеер для неё не существовали.
    Карточка при этом брала первого попавшегося, так что полоска и карточка показывали разное.
    """
    import pathlib

    jd = pathlib.Path("island/JD.qml").read_text(encoding="utf-8")
    shell = pathlib.Path("island/shell.qml").read_text(encoding="utf-8")
    assert "readonly property var musicPlayer:" in jd, "общий выбор источника музыки пропал"
    assert "playerPrefer" in jd and "playerIgnore" in jd, "порядок и запреты источников пропали"
    peek = shell.split("component PeekView:", 1)[1].split("component ", 1)[0]
    assert "JD.musicPlayer" in peek, "полоска перестала брать общий источник"
    assert "Mpris.players" not in peek, "полоска снова разбирает список MPRIS сама, мимо общего выбора"
    expanded = shell.split("component ExpandedView:", 1)[1].split("component ", 1)[0]
    assert "JD.musicPlayer" in expanded, "карточка перестала брать общий источник"


def test_the_player_could_not_be_turned_off_where_it_was_not_wanted() -> None:
    """Один хочет трек всегда, другому он мешает в свёрнутом виде и нужен только в раскрытом."""
    import pathlib

    from justday import config

    island = config.DEFAULTS["island"]
    for key in ("player_peek", "player_expanded", "player_prefer", "player_ignore"):
        assert key in island, f"настройка {key} пропала"
    assert island["player_prefer"] == ["spotify"], "порядок источников по умолчанию изменился молча"
    settings = pathlib.Path("island/SettingsView.qml").read_text(encoding="utf-8")
    for key in ("island.player_peek", "island.player_expanded", "island.player_prefer", "island.player_ignore"):
        assert key in settings, f"{key} нечем включить в окне настроек"


def test_the_dock_and_the_tray_sometimes_forgot_to_hide() -> None:
    """Иногда док и лоток просто оставались на экране и не прятались до перезапуска оболочки.

    Весь уход за край держался на том, что придёт событие «курсор ушёл с полосы». Оно приходит
    не всегда: курсор уходит в чужое окно, поверхность пересоздаётся, маска меняется. После
    потерянного события полоса считала, что рука всё ещё на ней, и прятать её было некому.
    """
    import pathlib

    shell = pathlib.Path("island/shell.qml").read_text(encoding="utf-8")
    edge = pathlib.Path("island/EdgeReveal.qml").read_text(encoding="utf-8")
    assert shell.count('property: "bodyHovered"') == 2, \
        "наведение на док и лоток снова держится на одном событии, без связки"
    assert "id: watchdog" in edge, "сторож за забытым прятаньем пропал"


def test_a_magnified_icon_kept_peeking_out_after_the_dock_hid() -> None:
    """Ведёшь рукой вверх медленно — док уезжает, а поднятый значок с подписью торчит из-за края.

    Док прятался на высоту карточки, но над карточкой живёт запас под увеличение, и значок под
    курсором в него поднимается. На эту разницу он и выглядывал.
    """
    import pathlib
    import re

    shell = pathlib.Path("island/shell.qml").read_text(encoding="utf-8")
    away = re.search(r"const away = dockHost\.atTop \? ([^\n]+)", shell)
    assert away, "правило ухода дока за край пропало"
    assert "cardHeight" not in away.group(1), "док снова уезжает на высоту карточки, а не вида"


def test_spamming_a_dock_icon_answered_with_open_wait_close_wait() -> None:
    """Быстрые щелчки по значку шли рвано: откроется, подождёт, закроется, подождёт.

    Список окон приходит от демона по сокету, и между щелчком и ответом проходит кадр-другой.
    Второй щелчок попадал ровно в эту щель: он видел прежнее состояние и сворачивал уже
    свёрнутое или поднимал уже поднятое. Своё намерение теперь помнится полсекунды — этого
    хватает демону ответить и мало, чтобы разойтись с правдой.
    """
    import pathlib

    qml = pathlib.Path("island/DockView.qml").read_text(encoding="utf-8")
    assert "function remember(id, minimized)" in qml, "память о своём намерении пропала"
    grouped = qml.split("readonly property var grouped:", 1)[1].split("\n    readonly property", 1)[0]
    assert "mine[String(w.id)]" in grouped, "намерение больше не перекрывает ответ демона"
    press = qml.split("function press(e, wins)", 1)[1].split("\n    function ", 1)[0]
    assert press.count("dv.remember(") == 2, "щелчок перестал запоминать, что он сделал с окном"
