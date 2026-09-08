"""Подтверждение входа и sudo с телефона.

Задача та же, что решают часы Apple для Mac: компьютер спрашивает
разрешение, человек подтверждает на устройстве, которое уже у него в руке.

Пароль здесь не хранится и не передаётся — ни в открытом виде, ни в
зашифрованном. Подтверждение работает через PAM: модуль ``pam_exec``
запускает скрипт, тот дожидается одобрения и возвращает успех вместо
проверки пароля. Так удобнее и так же нечего красть.

Два режима, потому что случаи разные:

* **Запрос** — компьютер уже спрашивает (``sudo`` в терминале). Он создаёт
  запрос и ждёт; телефон показывает, что именно подтверждается, и от кого.
* **Предварительное одобрение** — на экране входа ждать нельзя, там человек
  стоит перед формой пароля. Он заранее нажимает «разблокировать» на
  телефоне, и следующая попытка входа проходит.

Обмен идёт через файлы в каталоге пользователя, а не через сеть: PAM-скрипт
запускается от root в момент, когда сеть может быть ещё не поднята, а
файловая система есть всегда.
"""

from __future__ import annotations

import json
import os
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from remo32_core.log import get_logger

log = get_logger("agent.approvals")

ApprovalKind = Literal["login", "sudo", "other"]
ApprovalState = Literal["pending", "approved", "denied"]

DEFAULT_DIR = Path("~/.local/share/remo32/approvals")

# Сколько живёт запрос, если срок не задан явно. Минуты здесь не нужны:
# человек либо подтверждает сразу, либо не подтверждает вовсе, а
# просроченное одобрение, лежащее до утра, — это и есть дыра.
DEFAULT_TTL_SECONDS = 60


@dataclass
class Approval:
    """Один запрос на подтверждение."""

    id: str
    kind: ApprovalKind
    state: ApprovalState = "pending"
    user: str = ""
    source: str = field(default="", metadata={"help": "tty, хост, откуда пришёл запрос"})
    command: str = ""
    created_at: float = 0.0
    expires_at: float = 0.0

    @property
    def expired(self) -> bool:
        return time.time() > self.expires_at

    @property
    def seconds_left(self) -> int:
        return max(0, int(self.expires_at - time.time()))

    def to_json(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "state": self.state,
            "user": self.user,
            "source": self.source,
            "command": self.command,
            "created_at": self.created_at,
            "expires_at": self.expires_at,
            "seconds_left": self.seconds_left,
        }

    @classmethod
    def from_json(cls, data: dict[str, Any]) -> Approval:
        return cls(
            id=str(data["id"]),
            kind=data.get("kind", "other"),
            state=data.get("state", "pending"),
            user=str(data.get("user", "")),
            source=str(data.get("source", "")),
            command=str(data.get("command", "")),
            created_at=float(data.get("created_at", 0)),
            expires_at=float(data.get("expires_at", 0)),
        )


class ApprovalStore:
    """Каталог с запросами. Одновременно им пользуются агент и PAM-скрипт.

    Права здесь не украшение: одобрение — это пропуск к ``sudo``. Каталог
    0700, файлы 0600. Скрипт запускается от root и после записи передаёт
    файл владельцу, иначе агент, работающий от пользователя, не сможет его
    изменить.
    """

    def __init__(self, directory: Path | str = DEFAULT_DIR, enabled: bool = False) -> None:
        self._dir = Path(directory).expanduser()
        self.enabled = enabled

    @property
    def directory(self) -> Path:
        return self._dir

    def _ensure_dir(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)
        self._dir.chmod(0o700)

    def _path(self, approval_id: str) -> Path:
        # Идентификатор мы порождаем сами, но он приходит и снаружи, из
        # адреса запроса: имя файла берём строго безопасное.
        safe = "".join(c for c in approval_id if c.isalnum() or c in "-_")[:64]
        if not safe:
            raise ValueError("пустой идентификатор подтверждения")
        return self._dir / f"{safe}.json"

    # --- чтение ---------------------------------------------------------

    def list(self) -> list[Approval]:
        """Живые запросы, свежие первыми. Просроченные попутно убираются."""
        if not self._dir.is_dir():
            return []

        found: list[Approval] = []
        for path in self._dir.glob("*.json"):
            approval = self._read(path)
            if approval is None:
                continue
            if approval.expired:
                path.unlink(missing_ok=True)
                continue
            found.append(approval)
        return sorted(found, key=lambda a: a.created_at, reverse=True)

    def get(self, approval_id: str) -> Approval | None:
        approval = self._read(self._path(approval_id))
        if approval is None or approval.expired:
            return None
        return approval

    @staticmethod
    def _read(path: Path) -> Approval | None:
        try:
            return Approval.from_json(json.loads(path.read_text(encoding="utf-8")))
        except (OSError, ValueError, KeyError) as exc:
            log.warning("подтверждение не читается", path=str(path), error=str(exc))
            return None

    # --- запись ---------------------------------------------------------

    def create(
        self,
        kind: ApprovalKind,
        *,
        state: ApprovalState = "pending",
        user: str = "",
        source: str = "",
        command: str = "",
        ttl_seconds: int = DEFAULT_TTL_SECONDS,
    ) -> Approval:
        self._ensure_dir()
        now = time.time()
        approval = Approval(
            id=secrets.token_urlsafe(9),
            kind=kind,
            state=state,
            user=user,
            source=source,
            command=command,
            created_at=now,
            expires_at=now + ttl_seconds,
        )
        self._write(approval)
        log.info("создано подтверждение", kind=kind, state=state, id=approval.id)
        return approval

    def decide(self, approval_id: str, approved: bool) -> Approval:
        approval = self.get(approval_id)
        if approval is None:
            raise KeyError(approval_id)
        approval.state = "approved" if approved else "denied"
        self._write(approval)
        log.info("решение по подтверждению", id=approval.id, state=approval.state)
        return approval

    def consume(self, approval_id: str) -> None:
        """Убирает использованное одобрение.

        Одноразовость — половина всей защиты: иначе одно нажатие на телефоне
        открывало бы sudo до конца срока, сколько бы раз его ни попросили.
        """
        self._path(approval_id).unlink(missing_ok=True)

    def _write(self, approval: Approval) -> None:
        self._ensure_dir()
        path = self._path(approval.id)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(approval.to_json(), ensure_ascii=False), encoding="utf-8")
        tmp.chmod(0o600)
        tmp.replace(path)

        # Скрипт работает от root: без передачи владельца агент, живущий от
        # пользователя, не сможет отметить запрос подтверждённым.
        if os.geteuid() == 0:
            owner = _owner_of(self._dir)
            if owner is not None:
                os.chown(path, *owner)


def _owner_of(path: Path) -> tuple[int, int] | None:
    try:
        stat = path.stat()
    except OSError:
        return None
    return stat.st_uid, stat.st_gid
