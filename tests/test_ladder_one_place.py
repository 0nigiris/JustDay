"""Лестница одна на весь проект, и все три проверки «есть ли чем войти» отвечают одинаково (Р-60 ревизии)."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from justday import config, shell, terminal

PLUGIN = Path(__file__).resolve().parent.parent / "shell" / "opencode" / "justday-ladder.js"


@pytest.fixture
def conf(tmp_path, monkeypatch):
    for name, rel in (("CONF_DIR", ""), ("PLUGIN", "plugin/justday-ladder.js"), ("LADDER", "justday-ladder.json"),
                      ("SETTINGS", "opencode.json"), ("RULES", "ПРАВИЛА.md")):
        monkeypatch.setattr(shell, name, tmp_path / rel)
    monkeypatch.setattr(shell, "AUTH", tmp_path / "auth.json")
    monkeypatch.setattr(shell, "CLAUDE_HOME", tmp_path / "claude")
    monkeypatch.setattr(shell.providers, "secret_get", lambda name: "")
    for var in shell.KEYS.values():
        monkeypatch.delenv(var, raising=False)
    return tmp_path


def test_the_plugin_ladder_came_from_the_one_in_config_toml(conf, monkeypatch):
    """Ступени лежали в четырёх местах и расходились; плагин OpenCode жил по своему списку, а не по тому,
    что человек поставил в config.toml."""
    monkeypatch.setattr(config, "load", lambda: {"terminal": {"ladder": [
        "claude:opus", "opencode:openai/gpt-6-luna", "opencode:nvidia/nvidia/nemotron", "opencode:ollama/qwen3.5:9b"]}})
    shell.ensure()
    got = json.loads(shell.LADDER.read_text(encoding="utf-8"))
    assert got["ladder"] == ["openai/gpt-6-luna", "nvidia/nvidia/nemotron", "ollama/qwen3.5:9b"]
    assert got["keys"]["nvidia"] == "NVIDIA_API_KEY"


def test_a_rung_with_a_key_in_the_environment_was_alive_in_one_check_and_dead_in_another(conf, monkeypatch):
    """nvidia: терминал её знал, плагин OpenCode — нет, и лестница OpenCode ходила мимо неё."""
    monkeypatch.setattr(terminal.shutil, "which", lambda name: "/usr/bin/" + name)
    rung = terminal.parse_rung("opencode:nvidia/nvidia/nemotron")
    assert not terminal.reachable(rung)
    monkeypatch.setenv("NVIDIA_API_KEY", "x")
    assert terminal.reachable(rung)
    assert not terminal.reachable(terminal.parse_rung("opencode:opencode/nemotron-3.5-lightning-free"))


@pytest.mark.skipif(not shutil.which("node"), reason="нет node")
@pytest.mark.parametrize("key,expect", [(True, "nvidia/big"), (False, "ollama/small")])
def test_the_plugin_took_nvidia_when_the_key_was_there(conf, key, expect):
    shell.LADDER.write_text(json.dumps({"ladder": ["nvidia/big", "ollama/small"],
                                        "keys": shell.KEYS, "local": sorted(shell.LOCAL)}), encoding="utf-8")
    script = """
const o = { message: {}, parts: [{ type: 'text', text: 'напиши скрипт для переименования файлов' }] }
const { JustDayLadder } = await import(process.env.PLUGIN)
const h = await JustDayLadder({ client: { tui: { showToast: async () => {} }, session: {} } })
await h['chat.message']({}, o)
console.log(o.message.model.providerID + '/' + o.message.model.modelID)
"""
    env = {"PATH": "/usr/bin:/bin", "XDG_CONFIG_HOME": str(conf.parent), "XDG_DATA_HOME": str(conf), "HOME": str(conf),
           "PLUGIN": PLUGIN.as_uri()}
    if key:
        env["NVIDIA_API_KEY"] = "x"
    (conf.parent / "opencode").mkdir(exist_ok=True)
    shutil.copy(shell.LADDER, conf.parent / "opencode" / "justday-ladder.json")
    out = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True, timeout=60, env=env)
    assert out.stdout.strip() == expect, out.stderr
