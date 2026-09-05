"""Сборка приложения агента."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from remo32_agent import __version__
from remo32_agent.api import build_router, openapi_tags
from remo32_agent.config import AgentSettings, load_settings
from remo32_agent.context import AgentContext
from remo32_agent.execution import CommandRunner
from remo32_agent.stats.collector import prime_cpu_percent
from remo32_core.http import install_exception_handlers, install_request_id_middleware
from remo32_core.log import configure_logging, get_logger

log = get_logger("agent.app")

DESCRIPTION = """
Агент Remo32 работает на управляемом ПК и выполняет то, что должно
происходить на уровне операционной системы: отдаёт статистику, запускает
предопределённые действия, корректно выключает и перезагружает машину,
предоставляет удалённый терминал.

**Аутентификация.** Все ручки, кроме `/ping`, требуют заголовок
`X-Remo32-Agent-Token`. Токен задаётся переменной окружения
`REMO32_AGENT_TOKEN` и никогда не хранится в файле конфигурации.

**Произвольные команды выполнить нельзя.** API принимает только
идентификаторы действий, описанных в конфигурации.
"""


def create_app(
    settings: AgentSettings | None = None,
    *,
    runner: CommandRunner | None = None,
    configure_logs: bool = True,
) -> FastAPI:
    """Создаёт приложение агента.

    ``runner`` подменяется в тестах — благодаря этому автотесты проверяют
    выключение ПК, ничего не выключая.
    """
    settings = settings or load_settings()

    if configure_logs:
        configure_logging(
            level=settings.server.log_level,
            fmt=settings.server.log_format,
            component="agent",
        )

    ctx = AgentContext(settings, runner=runner)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        prime_cpu_percent()
        log.info(
            "агент запущен",
            agent_id=settings.agent_id,
            host=settings.server.host,
            port=settings.server.port,
            actions=len(ctx.executor.registry),
            terminal=settings.terminal.enabled,
            power_dry_run=settings.power.dry_run,
            auth=ctx.auth.enabled,
        )
        if settings.server.host not in {"127.0.0.1", "localhost", "::1"} and not ctx.auth.enabled:
            log.error(
                "агент слушает на внешнем адресе БЕЗ ТОКЕНА — это опасно",
                host=settings.server.host,
            )
        yield
        log.info("агент остановлен")

    app = FastAPI(
        title="Remo32 Agent",
        version=__version__,
        description=DESCRIPTION,
        openapi_tags=openapi_tags(),
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
    )
    app.state.context = ctx

    install_request_id_middleware(app, component="agent")
    install_exception_handlers(app)
    app.include_router(build_router(ctx))
    return app
