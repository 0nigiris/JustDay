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
KEYS = {"openrouter": "OPENROUTER_API_KEY", "groq": "GROQ_API_KEY", "deepseek": "DEEPSEEK_API_KEY"}

CONF_DIR = Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")) / "opencode"
PLUGIN = CONF_DIR / "plugin" / "justday-ladder.js"
LADDER = CONF_DIR / "justday-ladder.json"
SETTINGS = CONF_DIR / "opencode.json"
RULES = CONF_DIR / "ПРАВИЛА.md"
CLAUDE_HOME = Path.home() / ".claude"

DEFAULT_LADDER = {
    # Порядок — это и есть приоритет: сверху тот, кем хочется думать всегда.
    "ladder": ["anthropic/claude-opus-4-5", "anthropic/claude-sonnet-4-5", "anthropic/claude-haiku-4-5"],
    "tiny": "",
    "probeMinutes": 15,
    "tinyMaxChars": 80,
    "quiet": False,
}


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


def env() -> dict[str, str]:
    """Окружение для окна: ключи из связки, и ни одного из них на диске."""
    out = dict(os.environ)
    for name, var in KEYS.items():
        got = providers.secret_get(name)
        if got:
            out[var] = got
    return out


def run(args: list[str] | None = None) -> int:
    ensure()
    cli = shutil.which("opencode") or str(Path.home() / ".local" / "bin" / "opencode")
    if not Path(cli).exists():
        print("OpenCode не установлен: npm install -g opencode-ai")
        return 1
    os.execve(cli, [cli, *(args or [])], env())
    return 0        # сюда не возвращаются
