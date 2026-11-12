from justday import config, manage


def test_version_follows_pyproject_not_stale_install(tmp_path, monkeypatch):
    """После обновлений через git «О программе» показывало 0.2.0, хотя в коде была 0.9.0."""
    (tmp_path / "pyproject.toml").write_text('[project]\nname = "justday"\nversion = "7.1.2"\n')
    monkeypatch.setattr(config, "REPO_DIR", tmp_path)
    assert manage.app_version() == "7.1.2"   # не git-копия: беты не видно, номер честный
