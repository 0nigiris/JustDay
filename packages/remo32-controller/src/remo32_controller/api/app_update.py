"""Обновление приложения на телефоне.

Магазина нет, значит обновляет тот же контроллер, которым приложение
управляет. Телефон спрашивает версию, сравнивает со своей и, если на
сервере новее, скачивает и запускает установщик.

Версию берём из файла рядом с APK: его пишет ``android/build.sh``. Читать
её из самого APK означало бы разбирать бинарный ресурс манифеста — много
кода ради значения, которое сборщик и так знает.

Всё под сессией. APK не секрет, но открытая раздача файла, который человек
установит на телефон не глядя, — плохая мысль.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import FileResponse

from remo32_controller.auth.dependencies import Session
from remo32_controller.config import ControllerSettings
from remo32_core.errors import NotFoundError
from remo32_core.http import RequestId
from remo32_core.log import get_logger
from remo32_core.models import ApiResponse, AppRelease

log = get_logger("controller.api.app")

router = APIRouter(prefix="/api/app", tags=["приложение"])


def _settings(request: Request) -> ControllerSettings:
    settings: ControllerSettings = request.app.state.settings
    return settings


def _apk_path(request: Request) -> Path:
    settings = _settings(request)
    if not settings.android_app.enabled:
        raise NotFoundError("раздача приложения выключена")
    path = settings.android_app.apk_path.expanduser()
    if not path.is_absolute():
        path = Path.cwd() / path
    return path


def _read_release(apk: Path) -> AppRelease:
    """Метаданные сборки. Отсутствие файла — не ошибка сервера.

    APK может просто не быть собран: контроллер полезен и без приложения.
    """
    if not apk.is_file():
        raise NotFoundError(
            "приложение не собрано: нет файла APK. Соберите его: ./android/build.sh"
        )

    meta_path = apk.with_suffix(".json")
    meta: dict[str, Any] = {}
    if meta_path.is_file():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except (ValueError, OSError) as exc:
            log.warning("метаданные сборки не читаются", path=str(meta_path), error=str(exc))

    stat = apk.stat()
    return AppRelease(
        version_code=int(meta.get("version_code", 0)),
        version_name=str(meta.get("version_name", "неизвестно")),
        size_bytes=stat.st_size,
        sha256=str(meta.get("sha256") or _sha256(apk)),
        built_at=meta.get("built_at"),
        download_url="/api/app/download",
    )


def _sha256(path: Path) -> str:
    """Считается только когда сборщик не оставил готовое значение.

    Файл читается кусками: APK небольшой, но держать его целиком в памяти
    незачем — контроллер живёт на той же машине, что и всё остальное.
    """
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


@router.get("/latest", response_model=ApiResponse[AppRelease])
async def latest(
    request: Request, _session: Session, request_id: RequestId
) -> ApiResponse[AppRelease]:
    """Какая версия приложения лежит на сервере."""
    return ApiResponse[AppRelease].success(_read_release(_apk_path(request)), request_id)


@router.get("/download")
async def download(request: Request, _session: Session) -> FileResponse:
    """Сам файл. Имя с версией — чтобы в «Загрузках» их можно было различить."""
    apk = _apk_path(request)
    release = _read_release(apk)
    log.info("выдача APK", version_code=release.version_code, size=release.size_bytes)
    return FileResponse(
        apk,
        media_type="application/vnd.android.package-archive",
        filename=f"remo32-{release.version_name}.apk",
    )
