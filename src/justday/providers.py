"""Which model drives the agent. Claude Code stays the harness (tools, skills, memory, sessions); only the
model endpoint changes, through Claude Code's own ANTHROPIC_BASE_URL support. Memory lives in files on disk,
so it is the same whichever model is selected.

Secrets (API keys, the mail app password) live in the desktop keyring (libsecret → KWallet/GNOME Keyring),
never in config files or in the assistant's memory.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

# name → (base url, secret name or fixed token, description)
PROVIDERS: dict[str, dict] = {
    "claude": {"desc": "подписка Claude / ключ Anthropic через ваш логин в Claude Code"},
    "ollama": {"base_url": "http://127.0.0.1:11434", "token": "ollama", "context": 65536,  # = OLLAMA_CONTEXT_LENGTH
               "desc": "локальная модель на вашей видеокарте, наружу ничего не уходит"},
    # the same local Ollama server forwards `…:cloud` models to ollama.com; the sign-in lives in Ollama, not here
    "ollama_cloud": {"base_url": "http://127.0.0.1:11434", "token": "ollama", "context": 128000, "cloud_signin": True,
                     "desc": "бесплатно: большие модели в облаке Ollama (Kimi, GLM, DeepSeek). Бесплатный аккаунт "
                             "без карты, лимиты сбрасываются каждые 5 часов; запросы уходят на ollama.com"},
    "openrouter": {"base_url": "https://openrouter.ai/api", "secret": "openrouter",
                   "desc": "сотни моделей, есть бесплатные (суффикс :free, 50 запросов в день); ключ на openrouter.ai/keys"},
    "deepseek": {"base_url": "https://api.deepseek.com/anthropic", "secret": "deepseek",
                 "desc": "DeepSeek напрямую; ключ на platform.deepseek.com"},
    "custom": {"secret": "custom", "desc": "любой Anthropic-совместимый адрес (brain.base_url), например LiteLLM"},
}

SECRET_ATTRS = ["service", "justday"]


_portable: dict | None = None


def _from_stick(name: str) -> str:
    """Ключ с флешки: там он лежит зашифрованным, а пароль живёт только в этом процессе.

    На чужой машине в связку ключей хозяина мы не пишем ничего — иначе «вынул флешку, следов не
    осталось» было бы неправдой: ключ остался бы у него.
    """
    global _portable
    blob = os.environ.get("JUSTDAY_SECRETS", "")
    passphrase = os.environ.get("JD_PASS", "")
    if not blob or not passphrase:
        return ""
    if _portable is None:
        from . import portable
        try:
            _portable = portable.unseal(Path(blob).read_bytes(), passphrase)
        except (OSError, RuntimeError, ValueError):
            _portable = {}
    return str(_portable.get(name) or "")


def secret_get(name: str) -> str:
    got = _from_stick(name)
    if got:
        return got
    if not shutil.which("secret-tool"):
        return ""
    r = subprocess.run(["secret-tool", "lookup", *SECRET_ATTRS, "key", name], capture_output=True, text=True)
    return r.stdout.strip()


def secret_set(name: str, value: str) -> None:
    subprocess.run(["secret-tool", "store", "--label", f"JustDay: {name}", *SECRET_ATTRS, "key", name],
                   input=value, text=True, check=True)


def is_claude(cfg: dict) -> bool:
    return cfg["brain"].get("provider", "claude") == "claude"


def env(cfg: dict) -> dict[str, str]:
    """Environment for every Claude Code process JustDay starts (brain and background workers)."""
    b = cfg["brain"]
    out = {"ENABLE_CLAUDEAI_MCP_SERVERS": "false"}  # claude.ai connectors (Gmail, Drive…) would send data to the cloud
    name = b.get("provider", "claude")
    if name == "claude":
        return out
    p = PROVIDERS.get(name)
    if p is None:
        raise ValueError(f"unknown brain.provider {name!r}; choose from {', '.join(PROVIDERS)}")
    token = p.get("token") or secret_get(p["secret"])
    if not token:
        raise RuntimeError(f"no API key for {name}: run `justday secret set {p['secret']}`")
    model = b["model"]
    out.update({
        "ANTHROPIC_BASE_URL": b.get("base_url") or p.get("base_url", ""),
        "ANTHROPIC_AUTH_TOKEN": token,
        "ANTHROPIC_API_KEY": "",
        # every alias and background task on the chosen model, otherwise Claude Code asks for claude-* ids
        "ANTHROPIC_DEFAULT_OPUS_MODEL": model,
        "ANTHROPIC_DEFAULT_SONNET_MODEL": model,
        "ANTHROPIC_DEFAULT_HAIKU_MODEL": model,
        "CLAUDE_CODE_SUBAGENT_MODEL": model,
        "CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC": "1",
    })
    # unknown model ids get a 200k window assumption; tell Claude Code the real one so it compacts in time
    context = b.get("context_tokens") or p.get("context")
    if context:
        out["CLAUDE_CODE_MAX_CONTEXT_TOKENS"] = str(context)
    return out


OLLAMA = "http://127.0.0.1:11434"


def cloud_account() -> dict:
    """Is the local Ollama signed in to ollama.com? If not, the link that connects this computer to an account."""
    import json
    import urllib.error
    import urllib.request

    try:
        with urllib.request.urlopen(urllib.request.Request(f"{OLLAMA}/api/me", method="POST", data=b"{}"), timeout=5) as r:
            me = json.loads(r.read() or b"{}")
        return {"signed_in": True, "user": me.get("name") or me.get("email") or ""}
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read() or b"{}")
        except ValueError:
            body = {}
        return {"signed_in": False, "signin_url": body.get("signin_url", "")}
    except OSError:
        return {"signed_in": False, "signin_url": "", "error": "Ollama не запущена (systemctl --user start justday-ollama)"}


def ensure_cloud_model(model: str) -> None:
    """A `:cloud` model needs its (tiny) manifest in the local Ollama before the Anthropic endpoint accepts it."""
    import json
    import urllib.request

    body = json.dumps({"model": model, "stream": False}).encode()
    try:
        urllib.request.urlopen(urllib.request.Request(f"{OLLAMA}/api/pull", data=body, method="POST"), timeout=60).read()
    except OSError:
        pass  # the brain reports the real error on the first request


# Кто вправе нажать «да». Мозг, его фоновые задачи и любая другая нейросеть на машине — нет:
# `justday job start x -- "sleep 3; justday approve"` подтверждал опасную команду сам себе (Р-1).
AI_PROCESSES = {"claude", "opencode", "codex"}


def spawned_by_ai(pid: int, daemon: int) -> bool:
    """True, если процесс — потомок демона (мозг, задачи, воркеры) или любой нейросети.

    Островок, телефонная служба и терминал человека живут под systemd и сюда не попадают;
    программы, которые демон открывает, уходят в свой scope через systemd-run и тоже."""
    while pid > 1:
        if pid == daemon:
            return True
        try:
            stat = Path(f"/proc/{pid}/stat").read_text()
        except OSError:
            return False
        if stat[stat.index("(") + 1:stat.rindex(")")] in AI_PROCESSES:
            return True
        pid = int(stat[stat.rindex(")") + 2:].split()[1])
    return False


# ---- permission policy for models without Claude Code's auto-mode classifier ----
_RULE = re.compile(r"^Bash\((.+?)(?::\*)?\)$")


def _pieces(cmd: str) -> list[str]:
    return [p.strip() for p in re.split(r"&&|\|\||;|\||\n|\$\(|`", cmd) if p.strip()]


def risky(tool: str, inp: dict, ask_rules: list[str]) -> bool:
    """True if a call matches one of the `ask` rules (destructive shell commands, publishing…)."""
    if tool != "Bash":
        return False
    cmd = inp.get("command", "")
    parts = _pieces(cmd)
    for rule in ask_rules:
        m = _RULE.match(rule)
        if m and any(p.startswith(m.group(1)) or p.startswith("sudo " + m.group(1)) for p in parts):
            return True
    return bool(re.search(r"\brm\s+-[a-zA-Z]*[rf]", cmd))


def all_allowed(tool: str, inp: dict, allow_rules: list[str]) -> bool:
    """True, если команда целиком собрана из того, что человек уже разрешил.

    Зачем это нужно. Разрешение `Bash(cat:*)` работает, пока команда одна. Стоит склеить две
    разрешённые — `cat /sys/... && echo ---` — и статический разбор сдаётся: «содержит подстановку
    команды», «содержит синтаксис (&), который нельзя разобрать», — и человека дёргают вопросом
    про `cat`. Здесь мы смотрим **каждый** кусок: разрешены все — вопроса нет; хоть один нет
    (`sudo`, `rm`) — вопрос как обычно.
    """
    if tool != "Bash":
        return False
    parts = _pieces(inp.get("command", ""))
    if not parts:
        return False
    heads = [m.group(1) for r in allow_rules if (m := _RULE.match(r))]
    if not heads:
        return False
    return all(any(p.startswith(h) for h in heads) for p in parts)
