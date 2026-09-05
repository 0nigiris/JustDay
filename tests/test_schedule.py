"""Планировщик: срабатывание, догон, защита от повторов, хранение.

Действия здесь не выполняются по-настоящему: реестр подменён заглушкой,
которая только считает вызовы. Планировщик не должен уметь ничего сделать
с реальной машиной в тестах.
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from remo32_controller.schedule.models import ScheduleCreate, ScheduleEntry, ScheduleUpdate
from remo32_controller.schedule.service import (
    ScheduleExistsError,
    ScheduleNotFoundError,
    ScheduleService,
)
from remo32_core.errors import DeviceUnreachableError, PcNotFoundError
from remo32_core.models import ActionResult


class FakeRegistry:
    """Реестр-заглушка: помнит вызовы, ничего не запускает."""

    def __init__(self, *, fail: bool = False, unreachable: bool = False) -> None:
        self.calls: list[tuple[str, str]] = []
        self.fail = fail
        self.unreachable = unreachable

    def ids(self) -> list[str]:
        return ["testpc", "second"]

    async def run_action(self, pc_id: str, action_id: str) -> ActionResult:
        self.calls.append((pc_id, action_id))
        if self.unreachable:
            raise DeviceUnreachableError("ПК выключен")
        return ActionResult(
            action_id=action_id,
            success=not self.fail,
            started_at=datetime(2026, 9, 3, 23, 0),
            message="не вышло" if self.fail else "готово",
        )


def make_service(tmp_path: Path, registry: FakeRegistry | None = None) -> ScheduleService:
    return ScheduleService(registry or FakeRegistry(), tmp_path)  # type: ignore[arg-type]


def entry_data(**overrides: object) -> ScheduleCreate:
    data: dict[str, object] = {
        "id": "night",
        "name": "Погасить свет",
        "at": "23:00",
        "days": [],
        "pc_id": "testpc",
        "action_id": "rgb-off",
    }
    data.update(overrides)
    return ScheduleCreate.model_validate(data)


# --- модель ------------------------------------------------------------------


@pytest.mark.parametrize("bad", ["24:00", "23:60", "7:00", "23-00", "", "полночь"])
def test_invalid_time_rejected(bad: str) -> None:
    with pytest.raises(ValueError):
        entry_data(at=bad)


def test_valid_time_accepted() -> None:
    assert entry_data(at="00:00").at == "00:00"
    assert entry_data(at="23:59").at == "23:59"


def test_days_normalised() -> None:
    entry = ScheduleEntry.model_validate(entry_data(days=[6, 0, 0, 3]).model_dump())
    assert entry.days == [0, 3, 6]


def test_invalid_day_rejected() -> None:
    with pytest.raises(ValueError):
        ScheduleEntry.model_validate(entry_data(days=[7]).model_dump())


# --- операции ----------------------------------------------------------------


def test_create_and_list(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service.create(entry_data())
    assert [e.id for e in service.list_entries()] == ["night"]


def test_duplicate_id_rejected(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service.create(entry_data())
    with pytest.raises(ScheduleExistsError):
        service.create(entry_data())


def test_unknown_pc_rejected(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    with pytest.raises(PcNotFoundError):
        service.create(entry_data(pc_id="нет-такого"))


def test_missing_schedule(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    with pytest.raises(ScheduleNotFoundError):
        service.get("нет")
    with pytest.raises(ScheduleNotFoundError):
        service.delete("нет")


def test_update_validates_time(tmp_path: Path) -> None:
    """Правка через API не должна протаскивать некорректное время."""
    service = make_service(tmp_path)
    service.create(entry_data())
    with pytest.raises(ValueError):
        service.update("night", ScheduleUpdate(at="99:99"))


def test_update_is_partial(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service.create(entry_data())
    updated = service.update("night", ScheduleUpdate(enabled=False))
    assert updated.enabled is False
    assert updated.at == "23:00"
    assert updated.name == "Погасить свет"


def test_survives_restart(tmp_path: Path) -> None:
    """Ребут раз в неделю не должен стирать расписание."""
    make_service(tmp_path).create(entry_data())
    revived = make_service(tmp_path)
    assert [e.id for e in revived.list_entries()] == ["night"]


def test_broken_entry_does_not_break_the_rest(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service.create(entry_data())
    service.create(entry_data(id="second", at="07:00"))

    path = tmp_path / "schedules.json"
    text = path.read_text(encoding="utf-8").replace('"07:00"', '"25:99"')
    path.write_text(text, encoding="utf-8")

    revived = make_service(tmp_path)
    assert [e.id for e in revived.list_entries()] == ["night"]


# --- срабатывание ------------------------------------------------------------


def test_due_at_the_right_moment(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service.create(entry_data(at="23:00"))

    assert service.due(datetime(2026, 9, 3, 22, 59)) == []
    assert [e.id for e in service.due(datetime(2026, 9, 3, 23, 0, 30))] == ["night"]


def test_disabled_never_fires(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service.create(entry_data(enabled=False))
    assert service.due(datetime(2026, 9, 3, 23, 0, 10)) == []


def test_weekday_filter(tmp_path: Path) -> None:
    service = make_service(tmp_path)
    service.create(entry_data(days=[0]))  # только понедельник

    thursday = datetime(2026, 9, 3, 23, 0, 10)
    monday = datetime(2026, 9, 7, 23, 0, 10)
    assert service.due(thursday) == []
    assert [e.id for e in service.due(monday)] == ["night"]


def test_catch_up_window(tmp_path: Path) -> None:
    """Опоздание в пределах окна догоняется, за его пределами — нет.

    Иначе контроллер, поднявшийся в полдень, немедленно выполнил бы
    ночное правило.
    """
    service = make_service(tmp_path)
    service.create(entry_data(at="23:00"))

    assert [e.id for e in service.due(datetime(2026, 9, 3, 23, 10))] == ["night"]
    assert service.due(datetime(2026, 9, 3, 23, 40)) == []


async def test_fires_once_per_slot(tmp_path: Path) -> None:
    registry = FakeRegistry()
    service = make_service(tmp_path, registry)
    service.create(entry_data(at="23:00"))

    moment = datetime(2026, 9, 3, 23, 0, 5)
    assert len(await service.tick(moment)) == 1
    assert len(await service.tick(datetime(2026, 9, 3, 23, 0, 25))) == 0
    assert len(await service.tick(datetime(2026, 9, 3, 23, 1, 0))) == 0
    assert registry.calls == [("testpc", "rgb-off")]

    # Следующие сутки — тот же слот срабатывает снова.
    assert len(await service.tick(datetime(2026, 9, 4, 23, 0, 5))) == 1
    assert len(registry.calls) == 2


async def test_result_recorded(tmp_path: Path) -> None:
    registry = FakeRegistry(fail=True)
    service = make_service(tmp_path, registry)
    service.create(entry_data(at="23:00"))

    await service.tick(datetime(2026, 9, 3, 23, 0, 5))
    entry = service.get("night")
    assert entry.last_ok is False
    assert entry.last_message == "не вышло"
    assert entry.last_run_at is not None


async def test_offline_pc_does_not_crash_the_scheduler(tmp_path: Path) -> None:
    """Выключенный ПК — обычное дело, а не авария контроллера."""
    registry = FakeRegistry(unreachable=True)
    service = make_service(tmp_path, registry)
    service.create(entry_data(at="23:00"))

    await service.tick(datetime(2026, 9, 3, 23, 0, 5))
    entry = service.get("night")
    assert entry.last_ok is False
    assert "выключен" in (entry.last_message or "")


async def test_run_now_does_not_consume_the_slot(tmp_path: Path) -> None:
    """Ручной запуск в 20:00 не отменяет плановое срабатывание в 23:00."""
    registry = FakeRegistry()
    service = make_service(tmp_path, registry)
    service.create(entry_data(at="23:00"))

    await service.run_now("night")
    assert service.get("night").last_fired_slot is None

    assert len(await service.tick(datetime(2026, 9, 3, 23, 0, 5))) == 1
    assert len(registry.calls) == 2


async def test_run_now_works_for_disabled_rule(tmp_path: Path) -> None:
    """Выключенное правило всё ещё можно выполнить руками с телефона."""
    registry = FakeRegistry()
    service = make_service(tmp_path, registry)
    service.create(entry_data(enabled=False))

    await service.run_now("night")
    assert registry.calls == [("testpc", "rgb-off")]


# --- API ---------------------------------------------------------------------


@pytest.fixture
def sched_client(controller_settings):  # type: ignore[no-untyped-def]
    from conftest import TEST_PASSWORD
    from fastapi.testclient import TestClient

    from remo32_controller.app import create_app

    with TestClient(create_app(controller_settings, configure_logs=False)) as client:
        assert client.post("/api/auth/login", json={"password": TEST_PASSWORD}).status_code == 200
        yield client


SCHEDULE_ENDPOINTS = [
    ("GET", "/api/schedules"),
    ("POST", "/api/schedules"),
    ("GET", "/api/schedules/night"),
    ("PATCH", "/api/schedules/night"),
    ("DELETE", "/api/schedules/night"),
    ("POST", "/api/schedules/night/run"),
]


@pytest.mark.parametrize(("method", "path"), SCHEDULE_ENDPOINTS)
def test_schedule_api_requires_login(controller_settings, method: str, path: str) -> None:  # type: ignore[no-untyped-def]
    """Расписание — тоже управление ПК: без входа недоступно."""
    from fastapi.testclient import TestClient

    from remo32_controller.app import create_app

    with TestClient(create_app(controller_settings, configure_logs=False)) as anon:
        assert anon.request(method, path).status_code == 401


def test_api_create_and_delete(sched_client) -> None:  # type: ignore[no-untyped-def]
    body = {
        "id": "night",
        "name": "Погасить свет",
        "at": "23:00",
        "days": [0, 1, 2, 3, 4],
        "pc_id": "testpc",
        "action_id": "rgb-off",
    }
    created = sched_client.post("/api/schedules", json=body)
    assert created.status_code == 201
    assert created.json()["data"]["at"] == "23:00"
    assert created.json()["request_id"]

    listed = sched_client.get("/api/schedules").json()["data"]
    assert len(listed) == 1

    assert sched_client.delete("/api/schedules/night").status_code == 200
    assert sched_client.get("/api/schedules").json()["data"] == []


def test_api_rejects_bad_time(sched_client) -> None:  # type: ignore[no-untyped-def]
    """Невалидное время — понятный отказ, а не 500."""
    response = sched_client.post(
        "/api/schedules",
        json={"id": "x", "name": "тест", "at": "25:99", "pc_id": "testpc", "action_id": "a"},
    )
    assert response.status_code == 422
    assert response.json()["ok"] is False


def test_api_rejects_unknown_pc(sched_client) -> None:  # type: ignore[no-untyped-def]
    response = sched_client.post(
        "/api/schedules",
        json={"id": "x", "name": "тест", "at": "23:00", "pc_id": "призрак", "action_id": "a"},
    )
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "pc_not_found"


def test_api_patch_is_partial(sched_client) -> None:  # type: ignore[no-untyped-def]
    sched_client.post(
        "/api/schedules",
        json={
            "id": "night",
            "name": "Свет",
            "at": "23:00",
            "pc_id": "testpc",
            "action_id": "rgb-off",
        },
    )
    response = sched_client.patch("/api/schedules/night", json={"enabled": False})
    assert response.status_code == 200
    data = response.json()["data"]
    assert data["enabled"] is False
    assert data["at"] == "23:00"


def test_api_unknown_schedule_is_404(sched_client) -> None:  # type: ignore[no-untyped-def]
    response = sched_client.get("/api/schedules/нет-такого")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "schedule_not_found"
