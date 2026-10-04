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
    monkeypatch.setattr(launcher.filesearch, "search", lambda *a, **k: [])
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



def test_launcher_includes_files_from_index(apps, monkeypatch, tmp_path):
    """Меню ищет и файлы: недавние + лёгкий индекс, не только .desktop."""
    sample = [{"kind": "file", "id": str(tmp_path / "notes.txt"), "name": "notes.txt",
               "icon": "text-x-generic", "sub": str(tmp_path), "dir": False}]
    monkeypatch.setattr(apps.filesearch, "search",
                        lambda q, limit=24: sample if "note" in q.lower() else [])
    got = apps.items("notes")
    assert any(i["kind"] == "file" and i["name"] == "notes.txt" for i in got)


def test_launcher_opens_file_kind(apps, monkeypatch):
    monkeypatch.setattr(apps.filesearch, "open_path",
                        lambda path: {"ok": True, "kind": "file", "id": path, "name": "x"})
    assert apps.run("file", "/tmp/x")["ok"] is True


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
    monkeypatch.setattr(dock, "CATALOG_FILE", tmp_path / "dock-catalog.json")
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
        {"id": "octobrowser", "name": "Octo Browser", "name_ru": "", "generic": "", "keywords": "",
         "icon": "octobrowser", "categories": "Internet;",
         "exec": "env /home/x/OctoBrowser.AppImage", "wmclass": "octobrowser"},
    ])
    monkeypatch.setattr(desktop, "list_games", lambda: [])
    return dock


def test_a_window_is_matched_to_the_app_that_owns_it(docked) -> None:
    """У окна есть только appId: «org.kde.dolphin» обязан превратиться в программу с именем и значком."""
    match = docked.catalog()["match"]
    assert match["org.kde.dolphin"]["name"] == "Dolphin"
    assert match["dolphin"]["name"] == "Dolphin"              # так окно зовут в половине случаев
    assert match["com.discordapp.discord"]["name"] == "Discord"   # обёртка flatpak, а не «flatpak»



def test_octo_profile_windows_keep_separate_keys(docked) -> None:
    """Octo profiles (octium) share the Octo name/icon but must NOT hard-merge into one dock key."""
    match = docked.catalog()["match"]
    assert match["octobrowser"]["name"] == "Octo Browser"
    assert match["octium"]["name"] == "Octo Browser"
    assert match["octium"]["icon"] == match["octobrowser"]["icon"]
    assert match["octium"]["key"] != match["octobrowser"]["key"]
    assert "octium" in docked.catalog()["separate"]


def test_a_game_shim_does_not_steal_the_windows_of_its_launcher(docked) -> None:
    """Exec любой демки из библиотеки — «steam …». Без разделения проходов она забирала окна Steam."""
    assert docked.catalog()["match"]["steam"]["name"] == "Steam"


def test_an_untouched_dock_is_not_empty(docked) -> None:
    """Пустая полоса у края экрана — это не чистый лист, а поломка: по ней нечего нажать."""
    assert docked.catalog()["items"], "док в первый запуск обязан чем-то заполниться"


def test_a_restarting_dock_does_not_wait_for_a_fresh_desktop_scan(docked, monkeypatch) -> None:
    """После перезапуска оболочки отсутствие каталога не должно задерживать первый кадр дока."""
    from justday import dock

    monkeypatch.setattr(dock, "catalog", lambda: pytest.fail("синхронно разбирали приложения"))

    assert dock.catalog_cached() == {}


def test_a_saved_dock_catalog_is_the_first_frame_not_a_new_desktop_scan(docked, monkeypatch) -> None:
    """Сохранённые значки должны попасть в приветствие демона до обновления каталога."""
    import json

    from justday import dock

    dock.CATALOG_FILE.write_text(json.dumps({"items": [{"id": "firefox"}], "pinned": []}),
                                 encoding="utf-8")
    monkeypatch.setattr(dock, "catalog", lambda: pytest.fail("пересобрали сохранённый каталог"))

    assert dock.catalog_cached()["items"] == [{"id": "firefox"}]


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


def test_showing_tray_icon_clears_alias_family(tmp_path, monkeypatch) -> None:
    """Enabling Discord must clear both "discord" and "discord-tray" leftovers."""
    from justday import config, dock

    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "config.toml")
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    config.set_value("tray", "hidden", ["discord", "discord-tray", "xwayland video bridge"])
    got = dock.hide_tray("Discord", False, aliases=["discord", "Discord", "discord-tray"])
    assert got["on"] is False
    hidden = dock.hidden_tray()
    assert "discord" not in hidden
    assert "discord-tray" not in hidden
    assert "xwayland video bridge" in hidden


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


# ──────────────────────────── карта значков для эффекта ────────────────────────────
def test_the_same_icon_map_is_not_pushed_to_kwin_twice(tmp_path, monkeypatch) -> None:
    """Повтор той же карты — это два лишних вызова в очереди перед самим сворачиванием.

    Сворачивание значком просит «обнови карту наверняка» прямо перед тем, как свернуть окно. Пока
    на это каждый раз писался kwinrc и дёргался KWin по dbus, окно уезжало с задержкой, а при
    быстрых нажатиях задержки складывались и док переставал поспевать за рукой.
    """
    import subprocess

    from justday import desktop

    calls: list[list[str]] = []
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setattr(desktop.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(desktop, "qdbus_bin", lambda: "")
    monkeypatch.setattr(desktop.subprocess, "run",
                        lambda cmd, **kw: calls.append(list(cmd)) or subprocess.CompletedProcess(cmd, 0))
    monkeypatch.setattr(desktop, "_last_icons_json", "")
    monkeypatch.setattr(desktop, "_last_icons_applied", "")

    icons = {"app:discord": {"x": 10, "y": 20, "w": 48, "h": 48}}
    assert desktop.publish_dock_icons(icons, reconfigure=True)["ok"]
    assert len(calls) == 1, "первая карта должна дойти до KWin"
    assert desktop.publish_dock_icons(icons, reconfigure=True).get("skipped") is True
    assert len(calls) == 1, "та же карта второй раз — молча"

    # Значки переехали — это уже другая карта, её отдать надо.
    assert desktop.publish_dock_icons({"app:discord": {"x": 99, "y": 20, "w": 48, "h": 48}},
                                      reconfigure=True)["ok"]
    assert len(calls) == 2


def test_the_icon_map_file_was_rewritten_on_every_hover_tick(tmp_path, monkeypatch) -> None:
    """Док шлёт карту значков на каждый шаг наведения, и демон каждый раз переписывал один и тот же файл.
    Теперь файл пишется, только когда карта изменилась или файл пропал (Р-45)."""
    from justday import desktop

    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    monkeypatch.setattr(desktop.shutil, "which", lambda name: None)      # kwriteconfig6 не трогаем
    monkeypatch.setattr(desktop, "_last_icons_file", "")
    path = tmp_path / "justday-dock-icons.json"
    icons = {"app:discord": {"x": 10, "y": 20, "w": 48, "h": 48}}
    writes: list[str] = []
    real = type(path).write_text
    monkeypatch.setattr(type(path), "write_text", lambda self, text, **kw: writes.append(text) or real(self, text, **kw))

    desktop.publish_dock_icons(icons)
    desktop.publish_dock_icons(icons)
    assert len(writes) == 1, "та же карта записана дважды"
    desktop.publish_dock_icons({"app:discord": {"x": 11, "y": 20, "w": 48, "h": 48}})
    assert len(writes) == 2, "карта изменилась, а файл остался прежним"
    path.unlink()
    desktop.publish_dock_icons({"app:discord": {"x": 11, "y": 20, "w": 48, "h": 48}})
    assert path.exists(), "файл пропал, а карту не вернули"


# ──────────────────────────── лестница поставщиков ────────────────────────────
def test_the_ladder_starts_at_the_one_we_want_to_think_with(monkeypatch) -> None:
    """Наверху лестницы — основной, ниже запасные по порядку, и никто не повторяется дважды."""
    from justday import fallback

    cfg = {"brain": {"home_provider": "claude", "provider": "ollama",
                     "fallbacks": ["openrouter", "claude", "ollama"]}}
    assert fallback.ladder(cfg) == ["claude", "openrouter", "ollama"]


def test_we_climb_back_to_the_better_one_and_not_past_it(monkeypatch) -> None:
    """Снизу видно только тех, кто выше. Стоя наверху, подниматься некуда — и проверять нечего."""
    from justday import fallback

    monkeypatch.setattr(fallback.providers, "secret_get",
                        lambda name: "key" if name == "openrouter" else "")
    cfg = {"brain": {"home_provider": "claude", "provider": "ollama", "light_model": "haiku",
                     "fallbacks": ["openrouter", "ollama"], "fallback_models": {"openrouter": "free/model"}}}
    assert fallback.better_than(cfg) == ("claude", "haiku")

    cfg["brain"]["provider"] = "claude"
    assert fallback.better_than(cfg) is None


def test_a_provider_that_answers_with_a_limit_is_not_back_yet(monkeypatch, tmp_path) -> None:
    """Проверка должна верить ответу, а не коду возврата: «429» с нулевым кодом — это ещё лимит."""
    import subprocess

    from justday import fallback

    monkeypatch.setattr(fallback.shutil, "which", lambda name: "/usr/bin/claude")
    monkeypatch.setattr(fallback.providers, "env", lambda cfg: {})
    cfg = {"brain": {"claude_cli": "claude", "provider": "ollama", "model": "haiku"}}

    monkeypatch.setattr(fallback.subprocess, "run",
                        lambda *a, **kw: subprocess.CompletedProcess(a, 0, "usage limit reached", ""))
    assert fallback.probe(cfg, "claude", "haiku") is False

    monkeypatch.setattr(fallback.subprocess, "run",
                        lambda *a, **kw: subprocess.CompletedProcess(a, 0, "ok", ""))
    assert fallback.probe(cfg, "claude", "haiku") is True


def test_the_tiny_level_is_offered_only_when_there_is_a_tiny_model(monkeypatch) -> None:
    """Уровень, которого нет, предлагать нельзя: просьба ушла бы в никуда."""
    from justday import dispatch

    monkeypatch.setattr(dispatch.localllm, "available", lambda: True)
    monkeypatch.setattr(dispatch.localllm, "chat", lambda *a, **kw: "tiny")
    assert dispatch.level_for("который час", tiny=True)[0] == dispatch.TINY
    # Без крошечной модели тот же ответ судьи не должен превращаться в несуществующую ступень.
    assert dispatch.level_for("который час", tiny=False)[0] in (dispatch.LIGHT, dispatch.STRONG)


# ──────────────────────────── что он знает о себе ────────────────────────────
def test_he_is_told_only_about_what_is_switched_on() -> None:
    """Он не знал, что у него есть буфер обмена и эмодзи: ему про них никто не сказал.

    Список собирается из конфига, а не пишется руками, и выключенное пропадает из него само —
    иначе он начнёт обещать человеку то, чего у того нет.
    """
    from justday import config, persona

    cfg = config.DEFAULTS
    on = persona.abilities({**cfg, "dock": {**cfg["dock"], "enabled": True},
                            "clipboard": {**cfg["clipboard"], "history": 50}})
    assert "буфер" in on.lower()
    assert "Док:" in on

    off = persona.abilities({**cfg, "dock": {**cfg["dock"], "enabled": False},
                             "clipboard": {**cfg["clipboard"], "history": 0}})
    assert "буфер" not in off.lower(), "выключенный буфер остался в списке — он пообещает лишнее"
    assert "Док:" not in off

    # Язык человека: английскому незачем читать список по-русски.
    said = persona.abilities({**cfg, "user": {**cfg["user"], "language": "en"}})
    assert "Clipboard" in said or "Emoji" in said


# ──────────────────────────── дотянуться до человека ────────────────────────────
def test_the_letter_goes_out_even_when_the_phone_is_unreachable(monkeypatch) -> None:
    """Телефон может быть выключен или не в сети — и тогда письмо единственный след разговора.

    Поэтому письмо уходит всегда, а звонок — это добавка к нему, а не замена.
    """
    from justday import phone

    sent: list[tuple] = []
    monkeypatch.setattr(phone, "ring", lambda which="": (_ for _ in ()).throw(RuntimeError("не в сети")))
    monkeypatch.setattr(phone, "notify", lambda text, which="": (_ for _ in ()).throw(RuntimeError("не в сети")))
    import justday.mail as mail_mod
    monkeypatch.setattr(mail_mod, "send", lambda to, subject, body, **kw: sent.append((to, subject, body)))

    import justday.config as config_mod
    monkeypatch.setattr(config_mod, "load", lambda: {"mail": {"address": "oni@example.com"}})

    got = phone.reach("пора вынести мусор", urgent=True)
    assert got["ok"] is True
    assert sent and sent[0][0] == "oni@example.com"
    assert "ring_error" in got and "письмо" in got["sent"]


def test_ordinary_matters_do_not_ring(monkeypatch) -> None:
    """Ассистент, который звонит по каждому поводу, перестаёт звонить вовсе: его отключают."""
    from justday import phone

    rang: list[str] = []
    monkeypatch.setattr(phone, "ring", lambda which="": rang.append("да"))
    import justday.config as config_mod
    import justday.mail as mail_mod
    monkeypatch.setattr(mail_mod, "send", lambda *a, **kw: None)
    monkeypatch.setattr(config_mod, "load", lambda: {"mail": {"address": "oni@example.com"}})

    got = phone.reach("пришло письмо из банка")
    assert not rang, "обычное дело не должно звонить"
    assert got["sent"] == ["письмо"]


# ──────────────────────────── режим сервера ────────────────────────────
def test_server_mode_restores_what_it_changed(tmp_path, monkeypatch) -> None:
    """Режим, который не умеет выключаться обратно, — это сломанный компьютер, а не режим.

    Проверяем пару: включили — экраны погасли, звук заглох, сторож сна поднят; выключили — экраны
    зажглись, звук вернули, сторожа убили, след на диске убран.
    """
    from justday import server

    did: list[str] = []
    killed: list[int] = []
    monkeypatch.setattr(server, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(server, "_screens", lambda on: did.append(f"screens={'on' if on else 'off'}") or True)
    monkeypatch.setattr(server, "_mute", lambda on: did.append(f"mute={on}") or True)
    monkeypatch.setattr(server, "_keep_awake", lambda why: 4242)
    monkeypatch.setattr(server.os, "kill", lambda pid, sig: killed.append(pid))

    got = server.on("сборка")
    assert got["ok"] and "screens=off" in did and "mute=True" in did and got["guard"] == 4242
    assert server.status()["on"] is True

    back = server.off()
    assert back["ok"] and "screens=on" in did and "mute=False" in did
    assert killed == [4242], "сторож сна остался жить — машина никогда не уснёт"
    assert server.status()["on"] is False
    assert not (tmp_path / "state.json").exists()


def test_turning_it_on_twice_does_not_start_a_second_guard(tmp_path, monkeypatch) -> None:
    """Второй сторож пережил бы выключение режима, и машина перестала бы засыпать навсегда."""
    from justday import server

    guards: list[str] = []
    monkeypatch.setattr(server, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(server, "_screens", lambda on: True)
    monkeypatch.setattr(server, "_mute", lambda on: True)
    monkeypatch.setattr(server, "_keep_awake", lambda why: guards.append(why) or 7)

    server.on("раз")
    server.on("два")
    assert len(guards) == 1


# ──────────────────────────── флешка ────────────────────────────
def test_the_stick_keeps_its_keys_sealed(tmp_path) -> None:
    """Потерянная флешка должна означать потерянную флешку, а не потерянные ключи."""
    from justday import portable

    blob = portable.seal({"openrouter": "sk-очень-секретно"}, "пароль флешки")
    assert b"sk-" not in blob, "ключ видно прямо в файле — это не шифрование"
    assert portable.unseal(blob, "пароль флешки")["openrouter"] == "sk-очень-секретно"
    with pytest.raises(RuntimeError):
        portable.unseal(blob, "чужой пароль")


def test_the_stick_carries_its_own_home(tmp_path) -> None:
    """Всё, что ассистент пишет о себе, должно уехать на флешку, а не остаться у хозяина машины."""
    from justday import portable

    got = portable.init(str(tmp_path))
    assert got["ok"], got
    run = (tmp_path / portable.RUN).read_text(encoding="utf-8")
    for var in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_STATE_HOME", "XDG_CACHE_HOME"):
        assert f'export {var}="$HERE' in run, f"{var} остался бы на чужой машине"
    assert "systemctl" not in run, "служба пережила бы флешку"
    for part in ("home/config", "home/data", "home/state", "home/cache"):
        assert (tmp_path / part).is_dir()


def test_keys_on_the_stick_never_touch_the_host_keyring(tmp_path, monkeypatch) -> None:
    """На чужой машине в связку ключей хозяина не пишется ничего — иначе след остаётся у него."""
    from justday import portable, providers

    blob = tmp_path / "secrets.enc"
    blob.write_bytes(portable.seal({"groq": "gsk_со_флешки"}, "пароль"))
    monkeypatch.setattr(providers, "_portable", None)
    monkeypatch.setenv("JUSTDAY_SECRETS", str(blob))
    monkeypatch.setenv("JD_PASS", "пароль")
    called: list[str] = []
    monkeypatch.setattr(providers.shutil, "which", lambda name: called.append(name) or "/usr/bin/secret-tool")

    assert providers.secret_get("groq") == "gsk_со_флешки"
    assert "secret-tool" not in called, "полезли в связку ключей, хотя ключ лежал на флешке"


# ──────────────────────────── кнопка на телефоне вместо Bixby ────────────────────────────
def test_phone_commands_do_not_wipe_what_the_person_already_had(tmp_path, monkeypatch) -> None:
    """У человека могут быть свои команды, и стереть их ради своих — хамство.

    Дописываем своё, чужое оставляем как было.
    """
    import configparser
    import json as json_mod

    from justday import phone

    dev = tmp_path / ("a" * 32)
    dev.mkdir()
    conf = dev / "kdeconnect_runcommand"
    mine = {"его-команда": {"name": "Свет на кухне", "command": "/usr/bin/light kitchen"}}
    conf.write_text("[General]\ncommands=" + json_mod.dumps(mine, ensure_ascii=False) + "\n", encoding="utf-8")
    monkeypatch.setattr(phone, "_runcommand_files", lambda: [conf])

    got = phone.commands(install=True)
    assert got["ok"] and got["written"] == 1

    ini = configparser.ConfigParser()
    ini.optionxform = str
    ini.read(conf, encoding="utf-8")
    now = json_mod.loads(ini.get("General", "commands"))
    assert "его-команда" in now, "чужая команда пропала"
    assert now["его-команда"]["name"] == "Свет на кухне"
    assert "justday-listen" in now
    assert now["justday-listen"]["command"].endswith("justday toggle")


def test_the_dock_preview_did_not_shoot_the_lock_screen_nor_the_password_manager(tmp_path, monkeypatch) -> None:
    """Миниатюра окна — снимок всего экрана с вырезкой. Поэтому на запертом сеансе (там поле пароля) и на окне менеджера
    паролей снимка быть не должно; а полный снимок не переживает вырезку, даже если она не удалась (Р-12)."""
    from justday import desktop

    shots: list[str] = []
    monkeypatch.setenv("XDG_RUNTIME_DIR", str(tmp_path))
    import contextlib
    from pathlib import Path

    monkeypatch.setattr(desktop, "capture_screen", lambda path: shots.append(path) or Path(path).write_bytes(b"x" * 1000))
    monkeypatch.setattr(desktop, "_get_thumb_lock", lambda: contextlib.nullcontext())
    wins = [{"id": "1", "app": "org.keepassxc.KeePassXC", "w": 400, "h": 300, "x": 0, "y": 0},
            {"id": "2", "app": "kate", "w": 400, "h": 300, "x": 0, "y": 0}]
    monkeypatch.setattr(desktop, "windows", lambda *a, **kw: wins)
    monkeypatch.setattr(desktop, "_session_locked", lambda: False)

    got = desktop.window_thumb("1")
    assert got["private"] and not shots, "окно менеджера паролей снято"
    monkeypatch.setattr(desktop, "_session_locked", lambda: True)
    got = desktop.window_thumb("2")
    assert got["private"] and not shots, "запертый сеанс снят"

    monkeypatch.setattr(desktop, "_session_locked", lambda: False)
    monkeypatch.setattr(desktop.shutil, "which", lambda name: "/usr/bin/magick")

    def crop_failed(*a, **kw):
        raise OSError("magick упал")

    monkeypatch.setattr(desktop.subprocess, "run", crop_failed)
    got = desktop.window_thumb("2")
    assert not got["ok"] and shots, "проба не дошла до снимка"
    left = [p for p in (tmp_path / "justday-thumbs").glob("*-full.png")]
    assert not left, "полный снимок экрана остался лежать после неудачной вырезки"
