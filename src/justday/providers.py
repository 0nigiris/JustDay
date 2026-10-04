"""Which model drives the agent. Claude Code stays the harness (tools, skills, memory, sessions); only the
model endpoint changes, through Claude Code's own ANTHROPIC_BASE_URL support. Memory lives in files on disk,
so it is the same whichever model is selected.

Secrets (API keys, the mail app password) live in the desktop keyring (libsecret → KWallet/GNOME Keyring),
never in config files or in the assistant's memory.
"""
from __future__ import annotations

import fnmatch
import os
import re
import shlex
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
# Не-Claude мозгу классификатор не помогает, и раньше здесь сравнивали начало строки: `FOO=1 rm -r x`,
# `env rm -fr x`, `/bin/dd`, `rm --recursive --force`, `git -C . push -f` проходили мимо ask, а
# `echo x > ~/.bashrc` считался разрешённым `echo` (Р-3). Теперь команда разбирается как её разберёт
# shell: по кавычкам, на простые команды, без префиксов окружения и обёрток, с путём к программе.
_RULE = re.compile(r"^Bash\((.+)\)$")
_SPLIT = {"&&", "||", ";", "|", "&", "|&", ";;", "(", ")"}
_REDIRECT = {">", ">>", ">|", "&>", "&>>", "<>"}
_WRAPPERS = {"env", "command", "exec", "nice", "nohup", "time", "stdbuf", "setsid", "doas", "ionice", "chrt",
             "timeout", "xargs", "unbuffer", "builtin"}
# Опции обёрток, которые берут следующее слово: `env -u X rm`, `nice -n 5 rm`, `xargs -I {} rm`.
_WRAPPER_ARG = {"-u", "-C", "-n", "-c", "-k", "-s", "-p", "-o", "-e", "-t", "-d", "-L", "-P", "-I", "-E", "-S"}
_SHELLS = {"sh", "bash", "zsh", "dash", "fish", "ksh"}
_ASSIGN = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def _simple_commands(cmd: str) -> tuple[list[list[str]], bool]:
    """Простые команды как списки слов (программа первой) и флаг «пишет в файл перенаправлением».

    Подстановка `$(…)`/`…`/`<(…)` разбирается как ещё одна команда: внутри неё может быть что угодно."""
    inner = re.findall(r"\$\(([^()]*)\)|`([^`]*)`|<\(([^()]*)\)", cmd)
    lexer = shlex.shlex(cmd.replace("\n", " ; "), posix=True, punctuation_chars=True)
    lexer.whitespace_split = True
    try:
        tokens = list(lexer)
    except ValueError:  # незакрытая кавычка: разобрать нельзя — значит и разрешить нельзя
        return [[cmd]], True
    out, cur, writes, i = [], [], False, 0
    while i < len(tokens):
        tok = tokens[i]
        if tok in _SPLIT:
            out.append(cur)
            cur = []
        elif tok in _REDIRECT or re.fullmatch(r"\d>>?", tok):
            target = tokens[i + 1] if i + 1 < len(tokens) else ""
            if target not in ("/dev/null", "&1", "&2", "/dev/stdout", "/dev/stderr") and not target.startswith("&"):
                writes = True
            i += 1
        elif tok in ("<", "<<", "<<<") or re.fullmatch(r"\d<", tok):
            i += 1
        else:
            cur.append(tok)
        i += 1
    out.append(cur)
    out = [_unwrap(c) for c in out if c]
    # `bash -c "rm -rf x"` и `eval "rm -rf x"`: настоящая команда спрятана в одном слове.
    for c in list(out):
        flag = next((i for i, w in enumerate(c) if re.fullmatch(r"-[a-z]*c", w)), None) if c[0] in _SHELLS else None
        if c[0] != "eval" and flag is None:
            continue
        body = " ".join(c[1:]) if c[0] == "eval" else " ".join(c[flag + 1:flag + 2])
        more, w = _simple_commands(body)
        out += more
        writes |= w
    for groups in inner:
        for part in groups:
            if part:
                more, w = _simple_commands(part)
                out += more
                writes |= w
    return [c for c in out if c], writes


def _unwrap(words: list[str]) -> list[str]:
    """`FOO=1 env -i nice -n 5 /bin/dd …` → `dd …`: префиксы окружения и обёртки ничего не меняют в том,
    что команда сделает."""
    while words:
        head = words[0]
        if _ASSIGN.match(head) or head in ("!", "{", "}"):
            words = words[1:]
        elif os.path.basename(head) in _WRAPPERS:
            words = words[1:]
            while words and (words[0].startswith("-") or _ASSIGN.match(words[0]) or re.fullmatch(r"[\d.]+[smhd]?",
                                                                                                    words[0])):
                words = words[2:] if words[0] in _WRAPPER_ARG else words[1:]
        else:
            break
    if words:
        words = [os.path.basename(words[0]), *words[1:]]
    if words[:1] == ["git"]:  # `git -C . push -f`: общие опции git до подкоманды
        rest = words[1:]
        while rest and rest[0].startswith("-"):
            rest = rest[2:] if rest[0] in ("-C", "-c", "--git-dir", "--work-tree") else rest[1:]
        words = ["git", *rest]
    return words


def _matches(rule_body: str, words: list[str]) -> bool:
    """Сопоставление правила так, как его делает Claude Code: `*` — что угодно, `x:*` — `x` или `x …`
    (граница слова: `ps:*` не пускает `psql`)."""
    line = " ".join(words)
    if rule_body.endswith(":*"):
        head = rule_body[:-2]
        return fnmatch.fnmatchcase(line, head) or fnmatch.fnmatchcase(line, head + " *")
    return fnmatch.fnmatchcase(line, rule_body)


def _destructive(words: list[str]) -> bool:
    """То, что опасно в любой записи, а не только в той, что вписана в ask."""
    prog, args = words[0], words[1:]
    flags = [a for a in args if a.startswith("-")]
    if prog == "rm":
        return any(a in ("--recursive", "--force") or (not a.startswith("--") and set(a[1:]) & set("rRf"))
                   for a in flags)
    if prog == "find":
        return any(a in ("-delete", "-exec", "-execdir", "-ok", "-okdir") for a in args)
    if prog == "git" and args[:1] == ["push"]:
        return any(a in ("-f", "--force", "--force-with-lease", "--mirror", "--delete", "-d") or a.startswith("+")
                   or a.startswith("--force") for a in args[1:])
    return prog in ("dd", "mkfs", "shred", "wipefs", "sudo", "pkexec", "su") or prog.startswith("mkfs.")


def risky(tool: str, inp: dict, ask_rules: list[str]) -> bool:
    """True if a call matches one of the `ask` rules (destructive shell commands, publishing…)."""
    if tool != "Bash":
        return False
    commands, _ = _simple_commands(inp.get("command", ""))
    bodies = [m.group(1) for r in ask_rules if (m := _RULE.match(r))]
    return any(_destructive(c) or any(_matches(b, c) for b in bodies) for c in commands)


def all_allowed(tool: str, inp: dict, allow_rules: list[str]) -> bool:
    """True, если команда целиком собрана из того, что человек уже разрешил.

    Зачем это нужно. Разрешение `Bash(cat:*)` работает, пока команда одна. Стоит склеить две
    разрешённые — `cat /sys/... && echo ---` — и статический разбор сдаётся: «содержит подстановку
    команды», «содержит синтаксис (&), который нельзя разобрать», — и человека дёргают вопросом
    про `cat`. Здесь мы смотрим **каждый** кусок: разрешены все — вопроса нет; хоть один нет
    (`sudo`, `rm`) — вопрос как обычно. Запись в файл перенаправлением — всегда вопрос: `echo`
    разрешён, а `echo x > ~/.bashrc` уже нет.
    """
    if tool != "Bash":
        return tool in allow_rules
    commands, writes = _simple_commands(inp.get("command", ""))
    bodies = [m.group(1) for r in allow_rules if (m := _RULE.match(r))]
    if writes or not commands or not bodies:
        return False
    return all(any(_matches(b, c) for b in bodies) for c in commands)
