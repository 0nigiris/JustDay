"""Р-45: каждый щелчок настройки в окне острова запускал процесс `justday config set` (Python с импортом всего пакета).
Теперь настройку принимает демон. Беды, которые нельзя допустить: тип значения теряется (число стало строкой),
мозг меняет настройки сам (через них снимается его защита), а ключ с переводом строки дописывает чужие настройки."""
from __future__ import annotations

import asyncio
import json

import pytest

from justday import config, manage
from justday.daemon import Daemon


@pytest.fixture
def cfg_file(tmp_path, monkeypatch):
    path = tmp_path / "config.toml"
    path.write_text('[island]\nmenu_width = 760\n\n[audio]\nearcons = true\n', encoding="utf-8")
    monkeypatch.setattr(config, "CONFIG_DIR", tmp_path)
    monkeypatch.setattr(config, "CONFIG_FILE", path)
    return path


def _ask(request: dict, human: bool) -> dict:
    class Reader:
        async def readline(self):
            return json.dumps(request).encode()

    class Writer:
        data = b""

        def write(self, b):
            self.data += b

        async def drain(self):
            pass

        def close(self):
            pass

        def get_extra_info(self, _name):
            return None

    d = Daemon.__new__(Daemon)
    d._peer_is_ai = lambda _w: not human
    d.reload_settings = lambda: []
    w = Writer()
    asyncio.run(d._client(Reader(), w))
    return json.loads(w.data)


def test_a_setting_keeps_its_type(cfg_file) -> None:
    assert _ask({"cmd": "config_set", "key": "island.menu_width", "value": "820"}, human=True)["ok"] is True
    assert _ask({"cmd": "config_set", "key": "audio.earcons", "value": "false"}, human=True)["ok"] is True
    got = config.load()
    assert got["island"]["menu_width"] == 820 and isinstance(got["island"]["menu_width"], int)
    assert got["audio"]["earcons"] is False


def test_the_brain_cannot_change_settings_through_the_socket(cfg_file) -> None:
    before = cfg_file.read_text(encoding="utf-8")
    got = _ask({"cmd": "config_set", "key": "audio.earcons", "value": "false"}, human=False)
    assert got["ok"] is False and cfg_file.read_text(encoding="utf-8") == before


def test_a_key_cannot_smuggle_in_other_settings(cfg_file) -> None:
    before = cfg_file.read_text(encoding="utf-8")
    with pytest.raises(ValueError):
        manage.set_setting("island.x\nbrain.permission_mode", "bypass")
    assert cfg_file.read_text(encoding="utf-8") == before
