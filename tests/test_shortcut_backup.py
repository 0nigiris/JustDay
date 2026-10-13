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


def test_purge_left_the_cache_of_what_he_watched() -> None:
    """Политика обещает: `--purge` удаляет всё сразу. А `~/.cache/justday` (обложки и до 3 ГБ видео острова,
    по ним видно, что он смотрел и слушал) оставался. Каждая XDG-папка, куда пишет программа, — в чистке."""
    import pathlib
    import re

    script = pathlib.Path("uninstall.sh").read_text(encoding="utf-8")
    purge = script.split("if ((PURGE))", 1)[1]
    used = set(re.findall(r"XDG_(\w+?)_HOME", "".join(p.read_text(encoding="utf-8")
                                                       for p in pathlib.Path("src/justday").glob("*.py")
                                                       if p.name != "portable.py")))
    assert used >= {"CONFIG", "DATA", "STATE", "CACHE"}
    for kind in used:
        assert f"${{XDG_{kind}_HOME:-" in purge, kind
