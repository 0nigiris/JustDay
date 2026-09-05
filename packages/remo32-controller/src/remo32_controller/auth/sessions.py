"""Сессии на JWT.

Токен кладётся в httpOnly-cookie: JavaScript до него не дотягивается,
значит XSS не уносит сессию.

Ключ подписи хранится в файле рядом с данными и создаётся автоматически
при первом запуске. Потеря ключа означает лишь то, что придётся войти
заново.
"""

from __future__ import annotations

import os
import secrets
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import jwt

from remo32_core.errors import UnauthorizedError
from remo32_core.log import get_logger

log = get_logger("controller.auth.sessions")

ALGORITHM = "HS256"
ISSUER = "remo32-controller"


class SessionManager:
    def __init__(self, secret: str, *, ttl_hours: int = 720) -> None:
        if len(secret) < 32:
            raise ValueError("ключ подписи сессий должен быть не короче 32 символов")
        self._secret = secret
        self._ttl = timedelta(hours=ttl_hours)
        # Отозванные идентификаторы сессий. Хранятся в памяти: перезапуск
        # контроллера и так делает все прежние сессии бесполезными не сразу,
        # но выход из системы обязан действовать немедленно.
        self._revoked: set[str] = set()

    def issue(self, subject: str = "owner", **claims: Any) -> tuple[str, datetime]:
        now = datetime.now(UTC)
        expires = now + self._ttl
        payload = {
            "iss": ISSUER,
            "sub": subject,
            "iat": int(now.timestamp()),
            "exp": int(expires.timestamp()),
            "jti": secrets.token_urlsafe(12),
            **claims,
        }
        return jwt.encode(payload, self._secret, algorithm=ALGORITHM), expires

    def verify(self, token: str) -> dict[str, Any]:
        try:
            payload: dict[str, Any] = jwt.decode(
                token, self._secret, algorithms=[ALGORITHM], issuer=ISSUER
            )
        except jwt.ExpiredSignatureError as exc:
            raise UnauthorizedError("сессия истекла, войдите заново") from exc
        except jwt.InvalidTokenError as exc:
            raise UnauthorizedError("недействительная сессия") from exc

        if payload.get("jti") in self._revoked:
            raise UnauthorizedError("сессия завершена")
        return payload

    def revoke(self, token: str) -> None:
        try:
            payload = jwt.decode(
                token, self._secret, algorithms=[ALGORITHM], options={"verify_exp": False}
            )
        except jwt.InvalidTokenError:
            return
        if (jti := payload.get("jti")) is not None:
            self._revoked.add(str(jti))

    @property
    def ttl_seconds(self) -> int:
        return int(self._ttl.total_seconds())


def load_or_create_secret(path: Path) -> str:
    """Читает ключ подписи, создавая его при первом запуске.

    Файл создаётся сразу с правами 0600 — между созданием и выставлением
    прав не должно быть окна, в которое его сможет прочитать кто-то ещё.
    """
    path = path.expanduser()
    if path.is_file():
        if path.stat().st_mode & 0o077:
            raise ValueError(f"ключ сессий доступен посторонним: chmod 600 {path}")
        return path.read_text(encoding="utf-8").strip()

    path.parent.mkdir(parents=True, exist_ok=True)
    secret = secrets.token_urlsafe(48)
    fd = os.open(path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8") as fh:
        fh.write(secret)
    log.info("создан новый ключ подписи сессий", path=str(path))
    return secret
