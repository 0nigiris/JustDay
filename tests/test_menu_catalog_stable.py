"""Меню просит каталог при каждом открытии, и сетка пересобиралась (160 значков в главном потоке) даже когда ничего не
изменилось — курсор ждал её. Остров теперь сравнивает каталог текстом и пересобирает только при отличии; это работает,
лишь пока демон отдаёт два подряд одинаковых каталога (без меток времени и случайного порядка)."""
import json

from justday import launcher


def test_two_catalogs_in_a_row_are_identical_so_the_grid_is_not_rebuilt(monkeypatch, tmp_path) -> None:
    monkeypatch.setattr(launcher, "favourites", lambda: ["app:a.desktop"])
    monkeypatch.setattr(launcher, "recents", lambda: ["app:b.desktop", "app:a.desktop"])
    first = json.dumps(launcher.catalog(), sort_keys=False)
    second = json.dumps(launcher.catalog(), sort_keys=False)
    assert first == second
