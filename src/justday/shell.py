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


def ensure() -> None:
    """Положить плагин на место и завести ему настройку, если её ещё нет."""
    PLUGIN.parent.mkdir(parents=True, exist_ok=True)
    src = source()
    if src.exists() and PLUGIN.resolve() != src:
        PLUGIN.unlink(missing_ok=True)
        PLUGIN.symlink_to(src)
    if not LADDER.exists():
        LADDER.write_text(json.dumps(DEFAULT_LADDER, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


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
