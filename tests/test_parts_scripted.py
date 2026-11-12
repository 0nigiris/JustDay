"""Студия и локальная модель ставятся скриптом: попади они в `uv sync --extra`, uv упал бы на неизвестном
extra, и вместе со студией не поставилась бы и речь, нажатая в ту же минуту."""
from justday import parts


def test_scripted_parts_never_reach_uv():
    ok, cmd = parts.sync(("studio", "local_llm", "speech"), dry=True)
    assert ok
    assert "--extra studio" not in cmd and "--extra local_llm" not in cmd
    assert "--extra speech" in cmd


def test_scripts_exist():
    from justday import config
    for p in parts.PARTS.values():
        if p.script:
            assert (config.REPO_DIR / "scripts" / p.script).exists(), p.script
