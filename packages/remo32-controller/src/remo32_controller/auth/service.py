"""Служба аутентификации контроллера.

Собирает вместе пароль, passkey и сессии, а также ограничивает частоту
попыток входа: без этого пароль можно было бы подобрать перебором даже
внутри частной сети.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

from remo32_controller.auth.passwords import verify_password
from remo32_controller.auth.revocations import RevocationStore
from remo32_controller.auth.sessions import SessionManager, load_or_create_secret
from remo32_controller.auth.store import CredentialStore
from remo32_controller.auth.webauthn_flow import WebAuthnService
from remo32_controller.config import ControllerSettings
from remo32_core.errors import ForbiddenError, UnauthorizedError
from remo32_core.log import get_logger

log = get_logger("controller.auth")


@dataclass
class _Attempts:
    count: int = 0
    blocked_until: float = 0.0
    history: list[float] = field(default_factory=list)


class RateLimiter:
    """Простое ограничение попыток входа по адресу источника."""

    def __init__(self, max_attempts: int, lockout_seconds: int) -> None:
        self._max = max_attempts
        self._lockout = lockout_seconds
        self._by_key: dict[str, _Attempts] = {}

    def check(self, key: str) -> None:
        entry = self._by_key.get(key)
        if entry is None:
            return
        now = time.monotonic()
        if entry.blocked_until > now:
            raise ForbiddenError(
                f"слишком много неудачных попыток, подождите {int(entry.blocked_until - now)} с",
                retry_after_seconds=int(entry.blocked_until - now),
            )

    def record_failure(self, key: str) -> None:
        entry = self._by_key.setdefault(key, _Attempts())
        entry.count += 1
        if entry.count >= self._max:
            entry.blocked_until = time.monotonic() + self._lockout
            entry.count = 0
            log.warning("источник заблокирован за перебор", key=key, seconds=self._lockout)

    def record_success(self, key: str) -> None:
        self._by_key.pop(key, None)


class AuthService:
    def __init__(self, settings: ControllerSettings) -> None:
        self._settings = settings
        data_dir = settings.resolved_data_dir()

        secret = settings.auth.resolve_session_secret() or load_or_create_secret(
            data_dir / "session.key"
        )
        self.sessions = SessionManager(
            secret,
            ttl_hours=settings.auth.session_ttl_hours,
            revocations=RevocationStore(data_dir / "sessions.json"),
        )
        self.store = CredentialStore(data_dir / "passkeys.json")
        self._password_hash = settings.auth.resolve_password_hash()
        self._limiter = RateLimiter(
            settings.auth.max_failed_attempts, settings.auth.lockout_seconds
        )

        self.webauthn: WebAuthnService | None = None
        if settings.auth.webauthn_enabled and settings.auth.webauthn_rp_id:
            origin = settings.server.public_origin or f"https://{settings.auth.webauthn_rp_id}"
            self.webauthn = WebAuthnService(
                self.store,
                rp_id=settings.auth.webauthn_rp_id,
                rp_name=settings.auth.webauthn_rp_name,
                expected_origin=origin,
            )
            log.info("passkey включён", rp_id=settings.auth.webauthn_rp_id, origin=origin)
        elif settings.auth.webauthn_enabled:
            log.warning("passkey отключён: не задан auth.webauthn_rp_id")

    @property
    def password_enabled(self) -> bool:
        return self._settings.auth.password_enabled and self._password_hash is not None

    @property
    def passkey_available(self) -> bool:
        return self.webauthn is not None and self.webauthn.has_credentials

    @property
    def passkey_configured(self) -> bool:
        return self.webauthn is not None

    def login_with_password(self, password: str, *, source: str) -> tuple[str, int]:
        """Проверяет пароль и выдаёт сессию."""
        self._limiter.check(source)

        if not self.password_enabled or self._password_hash is None:
            raise ForbiddenError("вход по паролю выключен")

        if not verify_password(self._password_hash, password):
            self._limiter.record_failure(source)
            log.warning("неудачный вход по паролю", source=source)
            raise UnauthorizedError("неверный пароль")

        self._limiter.record_success(source)
        token, expires = self.sessions.issue(method="password")
        log.info("успешный вход по паролю", source=source, expires=expires.isoformat())
        return token, self.sessions.ttl_seconds

    def login_with_passkey(
        self, handle: str, credential: dict[str, object], *, source: str
    ) -> tuple[str, int]:
        self._limiter.check(source)
        if self.webauthn is None:
            raise ForbiddenError("passkey не настроен")
        try:
            stored = self.webauthn.verify_authentication(handle, credential)
        except UnauthorizedError:
            self._limiter.record_failure(source)
            raise
        self._limiter.record_success(source)
        token, _ = self.sessions.issue(method="passkey", credential=stored.label)
        log.info("успешный вход по passkey", source=source, label=stored.label)
        return token, self.sessions.ttl_seconds

    @property
    def terminal_max_session_age_seconds(self) -> int:
        return self._settings.auth.terminal_max_session_age_minutes * 60

    def cookie_settings(self) -> dict[str, object]:
        return {
            "key": self._settings.auth.cookie_name,
            "httponly": True,
            "secure": self._settings.auth.cookie_secure,
            "samesite": "lax",
            "max_age": self.sessions.ttl_seconds,
            "path": "/",
        }


def default_data_dir(settings: ControllerSettings) -> Path:
    return settings.resolved_data_dir()
