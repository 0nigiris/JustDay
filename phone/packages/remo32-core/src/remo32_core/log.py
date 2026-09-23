"""Структурное логирование для всех компонентов Remo32.

Один вызов :func:`configure_logging` настраивает structlog так, чтобы:

* в терминале при разработке логи были цветными и читаемыми;
* в systemd/проде — строчками JSON, которые journald и любой сборщик разберут;
* к каждой записи автоматически прилипал ``request_id`` текущего запроса.
"""

from __future__ import annotations

import logging
import sys
from contextvars import ContextVar
from typing import Any, Literal
from uuid import uuid4

import structlog

LogFormat = Literal["console", "json"]

_request_id: ContextVar[str | None] = ContextVar("remo32_request_id", default=None)


def new_request_id() -> str:
    """Короткий идентификатор запроса — его видно и в логах, и в ответе API."""
    return uuid4().hex[:12]


def bind_request_id(request_id: str | None) -> str:
    """Привязывает идентификатор к текущему контексту (запросу или задаче)."""
    rid = request_id or new_request_id()
    _request_id.set(rid)
    return rid


def current_request_id() -> str | None:
    return _request_id.get()


def _inject_request_id(_logger: Any, _method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
    rid = _request_id.get()
    if rid is not None:
        event_dict.setdefault("request_id", rid)
    return event_dict


def configure_logging(
    *,
    level: str = "INFO",
    fmt: LogFormat = "console",
    component: str | None = None,
) -> None:
    """Настраивает logging и structlog. Вызывается один раз на старте процесса."""
    numeric_level = getattr(logging, level.upper(), logging.INFO)

    shared: list[Any] = [
        structlog.contextvars.merge_contextvars,
        _inject_request_id,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso", utc=True),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.UnicodeDecoder(),
    ]
    if component:
        shared.insert(0, _component_processor(component))

    renderer: Any = (
        structlog.dev.ConsoleRenderer(colors=sys.stderr.isatty())
        if fmt == "console"
        else structlog.processors.JSONRenderer(ensure_ascii=False)
    )

    structlog.configure(
        processors=[*shared, structlog.processors.format_exc_info, renderer],
        wrapper_class=structlog.make_filtering_bound_logger(numeric_level),
        logger_factory=structlog.PrintLoggerFactory(file=sys.stderr),
        cache_logger_on_first_use=True,
    )

    # Приводим stdlib-логи (uvicorn, httpx) к тому же уровню, чтобы вывод не двоился.
    logging.basicConfig(format="%(message)s", stream=sys.stderr, level=numeric_level)
    for noisy in ("uvicorn.access", "httpx", "httpcore", "aiomqtt"):
        logging.getLogger(noisy).setLevel(max(numeric_level, logging.WARNING))


def _component_processor(component: str) -> Any:
    def add_component(_logger: Any, _method: str, event_dict: dict[str, Any]) -> dict[str, Any]:
        event_dict.setdefault("component", component)
        return event_dict

    return add_component


def get_logger(name: str) -> Any:
    """Логгер компонента.

    Имя привязывается явным полем ``logger``: мы пишем через
    ``PrintLoggerFactory``, а не через stdlib, поэтому штатный
    ``add_logger_name`` здесь неприменим.
    """
    return structlog.get_logger(name).bind(logger=name)
