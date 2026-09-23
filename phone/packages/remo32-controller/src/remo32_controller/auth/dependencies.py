"""Зависимости FastAPI для проверки сессии."""

from __future__ import annotations

from typing import Annotated, Any

from fastapi import Cookie, Depends, Request

from remo32_controller.auth.service import AuthService
from remo32_core.errors import UnauthorizedError


def get_auth_service(request: Request) -> AuthService:
    service: AuthService = request.app.state.auth
    return service


def require_session(
    request: Request,
    auth: Annotated[AuthService, Depends(get_auth_service)],
) -> dict[str, Any]:
    """Пускает дальше только с действующей сессией.

    Cookie читается вручную, а не через параметр ``Cookie(...)``, потому что
    имя cookie задаётся конфигурацией.
    """
    token = request.cookies.get(str(auth.cookie_settings()["key"]))
    if not token:
        raise UnauthorizedError("требуется вход")
    return auth.sessions.verify(token)


Session = Annotated[dict[str, Any], Depends(require_session)]
Auth = Annotated[AuthService, Depends(get_auth_service)]

__all__ = ["Auth", "Cookie", "Session", "get_auth_service", "require_session"]
