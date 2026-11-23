"""У друга на Windows нет git-копии: «есть обновление» не появлялось никогда, и exe старел навсегда."""
import io
import json

from justday import manage


def test_windows_sees_a_newer_release(monkeypatch):
    rel = {"tag_name": "v0.10.0", "name": "JustDay 0.10.0",
           "assets": [{"name": "JustDay-Setup-0.10.0.exe", "browser_download_url": "https://x/s.exe"}]}
    monkeypatch.setattr("urllib.request.urlopen", lambda *a, **k: io.BytesIO(json.dumps(rel).encode()))
    monkeypatch.setattr(manage, "app_version", lambda: "0.9.0")
    st = manage.exe_update_status()
    assert st["behind"] == 1 and st["url"] == "https://x/s.exe"
    monkeypatch.setattr(manage, "app_version", lambda: "0.10.0")
    assert manage.exe_update_status()["behind"] == 0
