"""Вход, выход и управление passkey."""

from __future__ import annotations

import json
from typing import Any

from fastapi import APIRouter, Request, Response
from pydantic import BaseModel, Field

from remo32_controller.auth.dependencies import Auth, Session
from remo32_core.errors import ForbiddenError, NotFoundError
from remo32_core.http import RequestId
from remo32_core.log import get_logger
from remo32_core.models import ApiResponse

log = get_logger("controller.api.auth")

router = APIRouter(prefix="/api/auth", tags=["аутентификация"])


class AuthStatus(BaseModel):
    authenticated: bool
    password_enabled: bool
    passkey_available: bool = Field(description="Есть хотя бы один зарегистрированный passkey")
    passkey_configured: bool = Field(description="Passkey настроен и домен задан")
    method: str | None = None


class PasswordLogin(BaseModel):
    password: str = Field(min_length=1, max_length=512)


class PasskeyVerify(BaseModel):
    handle: str = Field(min_length=1, max_length=64)
    credential: dict[str, Any]
    label: str = Field("Телефон", max_length=64)


class PasskeyInfo(BaseModel):
    credential_id: str
    label: str
    created_at: str
    last_used_at: str | None = None


def _source(request: Request) -> str:
    return request.client.host if request.client else "unknown"


@router.get("/status", response_model=ApiResponse[AuthStatus])
async def status(request: Request, auth: Auth, request_id: RequestId) -> ApiResponse[AuthStatus]:
    """Состояние аутентификации. Единственная ручка, доступная без входа."""
    token = request.cookies.get(str(auth.cookie_settings()["key"]))
    method: str | None = None
    authenticated = False
    if token:
        try:
            payload = auth.sessions.verify(token)
            authenticated = True
            method = payload.get("method")
        except Exception:
            authenticated = False
    return ApiResponse[AuthStatus].success(
        AuthStatus(
            authenticated=authenticated,
            password_enabled=auth.password_enabled,
            passkey_available=auth.passkey_available,
            passkey_configured=auth.passkey_configured,
            method=method,
        ),
        request_id,
    )


@router.post("/login", response_model=ApiResponse[AuthStatus])
async def login(
    body: PasswordLogin,
    request: Request,
    response: Response,
    auth: Auth,
    request_id: RequestId,
) -> ApiResponse[AuthStatus]:
    """Вход по паролю."""
    token, _ = auth.login_with_password(body.password, source=_source(request))
    response.set_cookie(value=token, **auth.cookie_settings())  # type: ignore[arg-type]
    return ApiResponse[AuthStatus].success(
        AuthStatus(
            authenticated=True,
            password_enabled=auth.password_enabled,
            passkey_available=auth.passkey_available,
            passkey_configured=auth.passkey_configured,
            method="password",
        ),
        request_id,
    )


@router.post("/logout", response_model=ApiResponse[AuthStatus])
async def logout(
    request: Request, response: Response, auth: Auth, request_id: RequestId
) -> ApiResponse[AuthStatus]:
    key = str(auth.cookie_settings()["key"])
    if token := request.cookies.get(key):
        auth.sessions.revoke(token)
    response.delete_cookie(key, path="/")
    return ApiResponse[AuthStatus].success(
        AuthStatus(
            authenticated=False,
            password_enabled=auth.password_enabled,
            passkey_available=auth.passkey_available,
            passkey_configured=auth.passkey_configured,
        ),
        request_id,
    )


@router.post("/passkey/register/options", response_model=ApiResponse[dict[str, Any]])
async def passkey_register_options(
    auth: Auth, _session: Session, request_id: RequestId
) -> ApiResponse[dict[str, Any]]:
    """Опции регистрации passkey.

    Требует уже выполненного входа: новый ключ добавляет только тот, кто
    уже доказал, что он владелец.
    """
    if auth.webauthn is None:
        raise ForbiddenError("passkey не настроен: задайте auth.webauthn_rp_id")
    handle, options_json = auth.webauthn.registration_options()
    return ApiResponse[dict[str, Any]].success(
        {"handle": handle, "options": json.loads(options_json)}, request_id
    )


@router.post("/passkey/register/verify", response_model=ApiResponse[PasskeyInfo])
async def passkey_register_verify(
    body: PasskeyVerify, auth: Auth, _session: Session, request_id: RequestId
) -> ApiResponse[PasskeyInfo]:
    if auth.webauthn is None:
        raise ForbiddenError("passkey не настроен")
    credential_id = auth.webauthn.verify_registration(body.handle, body.credential, body.label)
    stored = auth.store.get(credential_id)
    if stored is None:  # pragma: no cover — сразу после успешной записи невозможно
        raise NotFoundError("passkey не сохранился", credential_id=credential_id)
    return ApiResponse[PasskeyInfo].success(
        PasskeyInfo(
            credential_id=stored.credential_id,
            label=stored.label,
            created_at=stored.created_at,
            last_used_at=stored.last_used_at,
        ),
        request_id,
    )


@router.post("/passkey/login/options", response_model=ApiResponse[dict[str, Any]])
async def passkey_login_options(auth: Auth, request_id: RequestId) -> ApiResponse[dict[str, Any]]:
    if auth.webauthn is None:
        raise ForbiddenError("passkey не настроен")
    if not auth.passkey_available:
        raise ForbiddenError("ни одного passkey не зарегистрировано")
    handle, options_json = auth.webauthn.authentication_options()
    return ApiResponse[dict[str, Any]].success(
        {"handle": handle, "options": json.loads(options_json)}, request_id
    )


@router.post("/passkey/login/verify", response_model=ApiResponse[AuthStatus])
async def passkey_login_verify(
    body: PasskeyVerify,
    request: Request,
    response: Response,
    auth: Auth,
    request_id: RequestId,
) -> ApiResponse[AuthStatus]:
    token, _ = auth.login_with_passkey(body.handle, body.credential, source=_source(request))
    response.set_cookie(value=token, **auth.cookie_settings())  # type: ignore[arg-type]
    return ApiResponse[AuthStatus].success(
        AuthStatus(
            authenticated=True,
            password_enabled=auth.password_enabled,
            passkey_available=True,
            passkey_configured=True,
            method="passkey",
        ),
        request_id,
    )


@router.get("/passkeys", response_model=ApiResponse[list[PasskeyInfo]])
async def list_passkeys(
    auth: Auth, _session: Session, request_id: RequestId
) -> ApiResponse[list[PasskeyInfo]]:
    items = [
        PasskeyInfo(
            credential_id=c.credential_id,
            label=c.label,
            created_at=c.created_at,
            last_used_at=c.last_used_at,
        )
        for c in auth.store.all()
    ]
    return ApiResponse[list[PasskeyInfo]].success(items, request_id)


@router.delete("/passkeys/{credential_id}", response_model=ApiResponse[dict[str, bool]])
async def delete_passkey(
    credential_id: str, auth: Auth, _session: Session, request_id: RequestId
) -> ApiResponse[dict[str, bool]]:
    if not auth.store.remove(credential_id):
        raise NotFoundError("passkey не найден", credential_id=credential_id)
    log.warning("passkey удалён", credential_id=credential_id[:12])
    return ApiResponse[dict[str, bool]].success({"removed": True}, request_id)
