"""Без связки ключей страница настроек больше минуты висела на «Загружаю настройки…»:
каждый из полутора десятков ключей ждал своё отдельное время ожидания `secret-tool`."""
import subprocess

from justday import config, providers


def test_one_timeout_stops_further_keyring_waits(monkeypatch):
    calls = []

    def hang(*a, **kw):
        calls.append(a)
        raise subprocess.TimeoutExpired(a[0], 5)

    monkeypatch.setattr(subprocess, "run", hang)
    monkeypatch.setattr(config, "KEYRING_DEAD", [False])
    monkeypatch.setattr(config, "_KEYRING_CACHE", {})
    monkeypatch.setattr(providers, "_SECRETS", {})
    monkeypatch.setattr(providers.shutil, "which", lambda n: "/usr/bin/" + n)
    assert config._keyring_get("ELEVENLABS_API_KEY") == ""
    assert providers.secret_get("openrouter") == ""
    assert providers.secret_get("groq") == ""
    assert config._keyring_get("FISH_API_KEY") == ""
    assert len(calls) == 1
