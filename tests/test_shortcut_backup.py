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


def test_uninstall_left_services_running() -> None:
    """После `uninstall.sh` justday-ui, голос и сторож продолжали работать без программы: удалятор
    гасил устаревший список служб. Теперь он берёт все наши юниты по маске, и ключи — по атрибуту."""
    import pathlib

    script = pathlib.Path("uninstall.sh").read_text(encoding="utf-8")
    assert "ls justday*.service justday*.socket" in script
    assert all(u.name.startswith("justday") for u in pathlib.Path("systemd").iterdir()), "юнит не под маской"
    assert "secret-tool clear service justday 2>" in script
