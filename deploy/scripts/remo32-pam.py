#!/usr/bin/env python3
"""Подтверждение входа и sudo с телефона — сторона PAM.

Запускается модулем ``pam_exec`` вместо проверки пароля. Возвращает 0,
если человек подтвердил действие на телефоне, и ненулевой код во всех
остальных случаях — тогда PAM спросит пароль как обычно.

Два режима:

``check``    Мгновенная проверка заранее выданного одобрения. Для экрана
             входа: ждать там нечего, человек уже стоит перед формой, и
             разрешение он выдал заранее, с телефона.

``request``  Создаёт запрос и ждёт ответа. Для ``sudo``: команда всё равно
             стоит и ждёт, а на телефоне видно, что именно подтверждается.

Пароль не участвует ни здесь, ни на стороне телефона: подтверждается
факт «это я», а не знание секрета.

Работает без сети и без запущенного контроллера: обмен идёт через файлы
в каталоге пользователя. В момент входа в систему сеть может быть ещё не
поднята, а файловая система есть всегда.

Скрипт не должен падать никогда. Любая неожиданность — это отказ, то есть
обычный запрос пароля, а не открытая дверь.
"""

from __future__ import annotations

import argparse
import json
import os
import pwd
import secrets
import sys
import time
from pathlib import Path

APPROVALS_SUBDIR = ".local/share/remo32/approvals"

# Сколько ждать ответа с телефона в режиме request. Дольше минуты человек
# всё равно не ждёт — он уйдёт вводить пароль руками.
DEFAULT_WAIT_SECONDS = 45
POLL_INTERVAL_SECONDS = 0.5


def log(message: str) -> None:
    """PAM собирает вывод скрипта в системный журнал."""
    print(f"remo32-pam: {message}", file=sys.stderr)


def target_user() -> str | None:
    """Кого именно пускают.

    PAM передаёт имя в PAM_USER. Полагаться на текущего пользователя
    процесса нельзя: при sudo скрипт уже работает от root.
    """
    user = os.environ.get("PAM_USER")
    return user or None


def approvals_dir(user: str) -> Path | None:
    try:
        entry = pwd.getpwnam(user)
    except KeyError:
        log(f"нет такого пользователя: {user}")
        return None
    return Path(entry.pw_dir) / APPROVALS_SUBDIR


def owner_of(user: str) -> tuple[int, int] | None:
    try:
        entry = pwd.getpwnam(user)
    except KeyError:
        return None
    return entry.pw_uid, entry.pw_gid


def read_all(directory: Path) -> list[tuple[Path, dict]]:
    if not directory.is_dir():
        return []
    found: list[tuple[Path, dict]] = []
    for path in sorted(directory.glob("*.json")):
        try:
            found.append((path, json.loads(path.read_text(encoding="utf-8"))))
        except (OSError, ValueError):
            continue
    return found


def fresh(data: dict) -> bool:
    return float(data.get("expires_at", 0)) > time.time()


def mode_check(kind: str, user: str) -> int:
    """Есть ли уже выданное одобрение нужного вида."""
    directory = approvals_dir(user)
    if directory is None:
        return 1

    for path, data in read_all(directory):
        if data.get("kind") != kind or data.get("state") != "approved":
            continue
        if not fresh(data):
            path.unlink(missing_ok=True)
            continue
        # Одноразовость — половина всей защиты: иначе одно нажатие
        # открывало бы дверь до конца срока, сколько бы раз ни попросили.
        path.unlink(missing_ok=True)
        log(f"подтверждено с телефона ({kind})")
        return 0

    return 1


def mode_request(kind: str, user: str, wait_seconds: int) -> int:
    """Создать запрос и дождаться ответа."""
    directory = approvals_dir(user)
    if directory is None:
        return 1

    try:
        directory.mkdir(parents=True, exist_ok=True)
        directory.chmod(0o700)
        owner = owner_of(user)
        if owner and os.geteuid() == 0:
            os.chown(directory, *owner)
    except OSError as exc:
        log(f"каталог подтверждений недоступен: {exc}")
        return 1

    approval_id = secrets.token_urlsafe(9)
    now = time.time()
    payload = {
        "id": approval_id,
        "kind": kind,
        "state": "pending",
        "user": user,
        # Откуда пришёл запрос: человек должен понимать, что подтверждает.
        "source": os.environ.get("PAM_TTY", "") or os.environ.get("PAM_RHOST", "") or "локально",
        "command": os.environ.get("SUDO_COMMAND", ""),
        "created_at": now,
        "expires_at": now + wait_seconds,
    }

    path = directory / f"{approval_id}.json"
    try:
        path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        path.chmod(0o600)
        if owner and os.geteuid() == 0:
            os.chown(path, *owner)
    except OSError as exc:
        log(f"запрос не создан: {exc}")
        return 1

    log(f"жду подтверждения на телефоне ({kind}, до {wait_seconds} с)")
    deadline = now + wait_seconds
    try:
        while time.time() < deadline:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except FileNotFoundError:
                log("запрос исчез")
                return 1
            except (OSError, ValueError):
                time.sleep(POLL_INTERVAL_SECONDS)
                continue

            state = data.get("state")
            if state == "approved":
                log("подтверждено с телефона")
                return 0
            if state == "denied":
                log("отклонено с телефона")
                return 1

            time.sleep(POLL_INTERVAL_SECONDS)
    finally:
        path.unlink(missing_ok=True)

    log("время вышло, спрашиваем пароль")
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Подтверждение входа и sudo с телефона")
    parser.add_argument("mode", choices=["check", "request"])
    parser.add_argument("--kind", default="sudo", choices=["login", "sudo", "other"])
    parser.add_argument("--wait", type=int, default=DEFAULT_WAIT_SECONDS)
    parser.add_argument(
        "--user",
        default=None,
        help="Обычно берётся из PAM_USER; указывается явно только при проверке вручную",
    )
    args = parser.parse_args(argv)

    user = args.user or target_user()
    if not user:
        log("неизвестно, кого пускать (нет PAM_USER)")
        return 1

    if args.mode == "check":
        return mode_check(args.kind, user)
    return mode_request(args.kind, user, max(5, min(args.wait, 300)))


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        # Скрипт, упавший с трассировкой, для PAM выглядит так же, как
        # отказ, но в журнале это нужно видеть отдельно.
        log(f"внутренняя ошибка: {exc}")
        sys.exit(1)
