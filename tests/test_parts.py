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


def test_the_chosen_emoji_never_typed_itself_on_plasma(monkeypatch) -> None:
    """Выбрал эмодзи — а он только в буфере: «вставьте Ctrl+V». Просили ровно обратного.

    Печатал его `wtype` через протокол виртуальной клавиатуры, а KWin такого протокола не даёт
    вовсе: «Compositor does not support the virtual keyboard protocol». То есть на Plasma 6
    символ не вставлялся сам никогда. Запасной путь — ydotool: он пишет в /dev/uinput, мимо
    композитора, и работает там, где виртуальная клавиатура запрещена.
    """
    from justday import face, glyphs

    monkeypatch.setattr(face, "session", lambda: "wayland")
    monkeypatch.setattr(glyphs.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(glyphs, "_ydotool_ready", lambda: True)
    ran: list[list[str]] = []

    class Done:
        returncode = 1          # wtype на KWin всегда так и отвечает

    class Ok:
        returncode = 0

    def fake_run(cmd, **kw):
        ran.append(cmd)
        return Ok() if cmd[0] == "ydotool" else Done()

    monkeypatch.setattr(glyphs.subprocess, "run", fake_run)
    ok, how = glyphs.type_out("😀")
    assert ok and how == "ydotool", "после отказа wtype запасного пути снова нет"
    assert [c[0] for c in ran] == ["wtype", "ydotool"], "порядок попыток изменился молча"


def test_server_mode_left_the_room_glowing(monkeypatch) -> None:
    """«Для человека выключен, для ассистента работает» — а клавиатура и мышь полыхали радугой.

    Тёмный экран при светящемся железе не даёт того, ради чего режим задуман: комната всё равно
    светится, ночью заметнее монитора. Гасим подсветку, а прежнюю картину возвращаем профилем
    OpenRGB — только он помнит режимы, скорости и цвета каждой зоны по отдельности.
    """
    import inspect

    from justday import config, server

    assert config.DEFAULTS["session"]["server_mode"]["leds_off"] is True, \
        "гашение подсветки пропало из настроек режима сервера"
    dark = inspect.getsource(server._dark)
    assert "leds_off" in dark, "режим сервера снова оставляет железо светиться"
    back = inspect.getsource(server.off)
    assert "_leds(True)" in back, "подсветку гасим, а вернуть забыли"
    leds = inspect.getsource(server._leds)
    assert "--save-profile" in leds, "прежнюю картину не сохраняем — возвращать будет нечего"
    assert leds.index("--save-profile") < leds.index('"--mode", "static"'), \
        "сохранение идёт после гашения: сохранится уже погасшее"


def _island_glyph():
    """JD.glyph() из островка, повторённый по его же таблицам: имя значка → файл svg или «» (искры)."""
    import pathlib
    import re

    jd = pathlib.Path("island/JD.qml").read_text(encoding="utf-8")
    table = re.search(r"readonly property var glyphs: \(\{(.+?)\}\)", jd, re.S).group(1)
    glyphs = dict(re.findall(r'"([^"]+)"\s*:\s*"([^"]+)"', table))
    local = set(re.findall(r'"([^"]+)"', re.search(r"localIcons: \[(.+?)\]", jd, re.S).group(1)))
    return lambda name: glyphs.get(name) or (name if name in local else "")


def test_mail_card_showed_sparkles_instead_of_its_own_icon() -> None:
    """«Иконки как будто не там»: шапка почты, календаря и вопроса рисовала запасные искры."""
    import pathlib
    import re

    from justday import island

    glyph = _island_glyph()
    shell = pathlib.Path("island/shell.qml").read_text(encoding="utf-8")
    header = re.search(r"CardHeader \{\s*Layout\.fillWidth: true\s*icon: (.+?)\n\s*tint:", shell, re.S).group(1)
    names = set(re.findall(r'[?:]\s*"([a-z0-9-]+)"', header)) | {"view-restore"}
    names |= {island.tool_icon(t, i) for t, i in [("Bash", "justday play x"), ("Bash", "git status"), ("Read", ""),
                                                  ("WebSearch", ""), ("Agent", ""), ("Skill", ""), ("Bash", "steam")]}
    for name in sorted(names):
        got = glyph(name)
        assert got and pathlib.Path(f"island/icons/{got}.svg").exists(), f"«{name}» рисуется запасными искрами"
    for svg in pathlib.Path("island/icons").glob("*.svg"):
        assert glyph(svg.stem) == svg.stem, f"значок {svg.stem} лежит в папке, но по имени его не найти"


def test_tapping_a_letter_showed_nothing_to_read() -> None:
    """Нажал на письмо — Джарвис начал читать вслух, а глазами посмотреть было нечего."""
    from justday import mail

    m = mail.MailAssistant()
    m.letters = [mail.Letter("1", "GitHub", "noreply@github.com", "", "", "Ваш доступ к репозиторию открыт. " * 40)]
    m.last_action = "summary"
    item = m.card("одно письмо")["items"][0]
    assert item["preview"].startswith("Ваш доступ к репозиторию открыт.")
    assert len(item["preview"]) <= 600, "в карточку ушло письмо целиком"
    assert item["address"] == "noreply@github.com", "кружку не от чего брать свой цвет"


def test_the_solid_bar_never_made_room_on_fedora(tmp_path, monkeypatch) -> None:
    """Распорка под сплошной полосой звала qdbus6, а в Fedora он зовётся qdbus-qt6: скрипт падал."""
    import importlib.util
    import shutil
    import subprocess
    import sys

    spec = importlib.util.spec_from_file_location("bar_strut", "island/bar_strut.py")
    strut = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(strut)
    calls = []
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setattr(shutil, "which", lambda n: "/usr/bin/qdbus-qt6" if n == "qdbus-qt6" else None)
    monkeypatch.setattr(subprocess, "run", lambda a, **k: calls.append(a) or subprocess.CompletedProcess(a, 0, "on 1 44", ""))
    monkeypatch.setattr(sys, "argv", ["bar_strut.py", "on", "44", "0", "0", "1"])
    assert strut.main() == 0
    assert calls and calls[0][0] == "/usr/bin/qdbus-qt6"


def test_island_crashed_at_start_in_the_icon_loader() -> None:
    """Островок через раз падал при запуске: значки темы грузились сразу из двух потоков."""
    import pathlib
    import re

    for f in pathlib.Path("island").glob("*.qml"):
        qml = f.read_text(encoding="utf-8")
        for img in re.finditer(r"Image \{(.+?)\n\s*\}", qml, re.S):
            body = img.group(1)
            themed = "iconPath(" in body or "themeImg.source" in body or "modelData.icon" in body
            if themed and "asynchronous:" in body:
                assert "asynchronous: true" not in body and "asynchronous: !ic.syncLoad" not in body, \
                    f"{f.name}: значок темы снова грузится в фоновом потоке"


def test_the_bar_cat_stood_still_and_told_no_numbers(monkeypatch) -> None:
    """Кошка на полосе не бежала, если кошку в доке выключили, и числа о памяти не было вовсе."""
    import asyncio
    import types

    from justday import daemon, sysload

    sent, ticks = [], iter(range(3))

    async def tick(_s):
        if next(ticks, None) is None:
            raise asyncio.CancelledError

    monkeypatch.setattr(daemon.asyncio, "sleep", tick)
    monkeypatch.setattr(sysload.Load, "cpu", lambda self: {"percent": 40.0})
    monkeypatch.setattr(sysload, "memory", lambda: {"percent": 63.0})
    monkeypatch.setattr(daemon.dock, "trash_full", lambda: False)
    me = types.SimpleNamespace(_subs={object()}, _trash_full=False, publish=lambda **m: sent.append(m),
                               cfg={"dock": {"cat": False}, "island": {"cat": True}})
    try:
        asyncio.run(daemon.Daemon._cpu_loop(me))
    except asyncio.CancelledError:
        pass
    assert {"cpu": 40.0, "mem": 63.0} in sent


def test_spotlight_jumped_down_and_flashed_while_closing() -> None:
    """Закрытый Spotlight на прощание уезжал вниз к доку и мигал сеткой программ (Hikisey).

    Проба в живом островке: до правки карточка в первые 50 мс после закрытия стояла на y=728
    вместо 96 и уже показывала полное меню. Режим поиска должен дожить до конца угасания.
    """
    import pathlib
    import re

    jd = pathlib.Path("island/JD.qml").read_text(encoding="utf-8")
    close = re.search(r"function closeMenu\(\) \{(.+?)\n    \}", jd, re.S).group(1)
    assert "menuOpen = false" in close
    assert "menuSearchMode" not in close, "закрытие снова переключает Spotlight в меню посреди угасания"
    assert "menuQuery" not in close, "закрытие снова стирает строку поиска посреди угасания"
    for opener in ("openMenu", "openSearch"):
        body = re.search(rf"function {opener}\(\) \{{(.+?)\n    \}}", jd, re.S).group(1)
        assert "menuSearchMode = " in body and 'menuQuery = ""' in body, f"{opener} не сбрасывает прошлый поиск"


def test_foreign_player_showed_the_browser_tab_title() -> None:
    """Плеер писал «natori - Absolute Zero - YouTube» — с хвостом сервиса и счётчиком вкладки."""
    import json
    import pathlib
    import re
    import shutil
    import subprocess

    import pytest

    node = shutil.which("node")
    if not node:
        pytest.skip("нет node, чтобы выполнить функцию островка")
    jd = pathlib.Path("island/JD.qml").read_text(encoding="utf-8")
    fn = re.search(r"(function cleanTitle\(s\) \{.+?\n    \})", jd, re.S).group(1)
    cases = {
        "natori - Absolute Zero - YouTube": "natori — Absolute Zero",
        "(2) natori - Absolute Zero - YouTube": "natori — Absolute Zero",
        "Kavinsky - Nightcall | SoundCloud": "Kavinsky — Nightcall",
        "Земфира - Хочешь? - Яндекс Музыка": "Земфира — Хочешь?",
        "Nightcall": "Nightcall",
        "AC-DC - Thunderstruck": "AC-DC — Thunderstruck",
        "": "",
    }
    js = fn + f"\nconsole.log(JSON.stringify({json.dumps(list(cases))}.map(cleanTitle)))"
    got = json.loads(subprocess.run([node, "-e", js], capture_output=True, text=True, check=True).stdout)
    assert dict(zip(cases, got)) == cases


def test_foreign_player_never_showed_its_cover() -> None:
    """Вместо обложки чужого плеера всегда была нота: к «file:///…» приклеивали второй file://."""
    import json
    import pathlib
    import re
    import shutil
    import subprocess

    import pytest

    node = shutil.which("node")
    if not node:
        pytest.skip("нет node, чтобы выполнить выражение островка")
    shell = pathlib.Path("island/shell.qml").read_text(encoding="utf-8")
    art = re.search(r"component Art: ClippingRectangle \{(.+?)\n    \}", shell, re.S).group(1)
    expr = re.search(r"id: artImg.+?\n\s*source: (.+?)\n", art, re.S).group(1)
    cases = {"file:///tmp/cover.png": "file:///tmp/cover.png", "/home/oni/a.jpg": "file:///home/oni/a.jpg",
             "https://i.ytimg.com/x.jpg": "https://i.ytimg.com/x.jpg", "": ""}
    js = f"console.log(JSON.stringify({json.dumps(list(cases))}.map(src => {{ const art = {{ src }}; return {expr} }})))"
    got = json.loads(subprocess.run([node, "-e", js], capture_output=True, text=True, check=True).stdout)
    assert dict(zip(cases, got)) == cases


def test_assistant_typed_into_the_lock_screen_password_field() -> None:
    """Пока сеанс заперт, «act type …» уходил экрану блокировки — то есть в поле пароля."""
    import pathlib
    import subprocess
    import textwrap

    import pytest

    tool = pathlib.Path.home() / ".local/share/uv/tools/kwin-mcp/bin/python"
    if not tool.exists():
        pytest.skip("kwin-mcp не установлен")
    probe = textwrap.dedent('''
        import asyncio, sys
        sys.path.insert(0, "plugin/bin")
        from kwin_mcp import server
        server.main = lambda: None
        server._engine.session_connect = lambda *a, **k: None
        import kwin_live as k

        class Engine:
            _session = None          # живой сеанс, не свой стол
            calls = []
            def __getattr__(self, name):
                return lambda *a, **kw: Engine.calls.append(name)

        server._engine = Engine()
        k._locked = lambda: True
        got = asyncio.run(k.act(["click 10 10", "type мойпароль", "key Return"]))
        assert Engine.calls == [], Engine.calls
        assert "заперт" in got[0] and "session_start" in got[0]
        assert "заперт" in asyncio.run(k.look())[0]

        # Ошибка logind не должна превращать неизвестное состояние в разрешение печатать.
        def unavailable(*args, **kwargs):
            raise OSError("logind недоступен")
        k.subprocess.run = unavailable
        assert k._locked(), "при сбое определения замка ввод был разрешён"
        print("ok")
    ''')
    out = subprocess.run([str(tool), "-c", probe], capture_output=True, text=True, timeout=60)
    assert out.stdout.strip().endswith("ok"), out.stderr[-1500:]
