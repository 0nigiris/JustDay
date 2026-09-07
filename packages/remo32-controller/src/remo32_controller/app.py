"""Сборка приложения контроллера."""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Response
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles

from remo32_controller import __version__
from remo32_controller.api import auth as auth_api
from remo32_controller.api import esp32 as esp32_api
from remo32_controller.api import pcs as pcs_api
from remo32_controller.api import schedules as schedules_api
from remo32_controller.api import system as system_api
from remo32_controller.api import terminal as terminal_api
from remo32_controller.auth.service import AuthService
from remo32_controller.config import ControllerSettings, load_settings
from remo32_controller.devices import DeviceRegistry
from remo32_controller.esp32.controller import Esp32Controller, build_transport
from remo32_controller.schedule.service import ScheduleService
from remo32_core.http import install_exception_handlers, install_request_id_middleware
from remo32_core.log import configure_logging, get_logger

log = get_logger("controller.app")

WEB_DIR = Path(__file__).parent / "web"

DESCRIPTION = """
Центральный контроллер Remo32: единая точка управления домашними ПК и
аппаратным контроллером ESP32.

**Аутентификация.** Все ручки, кроме `/api/health` и `/api/auth/status`,
требуют сессию. Вход — по passkey (отпечаток пальца) либо по паролю.
Сессия хранится в httpOnly-cookie.

**Tailscale — не аутентификация.** Контроллер требует вход даже внутри
частной сети: в тайлнете могут оказаться чужие устройства.

**Произвольные команды.** REST API их не принимает: доступны только
действия, описанные в конфигурации агента. Полноценный терминал вынесен
в отдельную возможность, выключенную по умолчанию и требующую разрешения
и в контроллере, и в агенте.
"""

TAGS = [
    {"name": "аутентификация", "description": "Вход, выход, passkey"},
    {"name": "ПК", "description": "Состояние, питание, статистика, действия"},
    {"name": "ESP32", "description": "Аппаратный контроллер, GPIO, переключение ПК"},
    {"name": "расписание", "description": "Правила «в такое-то время сделать то-то»"},
    {"name": "терминал", "description": "Удалённый терминал через WebSocket"},
    {"name": "служебные", "description": "Здоровье и поток событий"},
]


# Без Cache-Control браузер кэширует статику на своё усмотрение и после
# обновления интерфейса продолжает выполнять старый app.js — вплоть до ошибок
# вида «элемента больше нет». «no-cache» означает не «не кэшировать», а
# «каждый раз спрашивать»: при неизменном ETag ответ будет пустой 304.
NO_CACHE = {"Cache-Control": "no-cache"}


class RevalidatingStaticFiles(StaticFiles):
    """StaticFiles, заставляющий браузер сверяться с сервером перед показом."""

    def file_response(self, *args: object, **kwargs: object) -> Response:
        response = super().file_response(*args, **kwargs)  # type: ignore[arg-type]
        response.headers["Cache-Control"] = "no-cache"
        return response


def asset_version() -> str:
    """Метка версии статики: время правки самого свежего файла интерфейса.

    Одного «Cache-Control: no-cache» мало. Копия, попавшая в кэш браузера
    раньше, чем появился этот заголовок, остаётся там жить, и телефон
    продолжает выполнять старый app.js — с ошибками на элементах, которых
    в разметке уже нет. Меняющийся адрес — единственное, что гарантированно
    пробивает такой кэш.
    """
    newest = 0.0
    for path in WEB_DIR.rglob("*"):
        if path.is_file():
            newest = max(newest, path.stat().st_mtime)
    return str(int(newest))


def _page(name: str) -> HTMLResponse:
    html = (WEB_DIR / name).read_text(encoding="utf-8")
    return HTMLResponse(
        html.replace("__ASSET_VERSION__", asset_version()),
        headers=NO_CACHE,
    )


def create_app(
    settings: ControllerSettings | None = None, *, configure_logs: bool = True
) -> FastAPI:
    settings = settings or load_settings()

    if configure_logs:
        configure_logging(
            level=settings.server.log_level,
            fmt=settings.server.log_format,
            component="controller",
        )

    auth_service = AuthService(settings)

    esp32: Esp32Controller | None = None
    if settings.esp32.enabled:
        transport = build_transport(settings.esp32, token=os.environ.get(settings.esp32.token_env))
        esp32 = Esp32Controller(transport, settings.esp32)

    registry = DeviceRegistry(settings, esp32)
    schedules = ScheduleService(registry, settings.resolved_data_dir())

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if esp32 is not None:
            await esp32.start()
        await registry.start()
        await schedules.start()
        log.info(
            "контроллер запущен",
            version=__version__,
            host=settings.server.host,
            port=settings.server.port,
            pcs=len(settings.pcs),
            esp32=settings.esp32.transport if settings.esp32.enabled else "выключен",
            passkey=auth_service.passkey_configured,
            schedules=len(schedules.list_entries()),
        )
        if settings.esp32.enabled and settings.esp32.transport == "mock":
            log.warning("ВНИМАНИЕ: ESP32 симулируется, настоящее железо не задействовано")
        if settings.server.host == "0.0.0.0":
            log.warning(
                "контроллер слушает на всех интерфейсах. Для домашней установки "
                "укажите адрес Tailscale в server.host"
            )
        try:
            yield
        finally:
            await schedules.stop()
            await registry.stop()
            if esp32 is not None:
                await esp32.stop()
            log.info("контроллер остановлен")

    app = FastAPI(
        title="Remo32 Controller",
        version=__version__,
        description=DESCRIPTION,
        openapi_tags=TAGS,
        lifespan=lifespan,
        docs_url="/docs",
        redoc_url=None,
    )

    app.state.settings = settings
    app.state.auth = auth_service
    app.state.devices = registry
    app.state.esp32 = esp32
    app.state.schedules = schedules

    install_request_id_middleware(app, component="controller")
    install_exception_handlers(app)

    app.include_router(system_api.router)
    app.include_router(auth_api.router)
    app.include_router(pcs_api.router)
    app.include_router(esp32_api.router)
    app.include_router(schedules_api.router)
    app.include_router(terminal_api.router)

    if WEB_DIR.is_dir():
        app.mount("/static", RevalidatingStaticFiles(directory=WEB_DIR), name="static")

        @app.get("/", include_in_schema=False)
        async def index() -> HTMLResponse:
            return _page("index.html")

        @app.get("/terminal", include_in_schema=False)
        async def terminal_page() -> HTMLResponse:
            return _page("terminal.html")

    return app
