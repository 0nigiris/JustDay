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
const sent = []
const client = { tui: { showToast: async ({ body }) => said.push(body.message) },
                 session: { prompt: async (o) => sent.push(o) } }
const { JustDayLadder } = await import(process.env.PLUGIN)
const h = await JustDayLadder({ client })
const pick = async (text) => {
  const o = { message: {}, parts: [{ type: 'text', text }] }
  await h['chat.message']({}, o)
  return o.message.model.providerID + '/' + o.message.model.modelID
}
const out = { }
out.sent = sent
out.trivial = await pick('который час')
out.work = await pick('напиши скрипт для переименования файлов')
out.short_but_doing = await pick('открой дискорд')
await h.event({ event: { type: 'session.error', properties: { sessionID: 'ses_1', error: 'Error 429: usage limit reached' } } })
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
    # Вход в оболочку: без него ступени пропускаются как недоступные — это проверяется отдельно.
    auth = tmp_path / ".local" / "share" / "opencode"
    auth.mkdir(parents=True)
    (auth / "auth.json").write_text(json.dumps({"anthropic": {"type": "api"},
                                                "openrouter": {"type": "api"}}), encoding="utf-8")
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
    monkeypatch.setattr(shell, "SETTINGS", conf / "opencode.json")
    monkeypatch.setattr(shell.config, "load", lambda: {"terminal": {"ladder": ["claude:opus"]}})
    shell.ensure()
    assert (conf / "plugin" / "justday-ladder.js").resolve() == shell.source()
    first = json.loads((conf / "justday-ladder.json").read_text(encoding="utf-8"))
    assert first["ladder"] == ["ollama/qwen3.5:9b"]   # в config.toml ступеней оболочки нет — остаётся местная

    # Второй запуск не затирает остальное, что человек поправил под себя; ступени же одни, из config.toml.
    first["probeMinutes"] = 7
    (conf / "justday-ladder.json").write_text(json.dumps(first), encoding="utf-8")
    shell.ensure()
    assert json.loads((conf / "justday-ladder.json").read_text(encoding="utf-8"))["probeMinutes"] == 7


def test_the_next_model_is_told_where_to_read_up(ladder) -> None:
    """Пришедшей на смену нужен не приказ «продолжай», а то, что делалось до неё.

    Заметка кладётся в разговор без ответа: это контекст, а не реплика, и отвечать на неё человеку
    не надо. В ней — имя файла, где лежит всё остальное.
    """
    sent = ladder["sent"]
    assert sent, "смена модели прошла молча — следующая не узнает, что здесь было"
    body = sent[0]["body"]
    assert body["noReply"] is True
    assert "ПЕРЕДАЧА.md" in body["parts"][0]["text"]


def test_a_last_years_model_name_dropped_the_whole_ladder(tmp_path, monkeypatch) -> None:
    """Устаревшее имя модели на верхней ступени уводило думать самую слабую.

    Поставщик на переименованную модель отвечает не «такой больше нет», а просто ошибкой, а
    лестница любую ошибку считает кончившимся лимитом — и спускается. Верх умирал молча: человек
    видел только, что отвечает кто-то не тот. Теперь имена подновляются при запуске оболочки.
    """
    from justday import shell

    conf = tmp_path / "opencode"
    conf.mkdir()
    monkeypatch.setattr(shell, "CONF_DIR", conf)
    monkeypatch.setattr(shell, "PLUGIN", conf / "plugin" / "justday-ladder.js")
    monkeypatch.setattr(shell, "LADDER", conf / "justday-ladder.json")
    monkeypatch.setattr(shell, "SETTINGS", conf / "opencode.json")
    monkeypatch.setattr(shell.config, "load", lambda: {"terminal": {"ladder": [
        "opencode:anthropic/claude-opus-4-5", "opencode:anthropic/claude-sonnet-4-5", "opencode:ollama/своя"]}})
    (conf / "justday-ladder.json").write_text(json.dumps({
        "tiny": "anthropic/claude-3-5-haiku",
        "probeMinutes": 7,
    }, ensure_ascii=False), encoding="utf-8")

    shell.ensure()

    got = json.loads((conf / "justday-ladder.json").read_text(encoding="utf-8"))
    assert got["ladder"] == ["anthropic/claude-opus-5-5", "anthropic/claude-sonnet-5-5", "ollama/своя"]
    assert got["tiny"] == "anthropic/claude-haiku-4-5"
    assert got["probeMinutes"] == 7        # своё человек правил не для того, чтобы мы это стёрли


def test_renaming_two_rungs_into_one_does_not_leave_a_double() -> None:
    """Две ступени после переименования могли стать одной и той же моделью.

    Лестница из одинаковых ступеней не спускается: кончился лимит — пробуем того же самого,
    получаем ту же ошибку, и так до самого низа впустую.
    """
    from justday import shell

    assert shell.fresh(["anthropic/claude-opus-4-5", "anthropic/claude-opus-4-1"]) \
        == ["anthropic/claude-opus-5-5"]


def test_a_rung_with_nothing_to_log_in_with_was_counted_as_a_limit(tmp_path) -> None:
    """Ступень, куда нечем войти, проваливала начало разговора.

    Поставщик без ключа отвечает обычной ошибкой, а лестница любую ошибку считает кончившимся
    лимитом — и спускается. Разговор начинался с двух провалов подряд, и человек видел, что
    отвечает кто-то не тот. Такие ступени пропускаются сразу, а человеку говорится, какие.

    Про anthropic это теперь обычное дело: войти в него подпиской Claude нельзя (с февраля 2026
    Anthropic разрешает такой вход только своим Claude Code и claude.ai), а ключа у человека нет.
    """
    if not shutil.which("node"):
        pytest.skip("нет node — оболочку проверить нечем")
    conf = tmp_path / "opencode"
    conf.mkdir()
    (conf / "justday-ladder.json").write_text(json.dumps({
        "ladder": ["anthropic/claude-opus-5-5", "openrouter/qwen/qwen3-coder", "ollama/qwen3.5:9b"],
        "tiny": "ollama/qwen3.5:9b",
    }), encoding="utf-8")

    script = """
const said = []
const client = { tui: { showToast: async ({ body }) => said.push(body.message) },
                 session: { prompt: async () => ({}) } }
const { JustDayLadder } = await import(process.env.PLUGIN)
const h = await JustDayLadder({ client })
const o = { message: {}, parts: [{ type: 'text', text: 'напиши скрипт' }] }
await h['chat.message']({}, o)
console.log(JSON.stringify({ model: o.message.model.providerID + '/' + o.message.model.modelID, said }))
"""
    r = subprocess.run(["node", "--input-type=module", "-e", script], capture_output=True, text=True,
                       timeout=60, env={"PATH": "/usr/bin:/bin", "XDG_CONFIG_HOME": str(tmp_path),
                                        "PLUGIN": PLUGIN.as_uri(), "HOME": str(tmp_path)})
    assert r.returncode == 0, r.stderr
    got = json.loads(r.stdout.strip().splitlines()[-1])
    assert got["model"] == "ollama/qwen3.5:9b", "работа ушла на ступень, куда нечем войти"
    assert any("anthropic/claude-opus-5-5" in m for m in got["said"]), \
        "ступени пропущены молча — человек не поймёт, почему отвечает не тот"


def test_sitting_down_to_work_should_not_start_with_a_refusal(monkeypatch, capsys) -> None:
    """Выбирать оболочку руками значило каждый раз сначала наткнуться на «лимит кончился».

    Подписка Claude работает только в Claude Code, а когда она кончилась — работать всё равно
    надо, уже в оболочке. `justday work` спрашивает Claude одним крошечным вопросом и садится
    туда, где сегодня можно: человек при этом ничего не выбирает и ни на что не натыкается.
    """
    from justday import shell

    opened = []
    monkeypatch.setattr(shell.os, "execve", lambda cli, argv, env: opened.append(cli))
    monkeypatch.setattr(shell.shutil, "which", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(shell, "run", lambda args=None: opened.append("opencode") or 0)

    monkeypatch.setattr(shell, "claude_answers", lambda timeout=45.0: True)
    shell.work([])
    assert opened == ["/usr/bin/claude"], "Claude отвечает, а работа ушла не к нему"

    opened.clear()
    monkeypatch.setattr(shell, "claude_answers", lambda timeout=45.0: False)
    shell.work([])
    assert opened == ["opencode"], "лимит кончился, а работа всё равно пошла в Claude"
    assert "ПЕРЕДАЧА.md" in capsys.readouterr().out, "пришедшей на смену не сказали, что читать"
