"""Which model drives the agent. Claude Code stays the harness (tools, skills, memory, sessions); only the
model endpoint changes, through Claude Code's own ANTHROPIC_BASE_URL support. Memory lives in files on disk,
so it is the same whichever model is selected.

Secrets (API keys, the mail app password) live in the desktop keyring (libsecret → KWallet/GNOME Keyring),
never in config files or in the assistant's memory.
"""
from __future__ import annotations

import re
import shutil
import subprocess

# name → (base url, secret name or fixed token, description)
PROVIDERS: dict[str, dict] = {
    "claude": {"desc": "подписка Claude / ключ Anthropic через ваш логин в Claude Code"},
    "ollama": {"base_url": "http://127.0.0.1:11434", "token": "ollama", "context": 65536,  # = OLLAMA_CONTEXT_LENGTH
               "desc": "локальная модель на вашей видеокарте, наружу ничего не уходит"},
    "openrouter": {"base_url": "https://openrouter.ai/api", "secret": "openrouter",
                   "desc": "сотни моделей, есть бесплатные (суффикс :free); ключ на openrouter.ai/keys"},
    "deepseek": {"base_url": "https://api.deepseek.com/anthropic", "secret": "deepseek",
                 "desc": "DeepSeek напрямую; ключ на platform.deepseek.com"},
    "custom": {"secret": "custom", "desc": "любой Anthropic-совместимый адрес (brain.base_url), например LiteLLM"},
}

SECRET_ATTRS = ["service", "justday"]


def secret_get(name: str) -> str:
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


# ---- permission policy for models without Claude Code's auto-mode classifier ----
_RULE = re.compile(r"^Bash\((.+?)(?::\*)?\)$")


def risky(tool: str, inp: dict, ask_rules: list[str]) -> bool:
    """True if a call matches one of the `ask` rules (destructive shell commands, publishing…)."""
    if tool != "Bash":
        return False
    cmd = inp.get("command", "")
    parts = [p.strip() for p in re.split(r"&&|\|\||;|\||\n|\$\(|`", cmd) if p.strip()]
    for rule in ask_rules:
        m = _RULE.match(rule)
        if m and any(p.startswith(m.group(1)) or p.startswith("sudo " + m.group(1)) for p in parts):
            return True
    return bool(re.search(r"\brm\s+-[a-zA-Z]*[rf]", cmd))
