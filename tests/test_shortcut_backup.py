"""Удаление JustDay оставляло Meta и Alt+Space пустыми: у соседей их забрали, а вернуть было нечем (Р2-44)."""
from justday import manage


def test_neighbours_keys_come_back_after_uninstall(tmp_path, monkeypatch):
    monkeypatch.setattr(manage, "SHORTCUT_BACKUP", tmp_path / "backup" / "shortcuts.json")
    calls = []
    monkeypatch.setattr(manage, "_accel", lambda method, *a: calls.append((method, a)) or "")
    manage._remember_shortcut("krunner.desktop", "_launch", "KRunner", "KRunner", [32, 33])
    # второй запуск установщика видит уже обеднённый список — «было» не затирается
    manage._remember_shortcut("krunner.desktop", "_launch", "KRunner", "KRunner", [33])
    assert manage.restore_shortcuts() == ["KRunner"]
    assert calls == [("setShortcut", ("['krunner.desktop','_launch','KRunner','KRunner']", "@ai [32, 33]", "4"))]
    assert manage.restore_shortcuts() == []     # запись использована
