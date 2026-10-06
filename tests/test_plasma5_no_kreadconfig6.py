"""На Plasma 5 нет kreadconfig6: мастер первой настройки падал с FileNotFoundError на шаге «Кнопки»."""
from justday import kde, manage, notifications


def test_wizard_hotkey_read_survives_missing_kde_tools(monkeypatch, tmp_path):
    monkeypatch.setattr(kde, "KREAD", "no-such-kreadconfig")
    monkeypatch.setattr(kde, "KWRITE", "no-such-kwriteconfig")
    monkeypatch.setenv("HOME", str(tmp_path))
    assert manage._shortcut("justday.desktop") == []
    assert notifications._kread("f", "g", "k") == ""
    notifications._kwrite("f", "g", "k", "v")
