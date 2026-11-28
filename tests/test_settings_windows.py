from justday import config, manage


def test_settings_open_without_systemd(monkeypatch, tmp_path):
    """Окно настроек на Windows не открывалось (28 нояб.): settings-data звал systemctl, которого там нет."""
    monkeypatch.setattr(config, "WINDOWS", True)
    monkeypatch.setenv("PATH", str(tmp_path))
    assert manage.voices()["neural_running"] is False
    assert manage.guard()["on"] is False
