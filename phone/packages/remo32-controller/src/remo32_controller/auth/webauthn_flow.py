"""Регистрация и вход по passkey (WebAuthn).

Passkey — это отпечаток пальца или лицо на телефоне: секрет никогда не
покидает устройство, поэтому его нельзя подсмотреть и переиспользовать.

Ограничение, о котором важно помнить: passkey привязан к домену (RP ID).
Если контроллер переедет на другой адрес, ключи перестанут подходить —
именно поэтому вход по паролю остаётся всегда.
"""

from __future__ import annotations

import secrets
import time
from dataclasses import dataclass
from datetime import UTC, datetime

import webauthn
from webauthn.helpers import base64url_to_bytes, bytes_to_base64url
from webauthn.helpers.structs import (
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from remo32_controller.auth.store import CredentialStore, StoredCredential
from remo32_core.errors import UnauthorizedError
from remo32_core.log import get_logger

log = get_logger("controller.auth.webauthn")

CHALLENGE_TTL_SECONDS = 300
USER_ID = b"remo32-owner"
USER_NAME = "owner"


@dataclass(slots=True)
class _Challenge:
    value: bytes
    created_at: float


class WebAuthnService:
    def __init__(
        self,
        store: CredentialStore,
        *,
        rp_id: str,
        rp_name: str,
        expected_origin: str,
    ) -> None:
        self._store = store
        self._rp_id = rp_id
        self._rp_name = rp_name
        self._origin = expected_origin.rstrip("/")
        self._challenges: dict[str, _Challenge] = {}

    @property
    def rp_id(self) -> str:
        return self._rp_id

    @property
    def has_credentials(self) -> bool:
        return len(self._store) > 0

    def _remember_challenge(self, challenge: bytes) -> str:
        self._prune()
        handle = secrets.token_urlsafe(12)
        self._challenges[handle] = _Challenge(challenge, time.monotonic())
        return handle

    def _take_challenge(self, handle: str) -> bytes:
        self._prune()
        entry = self._challenges.pop(handle, None)
        if entry is None:
            raise UnauthorizedError("запрос устарел, попробуйте ещё раз")
        return entry.value

    def _prune(self) -> None:
        now = time.monotonic()
        expired = [
            handle
            for handle, entry in self._challenges.items()
            if now - entry.created_at > CHALLENGE_TTL_SECONDS
        ]
        for handle in expired:
            del self._challenges[handle]

    # --- регистрация ------------------------------------------------------

    def registration_options(self) -> tuple[str, str]:
        """Возвращает (handle, JSON-опции для браузера)."""
        options = webauthn.generate_registration_options(
            rp_id=self._rp_id,
            rp_name=self._rp_name,
            user_id=USER_ID,
            user_name=USER_NAME,
            user_display_name="Владелец Remo32",
            authenticator_selection=AuthenticatorSelectionCriteria(
                # resident key = ключ хранится на телефоне и подходит без
                # ввода имени пользователя: одно касание пальцем.
                resident_key=ResidentKeyRequirement.PREFERRED,
                user_verification=UserVerificationRequirement.PREFERRED,
            ),
            exclude_credentials=[
                PublicKeyCredentialDescriptor(id=base64url_to_bytes(c.credential_id))
                for c in self._store.all()
            ],
        )
        handle = self._remember_challenge(options.challenge)
        return handle, webauthn.options_to_json(options)

    def verify_registration(self, handle: str, credential: dict[str, object], label: str) -> str:
        challenge = self._take_challenge(handle)
        try:
            verified = webauthn.verify_registration_response(
                credential=credential,
                expected_challenge=challenge,
                expected_rp_id=self._rp_id,
                expected_origin=self._origin,
            )
        except Exception as exc:
            log.warning("регистрация passkey не прошла проверку", error=str(exc))
            raise UnauthorizedError(f"passkey не удалось зарегистрировать: {exc}") from exc

        credential_id = bytes_to_base64url(verified.credential_id)
        self._store.add(
            StoredCredential(
                credential_id=credential_id,
                public_key=bytes_to_base64url(verified.credential_public_key),
                sign_count=verified.sign_count,
                label=label or "Без названия",
                created_at=datetime.now(UTC).isoformat(),
            )
        )
        return credential_id

    # --- вход -------------------------------------------------------------

    def authentication_options(self) -> tuple[str, str]:
        options = webauthn.generate_authentication_options(
            rp_id=self._rp_id,
            allow_credentials=[
                PublicKeyCredentialDescriptor(id=base64url_to_bytes(c.credential_id))
                for c in self._store.all()
            ],
            user_verification=UserVerificationRequirement.PREFERRED,
        )
        handle = self._remember_challenge(options.challenge)
        return handle, webauthn.options_to_json(options)

    def verify_authentication(self, handle: str, credential: dict[str, object]) -> StoredCredential:
        challenge = self._take_challenge(handle)
        raw_id = credential.get("id")
        if not isinstance(raw_id, str):
            raise UnauthorizedError("в ответе браузера нет идентификатора ключа")

        stored = self._store.get(raw_id)
        if stored is None:
            raise UnauthorizedError("этот passkey не зарегистрирован")

        try:
            verified = webauthn.verify_authentication_response(
                credential=credential,
                expected_challenge=challenge,
                expected_rp_id=self._rp_id,
                expected_origin=self._origin,
                credential_public_key=base64url_to_bytes(stored.public_key),
                credential_current_sign_count=stored.sign_count,
            )
        except Exception as exc:
            log.warning("вход по passkey не прошёл проверку", error=str(exc))
            raise UnauthorizedError(f"passkey отклонён: {exc}") from exc

        self._store.touch(stored.credential_id, verified.new_sign_count)
        return stored
