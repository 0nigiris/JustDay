"""Права голосового мозга (brain/settings.json): что он может сделать без вопроса (Р-2, Р-10).

Правила проверяет Claude Code, а не наш код, поэтому здесь его сопоставление повторено так, как оно
описано: `*` — любые символы, `:*` в конце — то же, что ` *`; deny сильнее ask, ask сильнее allow.
Живая проверка с настоящим `claude -p` описана в ПЕРЕДАЧА.md (5 октября)."""

import fnmatch
import json
from pathlib import Path

SETTINGS = json.loads((Path(__file__).parents[1] / "brain" / "settings.json").read_text(encoding="utf-8"))


def _hits(kind: str, command: str) -> bool:
    for rule in SETTINGS["permissions"][kind]:
        if not rule.startswith("Bash(") or not rule.endswith(")"):
            continue
        pat = rule[5:-1]
        if pat.endswith(":*"):
            pat = pat[:-2] + "*"
        if fnmatch.fnmatchcase(command, pat):
            return True
    return False


def _runs_silently(command: str) -> bool:
    return not _hits("deny", command) and not _hits("ask", command) and _hits("allow", command)


def test_the_brain_could_read_api_keys_with_plain_cat():
    """Запрет стоял только на инструмент Read, а `cat`/`grep`/`jq` были разрешены — ключи читались."""
    secrets = ["~/.config/justday/secrets.env", "/home/oni/.claude/.credentials.json",
               "~/.local/share/opencode/auth.json", "~/.claude.json", "~/.ssh/id_ed25519", "/proc/self/environ"]
    for reader in ("cat", "head -n 5", "tail", "grep -r KEY", "jq .", "rg token"):
        for path in secrets:
            assert _hits("deny", f"{reader} {path}"), f"{reader} {path}"
    for leak in ("printenv", "env", "echo $ANTHROPIC_AUTH_TOKEN", "qdbus org.kde.kwalletd6"):
        assert _hits("deny", leak), leak


def test_a_web_page_could_carry_data_out_in_one_silent_step():
    """WebFetch без вопроса — вынос прочитанного наружу за один ход."""
    assert "WebFetch" in SETTINGS["permissions"]["ask"]
    assert "WebFetch" not in SETTINGS["permissions"]["allow"]


def test_allow_rules_that_promised_more_than_they_did():
    """`flatpak list|info|run` не совпадал ни с чем, `java` и `jii install` запускали чужой код без
    вопроса, `find` с -delete/-exec проходил как безобидный поиск."""
    for ok in ("flatpak list", "flatpak run org.telegram.desktop", "dnf search kitty", "ls ~", "justday status"):
        assert _runs_silently(ok), ok
    for bad in ("java -jar x.jar", "jii install foo", "find ~ -name x -delete", "find . -exec rm {} ;",
                "justday approve", "pactl load-module module-native-protocol-tcp"):
        assert not _runs_silently(bad), bad
