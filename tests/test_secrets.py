"""Ключи живут в связке, а не в файле рядом с настройками (Р-2 ревизии)."""

import os
import stat

import pytest

from justday import config


@pytest.fixture
def keyring(tmp_path, monkeypatch):
    """Подставная `secret-tool`: хранит ключи в папке, настоящую связку не трогает."""
    store = tmp_path / "ring"
    store.mkdir()
    tool = tmp_path / "bin" / "secret-tool"
    tool.parent.mkdir()
    tool.write_text(f"""#!/bin/sh
cmd=$1; shift
while [ $# -gt 1 ]; do [ "$1" = key ] && name=$2; shift; done
case $cmd in
  store) cat > "{store}/$name" ;;
  lookup) [ -f "{store}/$name" ] && cat "{store}/$name" || exit 1 ;;
  clear) rm -f "{store}/$name" ;;
esac
""")
    tool.chmod(tool.stat().st_mode | stat.S_IXUSR)
    monkeypatch.setenv("PATH", f"{tool.parent}:{os.environ['PATH']}")
    monkeypatch.setattr(config, "SECRETS_FILE", tmp_path / "secrets.env")
    monkeypatch.setattr(config, "_KEYRING_CACHE", {})
    monkeypatch.delenv("ELEVENLABS_API_KEY", raising=False)
    return store


def test_a_key_in_the_old_file_moved_to_the_keyring_and_the_file_went_empty(keyring):
    """Ключ ElevenLabs лежал открытым текстом в secrets.env, а Bash(cat:*) мозгу разрешён."""
    config.SECRETS_FILE.write_text("ELEVENLABS_API_KEY=sk-test\nOTHER=x\n")
    assert config.secret("ELEVENLABS_API_KEY") == "sk-test"  # старая установка продолжает работать
    assert config.migrate_secrets_file() == ["ELEVENLABS_API_KEY", "OTHER"]
    assert config.SECRETS_FILE.read_text() == ""
    assert (keyring / "elevenlabs").read_text() == "sk-test"
    assert config.secret("ELEVENLABS_API_KEY") == "sk-test"  # теперь из связки


def test_setting_a_key_does_not_leave_it_in_the_file(keyring):
    config.SECRETS_FILE.write_text("ELEVENLABS_API_KEY=old\n")
    config.set_secret("ELEVENLABS_API_KEY", "new")
    assert "old" not in config.SECRETS_FILE.read_text()
    assert config.secret("ELEVENLABS_API_KEY") == "new"
    config.set_secret("ELEVENLABS_API_KEY", "")
    assert config.secret("ELEVENLABS_API_KEY") == ""
