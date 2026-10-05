"""Пункт 16: самая обычная команда «открой …» раз в полминуты платила сто миллисекунд за обход всех .desktop."""
import threading
import time

from justday import config, desktop


def test_a_stale_app_catalog_is_served_at_once_and_rebuilt_on_the_side(monkeypatch) -> None:
    release, scanned = threading.Event(), []

    def slow_scan():
        scanned.append(1)
        release.wait(5)
        desktop._apps_cache = (time.monotonic(), [{"id": "new"}])
        return desktop._apps_cache[1]

    monkeypatch.setattr(desktop, "_scan_apps", slow_scan)
    monkeypatch.setattr(desktop, "_apps_cache", (time.monotonic() - 60, [{"id": "old"}]))
    t0 = time.monotonic()
    assert desktop.list_apps() == [{"id": "old"}], "команда ждала пересборки каталога"
    assert time.monotonic() - t0 < 0.5
    desktop.list_apps()                     # второй вызов во время пересборки — не запускает вторую
    time.sleep(0.1)
    assert len(scanned) == 1
    release.set()
    for _ in range(50):
        if desktop.list_apps() == [{"id": "new"}]:
            break
        time.sleep(0.05)
    assert desktop.list_apps() == [{"id": "new"}], "новый каталог не подхватился"


def test_the_very_first_call_waits_for_a_real_catalog(monkeypatch) -> None:
    """Пустого кэша нет — отдавать нечего, и пустой список за настоящий не выдаётся (так док терял значки)."""
    monkeypatch.setattr(desktop, "_apps_cache", None)
    monkeypatch.setattr(desktop, "_scan_apps", lambda: [{"id": "fresh"}])
    assert desktop.list_apps() == [{"id": "fresh"}]


def test_config_load_hands_out_a_private_copy_with_and_without_a_file(tmp_path, monkeypatch) -> None:
    """Р-18: без config.toml правка выбранной модели меняла умолчания всего процесса. Не вернуть, ускоряя load()."""
    for exists in (False, True):
        f = tmp_path / ("c.toml" if exists else "none.toml")
        if exists:
            f.write_text("[brain]\nmodel = \"opus\"\n")
        monkeypatch.setattr(config, "CONFIG_FILE", f)
        a, b = config.load(), config.load()
        a["brain"]["effort"] = "max"
        a["island"]["screen"] = "X"
        assert b["brain"]["effort"] != "max" and b["island"]["screen"] != "X"
        assert config.DEFAULTS["brain"]["effort"] != "max"
        assert (a["brain"]["model"] == "opus") is exists
