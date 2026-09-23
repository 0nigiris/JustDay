"""Модель записи расписания.

Расписание намеренно простое: время суток плюс набор дней недели. Полный
cron сюда не берётся — его невозможно осмысленно редактировать пальцем на
телефоне, а именно этого требовал сценарий использования.

Время местное — то, что показывают часы на ПК, где работает контроллер.
Это единственный вариант, который не удивляет: «гасить свет в 23:00»
означает 23:00 на стене, а не UTC.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

TIME_RE = re.compile(r"^([01]\d|2[0-3]):([0-5]\d)$")

ScheduleId = Annotated[str, Field(pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")]

DAY_NAMES = ("пн", "вт", "ср", "чт", "пт", "сб", "вс")


def check_time(value: str | None) -> str | None:
    """Общая проверка для всех трёх моделей.

    Раньше валидатор стоял только на ``ScheduleEntry``, и через API можно
    было отправить «25:99»: тело запроса разбирается моделью ``Create``,
    а падало это уже внутри сервиса, отдавая 500 вместо внятного отказа.
    """
    if value is not None and not TIME_RE.match(value):
        raise ValueError("время указывается как ЧЧ:ММ, например 23:00")
    return value


def check_days(value: list[int] | None) -> list[int] | None:
    if value is None:
        return None
    for day in value:
        if not 0 <= day <= 6:
            raise ValueError("день недели — число от 0 (пн) до 6 (вс)")
    return sorted(set(value))


class ScheduleEntry(BaseModel):
    """Одно правило: «в такое-то время в такие-то дни выполнить действие»."""

    model_config = ConfigDict(extra="forbid")

    id: ScheduleId
    name: str = Field(min_length=1, max_length=120)
    enabled: bool = True

    at: str = Field(description="Местное время в формате ЧЧ:ММ")
    days: list[int] = Field(
        default_factory=list,
        description="Дни недели, 0 = понедельник. Пустой список — каждый день.",
    )

    pc_id: str = Field(min_length=1, max_length=64)
    action_id: str = Field(min_length=1, max_length=64)

    # Заполняется планировщиком, в API только для чтения.
    last_run_at: datetime | None = None
    last_ok: bool | None = None
    last_message: str | None = None
    last_fired_slot: str | None = Field(
        None,
        description=(
            "Метка последнего сработавшего слота, ГГГГ-ММ-ДД ЧЧ:ММ. "
            "Защита от повторного запуска в ту же минуту."
        ),
    )

    _validate_at = field_validator("at")(check_time)
    _validate_days = field_validator("days")(check_days)

    @property
    def hour(self) -> int:
        return int(self.at[:2])

    @property
    def minute(self) -> int:
        return int(self.at[3:])

    def matches_day(self, moment: datetime) -> bool:
        """Подходит ли день недели. Пустой список дней означает «ежедневно»."""
        return not self.days or moment.weekday() in self.days

    def slot_key(self, moment: datetime) -> str:
        return f"{moment:%Y-%m-%d} {self.at}"

    def human_days(self) -> str:
        if not self.days:
            return "ежедневно"
        return ", ".join(DAY_NAMES[d] for d in self.days)


class ScheduleCreate(BaseModel):
    """Тело запроса на создание. Поля результата запуска сюда не входят."""

    model_config = ConfigDict(extra="forbid")

    id: ScheduleId
    name: str = Field(min_length=1, max_length=120)
    enabled: bool = True
    at: str
    days: list[int] = Field(default_factory=list)
    pc_id: str = Field(min_length=1, max_length=64)
    action_id: str = Field(min_length=1, max_length=64)

    _validate_at = field_validator("at")(check_time)
    _validate_days = field_validator("days")(check_days)


class ScheduleUpdate(BaseModel):
    """Частичное изменение: передаются только те поля, что меняются."""

    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(None, min_length=1, max_length=120)
    enabled: bool | None = None
    at: str | None = None
    days: list[int] | None = None
    pc_id: str | None = Field(None, min_length=1, max_length=64)
    action_id: str | None = Field(None, min_length=1, max_length=64)

    _validate_at = field_validator("at")(check_time)
    _validate_days = field_validator("days")(check_days)
