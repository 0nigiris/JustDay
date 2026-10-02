"""Панель инструментов: эмодзи, буфер обмена, нагрузка.

Главное здесь — не «список показался», а две вещи, которые ломаются молча: поиск по-русски (склонение
и ё) и то, что пароли в историю буфера не попадают.
"""
from __future__ import annotations

import json

import pytest

from justday import clipboard, glyphs, sysload

# ──────────────────────────────── эмодзи ────────────────────────────────


def test_the_set_is_there_and_grouped() -> None:
    got = glyphs.load()
    assert len(got["items"]) > 1500                       # 1923 на Unicode 18
    assert "Лица" in got["groups"] and "Флаги" in got["groups"]
    assert all({"c", "n", "g"} <= set(i) for i in got["items"][:50])


@pytest.mark.parametrize(
    ("query", "expect"),
    [("кот", "🐱"), ("кошка", "🐈"), ("огонь", "🔥"), ("ракета", "🚀"), ("rocket", "🚀"),
     ("украина", "🇺🇦"), ("галочка", "✔️"), ("думаю", "🤔")],
)
def test_search_finds_the_obvious_thing(query: str, expect: str) -> None:
    assert expect in [i["c"] for i in glyphs.search(query, limit=8)]


def test_russian_declension_does_not_break_the_search() -> None:
    """CLDR пишет «Российская Федерация», а человек ищет «россия» — и это должно находиться."""
    assert "🇷🇺" in [i["c"] for i in glyphs.search("россия", limit=8)]
    assert "😻" in [i["c"] for i in glyphs.search("кот сердце", limit=8)]     # оба слова, не одно


def test_e_and_yo_are_one_letter() -> None:
    assert glyphs.search("самолёт", limit=3)[0]["c"] == glyphs.search("самолет", limit=3)[0]["c"]


def test_an_exact_name_beats_a_mention_in_the_keywords() -> None:
    """«rocket» — это ракета, а не космонавт, у которого это слово в описании."""
    assert glyphs.search("rocket", limit=1)[0]["c"] == "🚀"


def test_every_word_of_the_query_must_match() -> None:
    assert glyphs.search("кот вертолёт", limit=5) == []


def test_recents_come_first_and_survive(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(glyphs, "RECENT_FILE", tmp_path / "recent.json")
    monkeypatch.setattr(glyphs.config, "STATE_DIR", tmp_path)
    glyphs.remember("🦀")
    glyphs.remember("🐱")
    assert glyphs.recents()[:2] == ["🐱", "🦀"]           # последний взятый — первым
    assert [i["c"] for i in glyphs.search(limit=2)] == ["🐱", "🦀"]
    glyphs.remember("🦀")                                  # повтор поднимает, а не задваивает
    assert glyphs.recents()[:2] == ["🦀", "🐱"]


# ─────────────────────────── буфер обмена ───────────────────────────


@pytest.fixture
def store(tmp_path, monkeypatch):
    """История в отдельном каталоге: тест не должен трогать настоящую."""
    monkeypatch.setattr(clipboard.config, "STATE_DIR", tmp_path)
    monkeypatch.setattr(clipboard, "STORE", tmp_path / "clipboard.jsonl")
    monkeypatch.setattr(clipboard, "BLOBS", tmp_path / "clipboard")
    monkeypatch.setattr(clipboard, "PAUSE_FLAG", tmp_path / "paused")
    monkeypatch.setattr(clipboard, "SKIPPED", tmp_path / "skipped.json")
    return tmp_path


@pytest.mark.parametrize(
    "secret",
    ["sk-ant-api03-AbCdEf1234567890xyzAbCdEf1234567890", "ghp_1234567890abcdefghij",
     "AKIAIOSFODNN7EXAMPLE", "xoxb-123456789012-abcdefghijkl",
     "-----BEGIN OPENSSH PRIVATE KEY-----\nabc",
     "l0v3m3htem3", "Tr0ub4dor&3"],
)
def test_secrets_never_reach_the_disk(store, secret: str) -> None:
    assert clipboard.store(secret)["ok"] is False
    assert clipboard.items() == []
    assert not clipboard.STORE.exists() or secret not in clipboard.STORE.read_text(encoding="utf-8")


@pytest.mark.parametrize(
    "ordinary",
    ["обычный текст на русском", "https://github.com/0nigiris/JustDay", "fixkraftmine@gmail.com",
     "~/.config/justday/config.toml", "v2.14.3", "justday clip wipe",
     "8c41a38f2b1e4d6c9a0b3e5f7d8c1a2b3c4d5e6f"],
)
def test_ordinary_things_are_remembered(store, ordinary: str) -> None:
    """Хеш коммита, путь и ссылку копируют постоянно — забывать их было бы вредительством."""
    assert clipboard.store(ordinary)["ok"] is True
    assert clipboard.items()[0]["preview"].startswith(ordinary[:40])


def test_skipped_ones_are_counted_so_the_gap_is_explainable(store) -> None:
    assert clipboard.skipped()["count"] == 0
    clipboard.store("Tr0ub4dor&3")
    clipboard.store("ghp_1234567890abcdefghij")
    assert clipboard.skipped()["count"] == 2


def test_the_same_text_rises_instead_of_piling_up(store) -> None:
    clipboard.store("первое")
    clipboard.store("второе")
    clipboard.store("первое")
    assert [i["preview"] for i in clipboard.items()] == ["первое", "второе"]


def test_pause_stops_remembering(store) -> None:
    clipboard.pause(True)
    assert clipboard.store("пока на паузе")["why"] == "пауза"
    clipboard.pause(False)
    assert clipboard.store("а теперь пишем")["ok"] is True


def test_forget_and_wipe(store) -> None:
    clipboard.store("один")
    clipboard.store("два")
    assert clipboard.forget("1") is True                 # по номеру в списке
    assert [i["preview"] for i in clipboard.items()] == ["один"]
    assert clipboard.wipe() == 1
    assert clipboard.items() == []


def test_search_in_the_history(store) -> None:
    clipboard.store("письмо про отпуск")
    clipboard.store("совсем другое")
    assert [i["preview"] for i in clipboard.items(query="отпуск")] == ["письмо про отпуск"]


def test_the_file_is_readable_only_by_its_owner(store) -> None:
    clipboard.store("что-то своё")
    assert clipboard.STORE.stat().st_mode & 0o077 == 0


def test_the_list_carries_previews_not_whole_texts(store) -> None:
    """Список рисуется строкой-предпросмотром: целиком текст нужен только в момент вставки, и
    незачем разносить его по журналам и по памяти островка."""
    clipboard.store("ы" * 5000)
    row = clipboard.items()[0]
    assert len(row["preview"]) <= clipboard.PREVIEW + 1
    assert "text" not in row and row["size"] == 5000


def test_the_watcher_knows_what_to_run() -> None:
    """На Wayland следит wl-paste, на X11 демон опрашивает сам."""
    argv = clipboard.watch_argv()
    assert argv == [] or all(cmd[0] == "wl-paste" and "--watch" in cmd for cmd in argv)


# ──────────────────────────── нагрузка ────────────────────────────


def test_memory_reads_like_the_system_reports_it() -> None:
    mem = sysload.memory()
    assert mem["total"] > 0 and 0 <= mem["percent"] <= 100
    assert mem["used"] + mem["avail"] <= mem["total"] + 1     # округление до мегабайта


def test_the_first_look_admits_it_has_nothing_to_compare_with() -> None:
    """Процент процессора — разность двух взглядов. Первый честно отдаёт нули, а не выдумывает."""
    load = sysload.Load()
    first = load.cpu()
    assert first["percent"] == 0.0 and first["count"] >= 1
    assert all(c == 0.0 for c in first["cores"])


def test_a_second_look_gives_real_numbers() -> None:
    load = sysload.Load()
    load.snapshot()
    busy = sum(i * i for i in range(400_000))                  # чем-то занять процессор
    snap = load.snapshot()
    assert busy > 0
    assert 0 <= snap["cpu"]["percent"] <= 100
    assert len(snap["cpu"]["cores"]) == snap["cpu"]["count"]
    assert snap["top"] and all({"pid", "name", "cpu", "mem_mb"} <= set(p) for p in snap["top"])


def test_one_line_for_voice_and_journal() -> None:
    load = sysload.Load()
    load.snapshot()
    line = sysload.human_summary(load.snapshot())
    assert "процессор" in line and "память" in line


def test_the_snapshot_is_json_and_nothing_more() -> None:
    """Снимок уходит островку и ассистенту по сокету: всё в нём должно быть простыми значениями."""
    load = sysload.Load()
    load.snapshot()
    assert json.loads(json.dumps(load.snapshot()))


def test_disks_are_listed_once_each() -> None:
    """На btrfs `/` и `/home` живут на одном устройстве — показывать место дважды нельзя."""
    got = sysload.disks()
    assert len({(d["total_gb"], d["free_gb"], d["percent"]) for d in got}) == len(got)


# ──────────────────────────── лаунчер ────────────────────────────


@pytest.fixture
def apps(monkeypatch, tmp_path):
    """Выдуманный набор программ: настоящий зависит от машины, на которой запустили проверку."""
    from justday import launcher

    monkeypatch.setattr(launcher, "RECENT_FILE", tmp_path / "recent.json")
    monkeypatch.setattr(launcher.config, "STATE_DIR", tmp_path)
    monkeypatch.setattr(launcher.desktop, "list_apps", lambda: [
        {"id": "discord", "name": "Discord", "name_ru": "", "generic": "Messenger",
         "keywords": "chat;vencord;", "icon": "discord"},
        {"id": "org.kde.konsole", "name": "Konsole", "name_ru": "Консоль", "generic": "Терминал",
         "keywords": "shell;terminal;", "icon": "utilities-terminal"},
        {"id": "code", "name": "Visual Studio Code", "name_ru": "", "generic": "Редактор",
         "keywords": "editor;", "icon": "code"},
    ])
    monkeypatch.setattr(launcher.desktop, "list_games", lambda: [
        {"source": "steam", "id": "570", "name": "Dota 2"},
    ])
    monkeypatch.setattr(launcher.desktop, "windows", lambda *a, **k: [])
    return launcher


def test_the_launcher_finds_by_name_and_by_russian_name(apps) -> None:
    assert apps.items("disc")[0]["name"] == "Discord"
    assert apps.items("консоль")[0]["name"] == "Консоль"
    assert apps.items("терминал")[0]["name"] == "Консоль"     # по описанию тоже


def test_games_are_in_the_same_list(apps) -> None:
    got = apps.items("dota")
    assert got and got[0]["kind"] == "game" and got[0]["id"] == "570"


def test_the_wrong_keyboard_layout_still_finds_it(apps) -> None:
    """«Вшысщкв» — это Discord, набранный не глядя на строку."""
    assert apps.items("Вшысщкв")[0]["name"] == "Discord"
    assert apps.swap_layout("Вшысщкв") == "Discord"
    assert apps.swap_layout("Discord") == "Вшысщкв"


def test_recently_launched_come_first(apps) -> None:
    assert apps.items("")[0]["name"] != "Visual Studio Code"   # по алфавиту первым не он
    apps.remember("app", "code")
    assert apps.items("")[0]["name"] == "Visual Studio Code"


def test_nothing_matches_means_nothing_and_not_noise(apps) -> None:
    """Пустой ответ — это сигнал островку предложить спросить ассистента, а не показать мусор."""
    assert apps.items("поставь таймер на десять минут") == []


# ──────────────────────── меню приложений ────────────────────────


def test_categories_pick_the_telling_label_not_the_first_one(apps) -> None:
    """Kate — это и Utility, и TextEditor, и Development. В меню она должна быть в одном месте."""
    from justday import launcher

    assert launcher.category_of("Qt;KDE;Utility;TextEditor;Development;") == "dev"
    assert launcher.category_of("Game;ActionGame;") == "games"
    assert launcher.category_of("Network;WebBrowser;") == "net"
    assert launcher.category_of("") == launcher.OTHER          # некуда — не «прочее» пустотой


def test_the_same_thing_is_not_listed_twice(apps) -> None:
    """Steam и flatpak кладут одну вещь и программой, и игрой: в меню должна остаться одна."""
    from justday import launcher

    apps.desktop.list_games = lambda: [{"source": "steam", "id": "570", "name": "Discord"}]
    names = [a["name"] for a in launcher.catalog()["apps"]]
    assert names.count("Discord") == 1
    assert next(a for a in launcher.catalog()["apps"] if a["name"] == "Discord")["kind"] == "app"


def test_pinning_survives_and_toggles(apps, tmp_path, monkeypatch) -> None:
    from justday import launcher

    monkeypatch.setattr(launcher, "FAV_FILE", tmp_path / "fav.json")
    assert launcher.pin("app", "code")["pinned"] is True
    assert launcher.favourites() == ["app:code"]
    assert launcher.pin("app", "code")["pinned"] is False       # то же нажатие снимает
    assert launcher.favourites() == []


def test_an_empty_favourites_page_shows_the_recent_ones(apps, tmp_path, monkeypatch) -> None:
    """Раздел, встречающий пустотой в первый день, человек больше не открывает."""
    from justday import launcher

    monkeypatch.setattr(launcher, "FAV_FILE", tmp_path / "fav.json")
    launcher.remember("app", "discord")
    assert launcher.catalog()["pinned"] == ["app:discord"]


# ──────────────────────── завершение сеанса ────────────────────────


@pytest.mark.parametrize("what", ["logout", "reboot", "poweroff"])
def test_losing_work_needs_saying_so_twice(what: str) -> None:
    """Запрет живёт в самой функции, а не в виде: кнопка может ошибиться, функция — нет."""
    from justday import session

    got = session.run(what)
    assert got["ok"] is False and got["confirm"] is True


def test_there_is_no_such_thing_as_a_made_up_action() -> None:
    from justday import session

    assert session.run("rm -rf /", confirm=True)["ok"] is False


# ──────────────────────── док ────────────────────────


@pytest.fixture
def docked(monkeypatch, tmp_path):
    """Тот же выдуманный набор программ, но с тем, чем док ловит открытые окна."""
    from justday import desktop, dock

    monkeypatch.setattr(dock.config, "STATE_DIR", tmp_path)
    monkeypatch.setattr(dock, "PIN_FILE", tmp_path / "dock.json")
    monkeypatch.setattr(desktop, "list_apps", lambda: [
        {"id": "org.kde.dolphin", "name": "Dolphin", "name_ru": "", "generic": "", "keywords": "",
         "icon": "system-file-manager", "categories": "System;FileManager;", "exec": "dolphin %u", "wmclass": ""},
        {"id": "steam", "name": "Steam", "name_ru": "", "generic": "", "keywords": "", "icon": "steam",
         "categories": "Game;", "exec": "/usr/bin/steam %U", "wmclass": "steam"},
        {"id": "burglin-gnomes", "name": "Burglin' Gnomes Demo", "name_ru": "", "generic": "", "keywords": "",
         "icon": "", "categories": "Game;", "exec": "steam steam://rungameid/1234", "wmclass": ""},
        {"id": "discord", "name": "Discord", "name_ru": "", "generic": "", "keywords": "", "icon": "discord",
         "categories": "Network;InstantMessaging;",
         "exec": "flatpak run --branch=stable com.discordapp.Discord", "wmclass": ""},
    ])
    monkeypatch.setattr(desktop, "list_games", lambda: [])
    return dock


def test_a_window_is_matched_to_the_app_that_owns_it(docked) -> None:
    """У окна есть только appId: «org.kde.dolphin» обязан превратиться в программу с именем и значком."""
    match = docked.catalog()["match"]
    assert match["org.kde.dolphin"]["name"] == "Dolphin"
    assert match["dolphin"]["name"] == "Dolphin"              # так окно зовут в половине случаев
    assert match["com.discordapp.discord"]["name"] == "Discord"   # обёртка flatpak, а не «flatpak»


def test_a_game_shim_does_not_steal_the_windows_of_its_launcher(docked) -> None:
    """Exec любой демки из библиотеки — «steam …». Без разделения проходов она забирала окна Steam."""
    assert docked.catalog()["match"]["steam"]["name"] == "Steam"


def test_an_untouched_dock_is_not_empty(docked) -> None:
    """Пустая полоса у края экрана — это не чистый лист, а поломка: по ней нечего нажать."""
    assert docked.catalog()["items"], "док в первый запуск обязан чем-то заполниться"


def test_pinning_keeps_the_order_things_were_pinned_in(docked) -> None:
    docked.pin("app", "discord", True)
    docked.pin("app", "steam", True)
    assert docked.pinned()[-2:] == ["app:discord", "app:steam"]
    assert docked.pin("app", "discord", False)["on"] is False
    assert "app:discord" not in docked.pinned()


def test_dragging_cannot_smuggle_in_something_that_was_not_pinned(docked) -> None:
    docked.pin("app", "discord", True)
    docked.arrange(["app:steam", "app:discord"])
    assert "app:steam" not in docked.pinned()
    assert "app:discord" in docked.pinned()


def test_dragging_one_icon_does_not_lose_the_others(docked) -> None:
    """Перестановка — это перестановка. Неполный список значит «остальные как были», а не
    «остальных больше нет»: иначе одно перетаскивание вычищает док."""
    docked.pin("app", "discord", True)
    was = docked.pinned()
    docked.arrange(["app:discord"])
    assert docked.pinned()[0] == "app:discord"
    assert sorted(docked.pinned()) == sorted(was)


def test_the_menu_icon_is_repainted_before_it_is_used(tmp_path, monkeypatch) -> None:
    """В темах такие значки нарисованы «цветом текста», и Qt его не разрешает: на тёмном доке
    получилось бы чёрное пятно вместо яблока."""
    from justday import dock

    theme = tmp_path / "icons" / "SomeTheme" / "places" / "scalable"
    theme.mkdir(parents=True)
    (theme / "start-here.svg").write_text('<svg><path fill="currentColor" d="M0 0"/></svg>', encoding="utf-8")
    monkeypatch.setattr(dock, "ICON_DIRS", (tmp_path / "icons",))
    monkeypatch.setattr(dock, "icon_theme", lambda: "SomeTheme")
    monkeypatch.setattr(dock.config, "STATE_DIR", tmp_path)
    monkeypatch.setattr(dock, "LAUNCHER_FILE", tmp_path / "launcher-icon.svg")

    got = dock.launcher_icon("apple")
    assert got, "значок не нашёлся в теме"
    assert "currentColor" not in (tmp_path / "launcher-icon.svg").read_text(encoding="utf-8")


def test_a_colour_icon_is_left_alone(tmp_path, monkeypatch) -> None:
    from justday import dock

    theme = tmp_path / "icons" / "SomeTheme" / "places" / "scalable"
    theme.mkdir(parents=True)
    src = theme / "start-here.svg"
    src.write_text('<svg><path fill="#ff0000" d="M0 0"/></svg>', encoding="utf-8")
    monkeypatch.setattr(dock, "ICON_DIRS", (tmp_path / "icons",))
    monkeypatch.setattr(dock, "icon_theme", lambda: "SomeTheme")
    assert dock.launcher_icon("apple") == str(src)


def test_the_grid_asks_for_no_file_at_all(monkeypatch) -> None:
    from justday import dock

    assert dock.launcher_icon("grid") == ""


def test_hiding_a_tray_icon_is_case_blind(tmp_path, monkeypatch) -> None:
    """Значки называют себя как попало: «Xwayland Video Bridge» и «xwayland video bridge» — одно."""
    from justday import config, dock

    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    config.set_value("tray", "hidden", [])
    dock.hide_tray("Blueman", True)
    assert "blueman" in dock.hidden_tray()
    assert dock.hide_tray("BLUEMAN", False)["on"] is False
    assert "blueman" not in dock.hidden_tray()


# ──────────────────────────── запасная модель ────────────────────────────
def test_limit_and_network_failures_are_told_apart() -> None:
    """Лимит и обрыв связи — разные беды: при лимите есть куда пойти, при обрыве некуда."""
    from justday import fallback

    assert fallback.looks_like_limit("Error 429: rate_limit_error, usage limit reached")
    assert fallback.looks_like_limit("insufficient credit")
    assert not fallback.looks_like_limit("connection refused")
    assert not fallback.looks_like_limit("Temporary failure in name resolution")
    # Сеть важнее: «429» внутри сообщения об обрыве не повод уходить к запасному, он в том же
    # интернете и упрётся туда же.
    assert not fallback.looks_like_limit("connection refused after 429 attempts")


def test_fallback_skips_providers_without_a_key(monkeypatch) -> None:
    """Предлагать переход, который тут же упрётся в «нет ключа», значит тратить попытку впустую."""
    from justday import fallback

    monkeypatch.setattr(fallback.providers, "secret_get", lambda name: "key" if name == "openrouter" else "")
    cfg = {"brain": {"provider": "claude", "fallbacks": ["deepseek", "openrouter", "ollama"]}}
    got = fallback.next_provider(cfg)
    assert got is not None and got[0] == "openrouter"


def test_fallback_does_not_offer_where_we_already_are(monkeypatch) -> None:
    from justday import fallback

    monkeypatch.setattr(fallback.providers, "secret_get", lambda name: "key")
    cfg = {"brain": {"provider": "openrouter", "fallbacks": ["openrouter", "ollama"]}}
    got = fallback.next_provider(cfg)
    assert got is not None and got[0] == "ollama"


def test_the_dispatcher_answers_without_a_local_model() -> None:
    """Местной модели может не быть вовсе — тогда решают правила, и они не должны молчать."""
    from justday import dispatch

    assert dispatch.level_for("открой дискорд", use_model=False)[0] == dispatch.LIGHT
    assert dispatch.level_for("напиши скрипт для переименования файлов", use_model=False)[0] == dispatch.STRONG
    assert dispatch.level_for("", use_model=False)[0] == dispatch.LIGHT
