"""На школьном ПК нельзя заново настраивать всё руками, а ключи нельзя возить открытым текстом.

Чемодан должен собираться только с паролем, раскрываться только верным паролем, не писать куда
попало и не терять прежний конфиг."""
import pytest

from justday import config, suitcase


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path / "cfg")
    monkeypatch.setattr(config, "CONFIG_FILE", tmp_path / "cfg" / "config.toml")
    monkeypatch.setattr(config, "SECRETS_FILE", tmp_path / "cfg" / "secrets.env")
    monkeypatch.setitem(suitcase.FILES, "pins.json", tmp_path / "pins.json")
    monkeypatch.setattr(config, "list_secrets", lambda: {"elevenlabs": "sk-mine", "telegram_pin": "1234"})
    saved = {}
    monkeypatch.setattr(config, "set_secret", lambda k, v: saved.__setitem__(k, v))
    (tmp_path / "cfg").mkdir()
    (tmp_path / "cfg" / "config.toml").write_text("[ui]\nlang='ru'\n")
    (tmp_path / "pins.json").write_text('{"a": 1}')
    return tmp_path, saved


def test_no_password_no_suitcase(home):
    with pytest.raises(ValueError):
        suitcase.pack("")


def test_roundtrip_keeps_old_config_and_hides_keys(home):
    tmp, saved = home
    blob = suitcase.pack("пароль")
    assert b"sk-mine" not in blob
    (tmp / "cfg" / "config.toml").write_text("[ui]\nlang='en'\n")
    got = suitcase.unpack(blob, "пароль")
    assert got == {"secrets": 2, "files": 1, "config": True}
    assert saved["elevenlabs"] == "sk-mine"
    assert "ru" in (tmp / "cfg" / "config.toml").read_text()
    assert "en" in (tmp / "cfg" / "config.toml.before-suitcase").read_text()


def test_wrong_password_is_an_error(home):
    blob = suitcase.pack("верный")
    with pytest.raises(RuntimeError):
        suitcase.unpack(blob, "чужой")
