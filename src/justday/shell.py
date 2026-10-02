"""Оболочка: чёрное окно OpenCode с нашим рулём.

Своего окна мы не писали. OpenCode уже такой, какой нужен, и умеет говорить с десятком
поставщиков; наше здесь — лестница: кто отвечает, когда меняется и что делать, когда у него
кончился лимит. Лестница живёт плагином (`shell/opencode/justday-ladder.js`), а эта команда её
ставит на место и запускает окно.

Ключи. В настройках OpenCode им не место: это обычный файл, который читается кем угодно и уезжает
в чужие руки вместе с резервной копией. Поэтому ключи лежат в связке ключей рабочего стола, а
сюда попадают переменными окружения — только дочернему процессу и только на время его жизни.
"""
from __future__ import annotations

import json
import os
import shutil
from pathlib import Path

from . import config, providers

# Поставщик → как его ключ называется у нас в связке и как его ждёт OpenCode.
#
# anthropic здесь тоже есть, но только как ключ API. Войти в оболочку подпиской Claude нельзя:
# с февраля 2026 Anthropic разрешает такой вход только своим Claude Code и claude.ai, а с апреля
# закрывает его и технически. Подписка остаётся там, где она разрешена, — в самом Claude Code,
# которым и думает сам Джарвис.
KEYS = {"anthropic": "ANTHROPIC_API_KEY", "openrouter": "OPENROUTER_API_KEY",
        "groq": "GROQ_API_KEY", "deepseek": "DEEPSEEK_API_KEY"}
AUTH = Path(os.environ.get("XDG_DATA_HOME", Path.home() / ".local" / "share")) / "opencode" / "auth.json"
LOCAL = {"ollama", "lmstudio", "llamacpp", "local"}

CONF_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "opencode"
PLUGIN = CONF_DIR / "plugin" / "justday-ladder.js"
LADDER = CONF_DIR / "justday-ladder.json"
SETTINGS = CONF_DIR / "opencode.json"
RULES = CONF_DIR / "ПРАВИЛА.md"
CLAUDE_HOME = Path.home() / ".claude"

DEFAULT_LADDER = {
    # Порядок — это и есть приоритет: сверху тот, кем хочется думать всегда.
    "ladder": ["anthropic/claude-opus-5-5", "anthropic/claude-sonnet-5-5", "anthropic/claude-haiku-4-5"],
    "tiny": "",
    "probeMinutes": 15,
    "tinyMaxChars": 80,
    "quiet": False,
}

# Переименованные модели. Поставщик на прошлогоднее имя не отвечает «такой больше нет» — он
# отвечает ошибкой, а лестница считает любую ошибку кончившимся лимитом и спускается на ступень
# ниже. Один устаревший верх — и думает кто угодно, кроме того, кем просили.
RENAMED = {
    "anthropic/claude-opus-4-5": "anthropic/claude-opus-5-5",
    "anthropic/claude-opus-4-1": "anthropic/claude-opus-5-5",
    "anthropic/claude-sonnet-4-5": "anthropic/claude-sonnet-5-5",
    "anthropic/claude-3-5-haiku": "anthropic/claude-haiku-4-5",
}


def fresh(rungs: list[str]) -> list[str]:
    """Заменить переименованные модели нынешними, порядок и всё остальное не трогая."""
    out, seen = [], set()
    for rung in rungs:
        name = RENAMED.get(rung, rung)
        if name not in seen:        # после замены две ступени могут совпасть
            seen.add(name)
            out.append(name)
    return out


def source() -> Path:
    return config.REPO_DIR / "shell" / "opencode" / "justday-ladder.js"


def mcp_from_claude() -> dict:
    """Серверы MCP, настроенные в Claude Code, в том виде, который понимает оболочка.

    Переносить их руками значит однажды забыть: инструмент есть в одной оболочке и нет в другой,
    и работа в запасной оказывается хуже не из-за модели, а из-за того, что ей нечем работать.
    """
    out: dict[str, dict] = {}
    for f in (Path.home() / ".claude.json", CLAUDE_HOME / "settings.json"):
        try:
            got = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        for name, srv in (got.get("mcpServers") or {}).items():
            if not isinstance(srv, dict):
                continue
            kind = str(srv.get("type") or ("local" if srv.get("command") else "remote"))
            if srv.get("url") and kind in ("http", "sse", "remote"):
                out[name] = {"type": "remote", "url": str(srv["url"]), "enabled": True}
                if srv.get("headers"):
                    out[name]["headers"] = srv["headers"]
            elif srv.get("command"):
                out[name] = {"type": "local", "enabled": True,
                             "command": [str(srv["command"]), *[str(a) for a in (srv.get("args") or [])]]}
                if srv.get("env"):
                    out[name]["environment"] = srv["env"]
    return out


def skill_paths() -> list[str]:
    """Где лежат умения: свои и те, что пришли с плагинами Claude Code.

    Пути берутся из списка установленных плагинов, а не записываются раз и навсегда: у плагина
    своя версия в пути, и обновление плагина молча оставило бы оболочку без его умений.
    """
    out = []
    own = CLAUDE_HOME / "skills"
    if own.is_dir():
        out.append(str(own))
    try:
        inst = json.loads((CLAUDE_HOME / "plugins" / "installed_plugins.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        inst = {}
    for entries in (inst.get("plugins") or {}).values():
        for e in entries if isinstance(entries, list) else []:
            got = Path(str(e.get("installPath") or "")) / "skills"
            if got.is_dir():
                out.append(str(got))
    return sorted(set(out))


def ensure() -> None:
    """Положить плагин на место, завести настройку и перенести инструменты из Claude Code."""
    PLUGIN.parent.mkdir(parents=True, exist_ok=True)
    src = source()
    if src.exists() and (not PLUGIN.exists() or PLUGIN.resolve() != src):
        PLUGIN.unlink(missing_ok=True)
        PLUGIN.symlink_to(src)
    if not LADDER.exists():
        LADDER.write_text(json.dumps(DEFAULT_LADDER, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        try:
            got = json.loads(LADDER.read_text(encoding="utf-8"))
        except ValueError:
            got = None
        if isinstance(got, dict) and isinstance(got.get("ladder"), list):
            rungs = fresh([str(r) for r in got["ladder"]])
            tiny = RENAMED.get(str(got.get("tiny") or ""), got.get("tiny"))
            if rungs != got["ladder"] or tiny != got.get("tiny"):
                got["ladder"], got["tiny"] = rungs, tiny
                LADDER.write_text(json.dumps(got, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    try:
        conf = json.loads(SETTINGS.read_text(encoding="utf-8")) if SETTINGS.exists() else {}
    except ValueError:
        return          # человек правил файл руками и сломал его — чинить за него не наше дело
    conf.setdefault("$schema", "https://opencode.ai/config.json")
    # Инструменты: те же MCP и те же умения, что в Claude Code.
    mcp = dict(conf.get("mcp") or {})
    mcp.update(mcp_from_claude())
    if mcp:
        conf["mcp"] = mcp
    paths = skill_paths()
    if paths:
        skills = dict(conf.get("skills") or {})
        skills["paths"] = sorted(set([*skills.get("paths", []), *paths]))
        conf["skills"] = skills
    # Сжимать разговор, не дожидаясь, пока он упрётся в стену. Длинная сессия без сжатия
    # кончается тем, что модель помнит начало и не помнит, что делала десять минут назад.
    conf.setdefault("compaction", {"auto": True, "tail_turns": 15})
    # Правила: общие для всех сессий и правила самого проекта.
    want = [str(RULES), "AGENTS.md"]
    conf["instructions"] = sorted(set([*(conf.get("instructions") or []), *want]))
    SETTINGS.write_text(json.dumps(conf, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def logged_in() -> set[str]:
    """Поставщики, в которые оболочка уже вошла своими средствами (`opencode auth login`)."""
    try:
        got = json.loads(AUTH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return set()
    return {str(k) for k in got} if isinstance(got, dict) else set()


def rungs(keys: set[str] | None = None) -> dict:
    """Какие ступени лестницы живые, а какие пропускаются, потому что в них нечем войти.

    Нужно для одной строки при запуске. Без неё человек видит только, что отвечает не тот, кого он
    поставил наверх, — и ищет беду в лестнице, хотя беда в том, что входа нет.
    """
    try:
        got = json.loads(LADDER.read_text(encoding="utf-8"))
        all_rungs = [str(r) for r in (got.get("ladder") or [])]
    except (OSError, ValueError, AttributeError):
        all_rungs = list(DEFAULT_LADDER["ladder"])
    have = set(logged_in()) | (keys if keys is not None else {n for n in KEYS if providers.secret_get(n)})
    live = [r for r in all_rungs if r.split("/", 1)[0] in LOCAL or r.split("/", 1)[0] in have]
    return {"live": live or all_rungs, "skipped": [] if not live else [r for r in all_rungs if r not in live]}


def env() -> dict[str, str]:
    """Окружение для окна: ключи из связки, и ни одного из них на диске.

    Заодно метка `JUSTDAY_SHELL`: по ней модель внутри узнаёт, что она запущена оболочкой, а не
    разговаривает с человеком напрямую. Что из этого следует — написано в `AGENTS.md`.
    """
    out = dict(os.environ)
    out["JUSTDAY_SHELL"] = "opencode"
    for name, var in KEYS.items():
        got = providers.secret_get(name)
        if got:
            out[var] = got
    return out


def report(out) -> None:
    """Одна строка про лестницу перед запуском окна: кто отвечает и кого пропустили."""
    have = {n for n, var in KEYS.items() if out.get(var)}
    step = rungs(have)
    print("Лестница: " + " → ".join(step["live"]))
    if step["skipped"]:
        print("Пропускаю (нечем войти): " + ", ".join(step["skipped"]))
        if any(r.startswith("anthropic/") for r in step["skipped"]):
            print("  Подписка Claude в чужих оболочках запрещена с февраля 2026 — только Claude Code\n"
                  "  и claude.ai. Для anthropic здесь нужен ключ API: justday secret set anthropic.")


def claude_answers(timeout: float = 45.0) -> bool:
    """Отвечает ли Claude Code прямо сейчас — один крошечный вопрос его же программой.

    Спрашиваем официальным `claude`: подписка разрешена только в нём, и ответ на этот вопрос
    решает, за какую оболочку человеку садиться.
    """
    from . import fallback

    cfg = config.load()
    return fallback.probe(cfg, str(cfg["brain"].get("home_provider") or "claude"), timeout=timeout)


def work(args: list[str] | None = None, *, force: str = "") -> int:
    """Сесть за работу: Claude Code, пока он отвечает, и оболочка, когда у него кончился лимит.

    Зачем это одной командой. Одной оболочкой на всё обойтись нельзя: подписка Claude работает
    только в Claude Code, а когда она кончилась, работать всё равно надо. Выбирать руками значит
    каждый раз сначала наткнуться на отказ. Поэтому выбирает команда, а человек просто садится.
    """
    if force != "shell" and (force == "claude" or claude_answers()):
        cli = shutil.which("claude")
        if cli:
            print("Claude отвечает — работаем в Claude Code.")
            os.execve(cli, [cli, *(args or [])], dict(os.environ))
            return 0
        print("Claude Code не установлен — открываю оболочку.")
    else:
        print("У Claude кончился лимит (или он не отвечает) — открываю оболочку.\n"
              "Прочитай ПЕРЕДАЧА.md: там что делалось до тебя и что дальше.")
    return run(args)


def run(args: list[str] | None = None) -> int:
    ensure()
    cli = shutil.which("opencode") or str(Path.home() / ".local" / "bin" / "opencode")
    if not Path(cli).exists():
        print("OpenCode не установлен: npm install -g opencode-ai")
        return 1
    out = env()
    report(out)
    os.execve(cli, [cli, *(args or [])], out)
    return 0        # сюда не возвращаются
