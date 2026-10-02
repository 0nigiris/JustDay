"""Лестница нейросетей в оболочке: кто отвечает на какую просьбу и что делать при лимите.

Плагин живёт в оболочке (OpenCode) и написан на JavaScript, а проверяется отсюда: один набор
тестов на весь проект лучше двух, и забыть про второй труднее, когда его нет.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parent.parent / "shell" / "opencode" / "justday-ladder.js"

SCRIPT = """
const said = []
const client = { tui: { showToast: async ({ body }) => said.push(body.message) } }
const { JustDayLadder } = await import(process.env.PLUGIN)
const h = await JustDayLadder({ client })
const pick = async (text) => {
  const o = { message: {}, parts: [{ type: 'text', text }] }
  await h['chat.message']({}, o)
  return o.message.model.providerID + '/' + o.message.model.modelID
}
const out = { }
out.trivial = await pick('который час')
out.work = await pick('напиши скрипт для переименования файлов')
out.short_but_doing = await pick('открой дискорд')
await h.event({ event: { type: 'session.error', properties: { error: 'Error 429: usage limit reached' } } })
out.after_limit = await pick('напиши скрипт')
await h.event({ event: { type: 'session.error', properties: { error: 'connection refused' } } })
out.after_network = await pick('напиши скрипт')
out.said = said
console.log(JSON.stringify(out))
"""


@pytest.fixture
def ladder(tmp_path):
    if not shutil.which("node"):
        pytest.skip("нет node — оболочку проверить нечем")
    conf = tmp_path / "opencode"
    conf.mkdir()
    (conf / "justday-ladder.json").write_text(json.dumps({
        "ladder": ["anthropic/claude-opus-4-5", "openrouter/deepseek/deepseek-chat", "ollama/qwen3:30b"],
        "tiny": "ollama/qwen3:0.6b",
    }), encoding="utf-8")
    r = subprocess.run(["node", "--input-type=module", "-e", SCRIPT], capture_output=True, text=True,
                       timeout=60, env={"PATH": "/usr/bin:/bin", "XDG_CONFIG_HOME": str(tmp_path),
                                        "PLUGIN": PLUGIN.as_uri(), "HOME": str(tmp_path)})
    assert r.returncode == 0, r.stderr
    return json.loads(r.stdout.strip().splitlines()[-1])


def test_small_talk_goes_to_the_small_model(ladder) -> None:
    """«Который час» не стоит облачной модели: ответить словом умеет и та, что на видеокарте."""
    assert ladder["trivial"] == "ollama/qwen3:0.6b"


def test_work_goes_to_the_top_of_the_ladder(ladder) -> None:
    """А работа — наверх, и короткая просьба что-то сделать это тоже работа.

    «Открой дискорд» короче «который час», но крошечной модели её отдавать нельзя: там надо не
    ответить, а сделать, а инструменты ей не даются.
    """
    assert ladder["work"] == "anthropic/claude-opus-4-5"
    assert ladder["short_but_doing"] == "anthropic/claude-opus-4-5"


def test_a_limit_steps_down_and_says_so(ladder) -> None:
    """Молча сменить того, кто отвечает, нельзя: человек должен знать, с кем говорит."""
    assert ladder["after_limit"] == "openrouter/deepseek/deepseek-chat"
    assert ladder["said"] and "Лимит" in ladder["said"][0]


def test_a_broken_connection_does_not_step_down(ladder) -> None:
    """Внизу тот же самый оборванный интернет — спускаться туда незачем."""
    assert ladder["after_network"] == "openrouter/deepseek/deepseek-chat"


# ──────────────────────────── ключи и место плагина ────────────────────────────
def test_keys_reach_the_window_through_the_environment_only(monkeypatch) -> None:
    """Ключам не место в настройках оболочки: это обычный файл, он читается и копируется.

    Связка ключей отдаёт их нам, мы отдаём их дочернему процессу переменными окружения — и ни одна
    строка ключа при этом не ложится на диск.
    """
    from justday import shell

    monkeypatch.setattr(shell.providers, "secret_get",
                        lambda name: "ключ-" + name if name in ("openrouter", "groq") else "")
    got = shell.env()
    assert got["OPENROUTER_API_KEY"] == "ключ-openrouter"
    assert got["GROQ_API_KEY"] == "ключ-groq"
    assert "DEEPSEEK_API_KEY" not in got      # ключа нет — и переменной быть не должно


def test_the_plugin_is_put_in_place_and_the_ladder_gets_a_default(tmp_path, monkeypatch) -> None:
    """Поставить оболочку — значит поставить и руль: без плагина это чужая программа, а не наша."""
    from justday import shell

    conf = tmp_path / "opencode"
    monkeypatch.setattr(shell, "CONF_DIR", conf)
    monkeypatch.setattr(shell, "PLUGIN", conf / "plugin" / "justday-ladder.js")
    monkeypatch.setattr(shell, "LADDER", conf / "justday-ladder.json")
    shell.ensure()
    assert (conf / "plugin" / "justday-ladder.js").resolve() == shell.source()
    first = json.loads((conf / "justday-ladder.json").read_text(encoding="utf-8"))
    assert first["ladder"][0].startswith("anthropic/")

    # Второй запуск не должен затирать то, что человек поправил под себя.
    (conf / "justday-ladder.json").write_text(json.dumps({"ladder": ["ollama/своя"]}), encoding="utf-8")
    shell.ensure()
    assert json.loads((conf / "justday-ladder.json").read_text(encoding="utf-8"))["ladder"] == ["ollama/своя"]
