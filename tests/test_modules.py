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


def test_unknown_part_is_refused_before_systemd(monkeypatch):
    """Этап 2 установки качает гигабайты по команде из острова: чужое имя части не должно дойти до командной строки."""
    from justday import modules

    ran = []
    monkeypatch.setattr(modules.subprocess, "run", lambda *a, **k: ran.append(a))
    got = modules.parts_in_background(["speech; rm -rf ~"])
    assert not got["ok"] and not ran


def test_studio_waits_for_voice_instead_of_vanishing(monkeypatch):
    """Студию выбирали в знакомстве, пока качался голос, — ответ «уже идёт», и студия не ставилась (28 нояб.)."""
    import subprocess
    import types

    monkeypatch.setattr(modules.shutil, "which", lambda n: "/bin/" + n)
    monkeypatch.setattr(modules, "_systemctl", lambda _c, u: types.SimpleNamespace(
        stdout="active" if u == "justday-parts.service" else "inactive"))
    ran = []
    monkeypatch.setattr(modules.subprocess, "run", lambda a, **k: ran.append(a) or subprocess.CompletedProcess(a, 0, "", ""))
    assert modules.parts_in_background(["studio"])["ok"]
    assert "--unit=justday-parts-next" in ran[0] and "is-active justday-parts" in ran[0][-1]
