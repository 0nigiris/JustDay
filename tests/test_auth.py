"""Аутентификация контроллера."""

from __future__ import annotations

import pytest
from conftest import TEST_PASSWORD

from remo32_controller.auth.passwords import hash_password, verify_password
from remo32_controller.auth.service import AuthService, RateLimiter
from remo32_controller.auth.sessions import SessionManager, load_or_create_secret
from remo32_controller.auth.store import CredentialStore, StoredCredential
from remo32_controller.config import ControllerSettings
from remo32_core.errors import ForbiddenError, UnauthorizedError


def test_password_hash_is_argon2id() -> None:
    stored = hash_password("какой-то пароль")
    assert stored.startswith("$argon2id$")
    assert verify_password(stored, "какой-то пароль")
    assert not verify_password(stored, "другой пароль")


def test_password_hash_is_salted() -> None:
    """Одинаковые пароли дают разные хэши — иначе видно, что они совпадают."""
    assert hash_password("одинаковый") != hash_password("одинаковый")


def test_short_password_rejected() -> None:
    with pytest.raises(ValueError, match="8 символов"):
        hash_password("корот")


def test_corrupt_hash_does_not_crash() -> None:
    assert verify_password("не-хэш-вовсе", "что угодно") is False


def test_session_round_trip() -> None:
    manager = SessionManager("k" * 48, ttl_hours=1)
    token, _ = manager.issue(method="password")
    payload = manager.verify(token)
    assert payload["sub"] == "owner"
    assert payload["method"] == "password"


def test_session_secret_must_be_long_enough() -> None:
    with pytest.raises(ValueError, match="32"):
        SessionManager("коротко")


def test_logout_revokes_immediately() -> None:
    manager = SessionManager("k" * 48)
    token, _ = manager.issue()
    manager.revoke(token)
    with pytest.raises(UnauthorizedError, match="завершена"):
        manager.verify(token)


def test_token_signed_with_other_key_rejected() -> None:
    issuer = SessionManager("a" * 48)
    verifier = SessionManager("b" * 48)
    token, _ = issuer.issue()
    with pytest.raises(UnauthorizedError):
        verifier.verify(token)


def test_expired_session_rejected() -> None:
    import time

    import jwt

    manager = SessionManager("k" * 48)
    expired = jwt.encode(
        {"iss": "remo32-controller", "sub": "owner", "exp": int(time.time()) - 10},
        "k" * 48,
        algorithm="HS256",
    )
    with pytest.raises(UnauthorizedError, match="истекла"):
        manager.verify(expired)


def test_secret_file_created_with_strict_permissions(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "session.key"
    secret = load_or_create_secret(path)
    assert len(secret) >= 32
    assert path.stat().st_mode & 0o077 == 0
    # Повторный вызов возвращает тот же ключ: сессии переживают перезапуск.
    assert load_or_create_secret(path) == secret


def test_rate_limiter_blocks_after_threshold() -> None:
    limiter = RateLimiter(max_attempts=3, lockout_seconds=60)
    for _ in range(3):
        limiter.check("1.2.3.4")
        limiter.record_failure("1.2.3.4")
    with pytest.raises(ForbiddenError, match="слишком много"):
        limiter.check("1.2.3.4")
    # Другой источник не страдает.
    limiter.check("5.6.7.8")


def test_successful_login_resets_counter() -> None:
    limiter = RateLimiter(max_attempts=3, lockout_seconds=60)
    limiter.record_failure("1.2.3.4")
    limiter.record_failure("1.2.3.4")
    limiter.record_success("1.2.3.4")
    limiter.record_failure("1.2.3.4")
    limiter.check("1.2.3.4")  # не должно бросить


def test_credential_store_persists_and_is_private(tmp_path) -> None:  # type: ignore[no-untyped-def]
    path = tmp_path / "passkeys.json"
    store = CredentialStore(path)
    store.add(
        StoredCredential(
            credential_id="abc",
            public_key="key",
            sign_count=0,
            label="Телефон",
            created_at="2026-01-01T00:00:00+00:00",
        )
    )
    assert path.stat().st_mode & 0o077 == 0
    assert len(CredentialStore(path)) == 1
    assert CredentialStore(path).get("abc") is not None


def test_credential_sign_count_updates(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Счётчик подписи растёт: он защищает от клонирования ключа."""
    store = CredentialStore(tmp_path / "p.json")
    store.add(
        StoredCredential(
            credential_id="abc", public_key="k", sign_count=1, label="X", created_at="now"
        )
    )
    store.touch("abc", 5)
    reloaded = CredentialStore(tmp_path / "p.json")
    credential = reloaded.get("abc")
    assert credential is not None
    assert credential.sign_count == 5
    assert credential.last_used_at is not None


def test_auth_service_login_flow(controller_settings: ControllerSettings) -> None:
    service = AuthService(controller_settings)
    token, ttl = service.login_with_password(TEST_PASSWORD, source="test")
    assert ttl > 0
    assert service.sessions.verify(token)["method"] == "password"

    with pytest.raises(UnauthorizedError):
        service.login_with_password("неверный", source="test")


def test_auth_service_blocks_bruteforce(controller_settings: ControllerSettings) -> None:
    service = AuthService(controller_settings)
    for _ in range(controller_settings.auth.max_failed_attempts):
        with pytest.raises(UnauthorizedError):
            service.login_with_password("неверный", source="злоумышленник")
    with pytest.raises(ForbiddenError, match="слишком много"):
        service.login_with_password(TEST_PASSWORD, source="злоумышленник")


def test_passkey_disabled_without_rp_id(controller_settings: ControllerSettings) -> None:
    """Passkey не включается молча: без домена он просто недоступен."""
    service = AuthService(controller_settings)
    assert service.webauthn is None
    assert service.passkey_configured is False
