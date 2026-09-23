"""Общий HTTP-слой для контроллера и агента.

Здесь живут единый конверт ответа, преобразование доменных ошибок в
HTTP-ответы и middleware, который присваивает каждому запросу
идентификатор. Благодаря этому модулю обе службы отвечают одинаково,
и клиенту достаточно одного разбора ответа.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Sequence
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from remo32_core.errors import Remo32Error
from remo32_core.log import bind_request_id, get_logger, new_request_id
from remo32_core.models import ApiResponse
from remo32_core.protocol import HEADER_REQUEST_ID

log = get_logger("http")


def _jsonable_errors(errors: Sequence[Any], limit: int = 10) -> list[dict[str, Any]]:
    """Приводит отчёт pydantic к виду, который переживёт сериализацию.

    В ``ctx`` pydantic кладёт живой объект исключения, а в ``input`` —
    исходное значение любого типа. Без очистки ответ 422 падал бы при
    сериализации и превращался в 500: ошибка ввода выглядела бы поломкой
    сервера.
    """
    cleaned: list[dict[str, Any]] = []
    for error in list(errors)[:limit]:
        item: dict[str, Any] = {}
        for key, value in error.items():
            if key == "ctx" and isinstance(value, dict):
                item[key] = {k: str(v) for k, v in value.items()}
            elif isinstance(value, str | int | float | bool | type(None)):
                item[key] = value
            elif isinstance(value, list | tuple):
                item[key] = [v if isinstance(v, str | int) else str(v) for v in value]
            else:
                item[key] = str(value)
        cleaned.append(item)
    return cleaned


def get_request_id(request: Request) -> str | None:
    """Идентификатор текущего запроса для тела ответа.

    Middleware кладёт его в ``request.state``; зависимость достаёт, чтобы
    успешные ответы несли тот же идентификатор, что и ошибки.
    """
    return getattr(request.state, "request_id", None)


RequestId = Annotated[str | None, Depends(get_request_id)]


def error_response(
    *,
    status_code: int,
    code: str,
    message: str,
    details: dict[str, Any] | None = None,
    request_id: str | None = None,
) -> JSONResponse:
    payload = ApiResponse[None].failure(code, message, details=details or {}, request_id=request_id)
    return JSONResponse(
        status_code=status_code,
        content=payload.model_dump(mode="json"),
        headers={HEADER_REQUEST_ID: request_id} if request_id else None,
    )


def install_request_id_middleware(app: FastAPI, *, component: str) -> None:
    """Присваивает запросу идентификатор и логирует его исход.

    Идентификатор возвращается в заголовке и в теле ответа — по нему можно
    найти запрос в логах контроллера и агента одновременно.
    """

    @app.middleware("http")
    async def _middleware(request: Request, call_next: Callable[[Request], Awaitable[Any]]) -> Any:
        incoming = request.headers.get(HEADER_REQUEST_ID)
        request_id = bind_request_id(incoming or new_request_id())
        request.state.request_id = request_id

        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            duration_ms = (time.perf_counter() - started) * 1000
            log.exception(
                "необработанная ошибка запроса",
                component=component,
                method=request.method,
                path=request.url.path,
                duration_ms=round(duration_ms, 1),
            )
            raise

        duration_ms = (time.perf_counter() - started) * 1000
        response.headers[HEADER_REQUEST_ID] = request_id
        # Успешные опросы статуса не засоряют лог: их сотни в час.
        level = "debug" if response.status_code < 400 else "warning"
        getattr(log, level)(
            "запрос обработан",
            component=component,
            method=request.method,
            path=request.url.path,
            status=response.status_code,
            duration_ms=round(duration_ms, 1),
        )
        return response


def install_exception_handlers(app: FastAPI) -> None:
    """Превращает исключения в тот же конверт, что и успешные ответы."""

    @app.exception_handler(Remo32Error)
    async def _domain_error(request: Request, exc: Remo32Error) -> JSONResponse:
        request_id = getattr(request.state, "request_id", None)
        log.warning(
            "доменная ошибка",
            code=exc.code,
            message=exc.message,
            details=exc.details,
            path=request.url.path,
        )
        return error_response(
            status_code=exc.http_status,
            code=exc.code,
            message=exc.message,
            details=exc.details,
            request_id=request_id,
        )

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError) -> JSONResponse:
        return error_response(
            status_code=422,
            code="validation_error",
            message="запрос не прошёл проверку",
            details={"errors": _jsonable_errors(exc.errors())},
            request_id=getattr(request.state, "request_id", None),
        )

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException) -> JSONResponse:
        codes = {
            401: "unauthorized",
            403: "forbidden",
            404: "not_found",
            405: "method_not_allowed",
            429: "rate_limited",
        }
        return error_response(
            status_code=exc.status_code,
            code=codes.get(exc.status_code, "http_error"),
            message=str(exc.detail),
            request_id=getattr(request.state, "request_id", None),
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception) -> JSONResponse:
        # Наружу не отдаём ни текст исключения, ни трассировку: они уже в логе.
        return error_response(
            status_code=500,
            code="internal_error",
            message="внутренняя ошибка; подробности в журнале по request_id",
            request_id=getattr(request.state, "request_id", None),
        )
