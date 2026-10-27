"""Любая правка кончалась перезапуском всего: док пропадал. Остров должен только перерисовываться."""
import os

from justday import modules


def test_island_restart_is_a_touch_not_a_kill(tmp_path, monkeypatch):
    (tmp_path / "island").mkdir()
    qml = tmp_path / "island" / "shell.qml"
    qml.write_text("x")
    os.utime(qml, (1, 1))
    monkeypatch.setattr(modules.config, "REPO_DIR", tmp_path)
    monkeypatch.setattr(modules, "_systemctl", lambda *a: (_ for _ in ()).throw(AssertionError("systemctl")))
    assert modules.restart("island") == {"ok": True, "how": "reload"}
    assert qml.stat().st_mtime > 1000


def test_unknown_module_is_refused():
    assert modules.restart("rm -rf")["ok"] is False
