"""Флешка: воткнул в чужой компьютер, поработал, вынул — следов не осталось.

Зачем. Своя машина есть не всегда: чужой ноутбук, компьютер в другой комнате, рабочее место, куда
ничего ставить нельзя. Хочется воткнуть флешку и получить своего ассистента — со своим характером,
своей памятью и своими ключами, — а вынув её, не оставить за собой ничего.

Что значит «ничего». Ни конфига в ~/.config, ни данных в ~/.local/share, ни записей в связке
ключей хозяина, ни служб systemd, ни горячих клавиш в его плазме. Всё это умеет переехать на саму
флешку: XDG-переменные уводят туда конфиг, данные, состояние и кэш, а службы при таком запуске не
ставятся вовсе — ассистент живёт, пока открыто окно, и уходит вместе с ним.

Ключи. На флешке они лежат зашифрованными, и расшифровываются только в память работающего
процесса: пароль спрашивается при запуске и никуда не записывается. Потерянная флешка — это
потерянная флешка, а не потерянные ключи.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

from . import config

RUN = "justday-portable.sh"
SECRETS = "secrets.enc"
# Шифруем тем, что есть на любой машине. Явный pbkdf2 и соль — пароль у человека будет человеческий,
# а не случайные тридцать знаков, и без растяжения ключа такой пароль перебирается за вечер.
ENC = ["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-iter", "600000", "-salt"]


def _openssl(args: list[str], data: bytes, passphrase: str) -> bytes:
    if not shutil.which("openssl"):
        raise RuntimeError("нет openssl — зашифровать ключи нечем")
    r = subprocess.run([*ENC, *args, "-pass", "env:JD_PASS"], input=data, capture_output=True,
                       env={**os.environ, "JD_PASS": passphrase}, timeout=60)
    if r.returncode:
        raise RuntimeError((r.stderr.decode("utf-8", "replace").strip() or "openssl отказался")[:200])
    return r.stdout


def seal(secrets: dict, passphrase: str) -> bytes:
    """Зашифровать ключи для флешки."""
    return _openssl([], json.dumps(secrets, ensure_ascii=False).encode("utf-8"), passphrase)


def unseal(blob: bytes, passphrase: str) -> dict:
    """Расшифровать ключи с флешки. Пароль неверный — честная ошибка, а не пустой словарь."""
    got = _openssl(["-d"], blob, passphrase)
    return json.loads(got.decode("utf-8"))


SCRIPT = """#!/usr/bin/env bash
# JustDay с флешки. Ничего не ставит и ничего не оставляет на этой машине.
#
# Всё, что ассистент пишет о себе — настройки, память, состояние, кэш, — уезжает сюда же, на
# флешку: XDG-переменные ниже уводят туда все четыре места, куда пишут программы в Linux.
# Служб systemd тут нет нарочно: ассистент живёт, пока открыто это окно, и уходит вместе с ним.
set -euo pipefail
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

export XDG_CONFIG_HOME="$HERE/home/config"
export XDG_DATA_HOME="$HERE/home/data"
export XDG_STATE_HOME="$HERE/home/state"
export XDG_CACHE_HOME="$HERE/home/cache"
mkdir -p "$XDG_CONFIG_HOME" "$XDG_DATA_HOME" "$XDG_STATE_HOME" "$XDG_CACHE_HOME"

# Ключи лежат зашифрованными рядом. Пароль спрашивается здесь и живёт только в этом процессе:
# в файлы он не попадает, в связку ключей хозяина машины — тем более.
if [[ -f "$HERE/secrets.enc" ]]; then
  read -rsp "Пароль флешки: " JD_PASS </dev/tty; echo
  export JD_PASS
  export JUSTDAY_SECRETS="$HERE/secrets.enc"
fi

exec "$HERE/app/.venv/bin/justday" "${@:-ui}"
"""

READ_ME = """# Флешка JustDay

Воткнуть, запустить `justday-portable.sh`, работать. Вынуть — на чужой машине не останется ничего:
настройки, память и ключи лежат здесь же, на флешке.

- `app/` — сам JustDay.
- `home/` — его настройки, память и состояние. Это то, что на обычной машине лежит в ~/.config и
  ~/.local/share.
- `secrets.enc` — ключи, зашифрованные паролем. Пароль спрашивается при запуске и нигде не
  сохраняется: потерянная флешка — это потерянная флешка, а не потерянные ключи.

Чего здесь нет нарочно: служб systemd и горячих клавиш. Ассистент живёт, пока открыто окно.
"""


def init(dest: str, secrets: dict | None = None, passphrase: str = "") -> dict:
    """Собрать флешку в этой папке. Папка должна существовать — создавать разделы мы не станем."""
    root = Path(dest).expanduser()
    if not root.is_dir():
        return {"ok": False, "error": f"нет такой папки: {root}"}
    app = root / "app"
    for part in ("home/config", "home/data", "home/state", "home/cache"):
        (root / part).mkdir(parents=True, exist_ok=True)

    src = config.REPO_DIR
    if not (src / "pyproject.toml").exists():
        return {"ok": False, "error": "не нашёл сам JustDay — откуда копировать?"}
    if not app.exists():
        shutil.copytree(src, app, ignore=shutil.ignore_patterns(
            ".git", ".venv", "__pycache__", "*.pyc", "graphify-out", "node_modules"))

    run = root / RUN
    run.write_text(SCRIPT, encoding="utf-8")
    run.chmod(0o755)
    (root / "README.md").write_text(READ_ME, encoding="utf-8")

    out = {"ok": True, "where": str(root), "run": str(run), "app": str(app)}
    if secrets:
        if not passphrase:
            return {"ok": False, "error": "ключи без пароля на флешку не кладутся"}
        (root / SECRETS).write_bytes(seal(secrets, passphrase))
        (root / SECRETS).chmod(0o600)
        out["secrets"] = len(secrets)
    return out
