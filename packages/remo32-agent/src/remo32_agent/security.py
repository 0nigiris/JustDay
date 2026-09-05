"""Аутентификация контроллера перед агентом.

Модель простая и намеренно жёсткая: один общий токен, который знают
только агент и контроллер. Агент никого не «узнаёт» — он проверяет
предъявленный токен и всё.

Почему токен нужен даже внутри Tailscale: в тайлнет могут быть добавлены
чужие устройства (у автора проекта такое уже было), а сама сеть Tailscale
подтверждает лишь то, что узел в неё допущен, — не то, что ему можно
выключать ваш компьютер.
"""

from __future__ import annotations

import secrets

from fastapi import Header, HTTPException, status

from remo32_core.log import get_logger
from remo32_core.protocol import HEADER_AGENT_TOKEN

log = get_logger("agent.security")


class TokenAuth:
    """Проверка общего токена. Сравнение — константное по времени."""

    def __init__(self, token: str | None, *, allow_insecure: bool = False) -> None:
        self._token = token
        self._allow_insecure = allow_insecure
        if token is None and allow_insecure:
            log.warning(
                "АГЕНТ РАБОТАЕТ БЕЗ ТОКЕНА. Допустимо только для локальной разработки "
                "и только на адресе 127.0.0.1"
            )

    @property
    def enabled(self) -> bool:
        return self._token is not None

    def verify(self, presented: str | None) -> None:
        if self._token is None:
            if self._allow_insecure:
                return
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="агент настроен неверно: токен отсутствует",
            )
        if presented is None:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=f"требуется заголовок {HEADER_AGENT_TOKEN}",
            )
        if not secrets.compare_digest(presented, self._token):
            log.warning("отклонён запрос с неверным токеном")
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="неверный токен")


async def require_token(
    request_token: str | None = Header(None, alias=HEADER_AGENT_TOKEN),
) -> None:
    """Заглушка-зависимость. Реальная проверка подставляется в app.py.

    FastAPI позволяет подменить зависимость через ``dependency_overrides``,
    но нам нужен доступ к настройкам, поэтому в приложении эта функция
    заменяется замыканием над готовым :class:`TokenAuth`.
    """
    raise HTTPException(status_code=500, detail="зависимость аутентификации не настроена")
