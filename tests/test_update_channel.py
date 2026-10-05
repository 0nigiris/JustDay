"""Те, кто обновлялся из main, получали сломанные промежуточные правки: канал стал отдельной веткой stable."""
import subprocess

from justday import config, manage


def _git(repo, *a):
    return subprocess.run(["git", "-C", str(repo), *a], capture_output=True, text=True, check=True).stdout.strip()


def test_install_on_main_is_told_to_move_to_stable(tmp_path, monkeypatch):
    origin, work = tmp_path / "o.git", tmp_path / "w"
    subprocess.run(["git", "init", "-q", "--bare", "-b", "main", str(origin)], check=True)
    subprocess.run(["git", "clone", "-q", str(origin), str(work)], check=True, capture_output=True)
    for k, v in (("user.name", "t"), ("user.email", "t@t")):
        _git(work, "config", k, v)
    (work / "a").write_text("1")
    _git(work, "add", ".")
    _git(work, "commit", "-qm", "первый")
    _git(work, "push", "-q", "origin", "HEAD:refs/heads/stable")
    (work / "a").write_text("2")
    _git(work, "commit", "-qam", "сырая правка в main")
    _git(work, "push", "-q", "origin", "HEAD:refs/heads/main")
    monkeypatch.setattr(config, "REPO_DIR", work)
    st = manage.update_status()
    assert st["branch"] == "stable" and st["on"] == "main"
    assert st["behind"] == 1 and "stable" in st["changes"][0]      # переезд на канал, сырые правки не тянутся
