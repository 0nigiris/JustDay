"""Общий HTTP-слой: конверт ответа одинаков у контроллера и агента."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import BaseModel, field_validator

from remo32_core.errors import (
    ActionNotFoundError,
    CapabilityUnavailableError,
    DeviceUnreachableError,
    Remo32Error,
)
from remo32_core.http import install_exception_handlers, install_request_id_middleware
from remo32_core.models import ApiResponse


class _WithValidator(BaseModel):
    """Модель с собственным валидатором, поднимающим ValueError."""

    at: str

    @field_validator("at")
    @classmethod
    def _check(cls, value: str) -> str:
        if value != "ok":
            raise ValueError("так нельзя")
        return value


def build_app() -> FastAPI:
    app = FastAPI()
    install_request_id_middleware(app, component="test")
    install_exception_handlers(app)

    @app.get("/ok")
    async def ok() -> ApiResponse[dict[str, int]]:
        return ApiResponse[dict[str, int]].success({"value": 1})

    @app.get("/not-found")
    async def not_found() -> None:
        raise ActionNotFoundError("нет такого действия", action_id="x")

    @app.get("/unreachable")
    async def unreachable() -> None:
        raise DeviceUnreachableError("устройство недоступно")

    @app.get("/unavailable")
    async def unavailable() -> None:
        raise CapabilityUnavailableError("нет железа")

    @app.post("/custom-validator")
    async def custom_validator(body: _WithValidator) -> None:
        return None

    @app.get("/boom")
    async def boom() -> None:
        raise RuntimeError("секретная внутренняя подробность")

    return app


def test_success_envelope() -> None:
    with TestClient(build_app()) as client:
        body = client.get("/ok").json()
        assert body["ok"] is True
        assert body["error"] is None


def test_domain_errors_map_to_status_codes() -> None:
    with TestClient(build_app()) as client:
        assert client.get("/not-found").status_code == 404
        assert client.get("/unreachable").status_code == 503
        assert client.get("/unavailable").status_code == 501


def test_error_details_are_preserved() -> None:
    with TestClient(build_app()) as client:
        error = client.get("/not-found").json()["error"]
        assert error["code"] == "action_not_found"
        assert error["details"]["action_id"] == "x"


def test_internal_error_does_not_leak_details() -> None:
    """Наружу не должно уйти ни текста исключения, ни трассировки."""
    with TestClient(build_app(), raise_server_exceptions=False) as client:
        response = client.get("/boom")
        assert response.status_code == 500
        body = response.json()
        assert "секретная внутренняя подробность" not in response.text
        assert body["error"]["code"] == "internal_error"
        assert body["request_id"]


def test_envelope_rejects_inconsistent_state() -> None:
    """Успешный ответ не может нести ошибку — это ловится моделью."""
    import pytest
    from pydantic import ValidationError

    from remo32_core.models import ApiError

    with pytest.raises(ValidationError):
        ApiResponse[dict[str, int]](ok=True, data={}, error=ApiError(code="x", message="y"))


def test_unknown_error_class_still_returns_envelope() -> None:
    class WeirdError(Remo32Error):
        code = "weird"
        http_status = 418

    app = build_app()

    @app.get("/weird")
    async def weird() -> None:
        raise WeirdError("странно")

    with TestClient(app) as client:
        response = client.get("/weird")
        assert response.status_code == 418
        assert response.json()["error"]["code"] == "weird"


def test_custom_validator_returns_envelope_not_500() -> None:
    """Собственный валидатор модели обязан давать 422 с читаемым телом.

    pydantic кладёт в отчёт живой объект ValueError. Пока он не приводился
    к строке, ответ падал при сериализации, и ошибка ввода выглядела как
    поломка сервера.
    """
    with TestClient(build_app()) as client:
        response = client.post("/custom-validator", json={"at": "плохо"})

    assert response.status_code == 422
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "validation_error"
    # Тело действительно сериализовалось, и текст валидатора виден.
    assert "так нельзя" in str(body["error"]["details"])
