"""Конфигурация контроллера.

Как и у агента: значения по умолчанию → TOML → переменные окружения.
Секретов в TOML нет. Токены агентов, пароль и ключ подписи сессий берутся
только из окружения или из файлов с правами 0600.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

from remo32_core.errors import ConfigurationError
from remo32_core.models import DeviceId, MacAddress

DEFAULT_CONFIG_PATHS = (
    Path("config/controller.toml"),
    Path("~/.config/remo32/controller.toml"),
    Path("/etc/remo32/controller.toml"),
)

SESSION_SECRET_ENV = "REMO32_SESSION_SECRET"  # noqa: S105
PASSWORD_HASH_ENV = "REMO32_PASSWORD_HASH"  # noqa: S105
MQTT_PASSWORD_ENV = "REMO32_MQTT_PASSWORD"  # noqa: S105
ESP32_TOKEN_ENV = "REMO32_ESP32_TOKEN"  # noqa: S105


def _config_path() -> Path | None:
    explicit = os.environ.get("REMO32_CONTROLLER_CONFIG")
    if explicit:
        path = Path(explicit).expanduser()
        if not path.is_file():
            raise ConfigurationError(f"файл конфигурации не найден: {path}")
        return path
    for candidate in DEFAULT_CONFIG_PATHS:
        expanded = candidate.expanduser()
        if expanded.is_file():
            return expanded
    return None


def read_secret(env_var: str, file_path: Path | None = None) -> str | None:
    """Секрет из переменной окружения либо из файла с правами 0600."""
    value = os.environ.get(env_var)
    if value:
        return value.strip()
    if file_path is None:
        return None
    path = file_path.expanduser()
    if not path.is_file():
        return None
    if path.stat().st_mode & 0o077:
        raise ConfigurationError(
            f"файл секрета доступен посторонним: {path}; выполните chmod 600 {path}"
        )
    return path.read_text(encoding="utf-8").strip()


class ServerSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    host: str = Field(
        "127.0.0.1",
        description=(
            "Адрес прослушивания. Для доступа с телефона укажите адрес Tailscale "
            "этой машины (tailscale ip -4), а НЕ 0.0.0.0 — контроллер не должен "
            "быть доступен из домашней сети целиком, а тем более из интернета."
        ),
    )
    port: int = Field(8080, ge=1, le=65535)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["console", "json"] = "console"
    public_origin: str | None = Field(
        None,
        description=(
            "Полный адрес, по которому вы открываете интерфейс, например "
            "https://desktop.tailnet-abc123.ts.net:8080. Нужен для passkey."
        ),
    )


class AuthSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    session_ttl_hours: int = Field(720, ge=1, le=8760)
    cookie_name: str = "remo32_session"
    cookie_secure: bool = Field(
        True,
        description=(
            "Cookie только по HTTPS. Отключайте лишь для локальной разработки на http://127.0.0.1."
        ),
    )
    password_enabled: bool = Field(
        True,
        description=(
            "Вход по паролю. Оставьте включённым даже при использовании passkey: "
            "это единственный способ восстановить доступ, если passkey потерян "
            "или изменился адрес контроллера."
        ),
    )
    password_hash_file: Path | None = None
    session_secret_file: Path | None = None

    webauthn_enabled: bool = True
    webauthn_rp_id: str | None = Field(
        None,
        description=(
            "Домен для passkey, например desktop.tailnet-abc123.ts.net. "
            "Passkey привязан к домену: при смене адреса ключи перестанут работать."
        ),
    )
    webauthn_rp_name: str = "Remo32"

    max_failed_attempts: int = Field(10, ge=1, le=100)
    lockout_seconds: int = Field(300, ge=10, le=86400)

    def resolve_password_hash(self) -> str | None:
        return read_secret(PASSWORD_HASH_ENV, self.password_hash_file)

    def resolve_session_secret(self) -> str | None:
        return read_secret(SESSION_SECRET_ENV, self.session_secret_file)


class PollerSettings(BaseModel):
    model_config = ConfigDict(extra="forbid")

    interval_seconds: float = Field(5.0, ge=1.0, le=300.0)
    timeout_seconds: float = Field(3.0, ge=0.5, le=60.0)
    stale_after_seconds: float = Field(
        30.0, ge=5.0, description="После этого возраста данные помечаются устаревшими"
    )
    offline_after_failures: int = Field(
        2, ge=1, le=10, description="Сколько неудачных опросов подряд считать выключением"
    )


class PcConfig(BaseModel):
    """Описание управляемого ПК."""

    model_config = ConfigDict(extra="forbid")

    id: DeviceId
    name: str = Field(min_length=1, max_length=120)
    description: str | None = None
    agent_url: str = Field(description="Базовый адрес агента, например http://100.64.0.10:8765")
    agent_token_env: str | None = Field(
        None,
        description=(
            "Имя переменной окружения с токеном этого агента. Сам токен в конфигурации не хранится."
        ),
    )
    agent_token_file: Path | None = None
    mac_address: MacAddress | None = Field(None, description="Нужен для Wake-on-LAN")
    broadcast_address: str = Field(
        "255.255.255.255",
        description=(
            "Куда слать magic packet. Точнее работает широковещательный адрес "
            "подсети, например 192.168.1.255."
        ),
    )
    wol_port: int = Field(9, ge=1, le=65535)
    kvm_port: int | None = Field(
        None, ge=1, le=16, description="Номер входа KVM, если он подключён к ESP32"
    )
    terminal_enabled: bool = Field(
        False, description="Разрешить веб-терминал для этого ПК (агент тоже должен его включить)"
    )
    terminal_workdir: str | None = None

    guarded_by_esp32: bool = Field(
        False,
        description=(
            "За этим ПК следит сторож на плате и поднимает его сам, если тот "
            "пропал. Перед плановым выключением контроллер предупредит плату, "
            "иначе она включит машину обратно."
        ),
    )
    guard_snooze_minutes: int = Field(
        480,
        ge=0,
        le=1440,
        description="На сколько минут просить сторожа замолчать при плановом выключении",
    )

    @field_validator("agent_url")
    @classmethod
    def _valid_url(cls, v: str) -> str:
        if not v.startswith(("http://", "https://")):
            raise ValueError("agent_url должен начинаться с http:// или https://")
        return v.rstrip("/")

    def resolve_token(self) -> str | None:
        if self.agent_token_env:
            value = os.environ.get(self.agent_token_env)
            if value:
                return value.strip()
        if self.agent_token_file:
            return read_secret("", self.agent_token_file)
        # Общий токен для всех агентов — упрощение для домашней установки.
        shared = os.environ.get("REMO32_AGENT_TOKEN")
        return shared.strip() if shared else None


class Esp32Settings(BaseModel):
    """Подключение к аппаратному контроллеру.

    ``transport`` определяет, с кем на самом деле разговаривает контроллер:

    * ``mock``  — встроенный симулятор в этом же процессе;
    * ``http``  — реальное устройство с HTTP-сервером в домашней сети;
    * ``mqtt``  — реальное устройство через брокер (работает и снаружи дома).

    Смена значения не требует изменения кода: интерфейс транспорта один.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    transport: Literal["mock", "http", "mqtt"] = "mock"
    device_id: str = Field("esp32-main", pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$")
    name: str = "ESP32"
    timeout_seconds: float = Field(5.0, ge=0.5, le=60.0)
    poll_interval_seconds: float = Field(10.0, ge=1.0, le=300.0)
    offline_after_seconds: float = Field(
        45.0, ge=5.0, description="Нет вестей дольше этого срока — считаем офлайном"
    )

    # transport = "http"
    base_url: str | None = Field(None, description="Например http://192.168.1.50")
    token_env: str = ESP32_TOKEN_ENV

    # transport = "mqtt"
    mqtt_host: str | None = None
    mqtt_port: int = Field(8883, ge=1, le=65535)
    mqtt_tls: bool = True
    mqtt_username: str | None = None
    mqtt_password_env: str = MQTT_PASSWORD_ENV
    mqtt_topic_prefix: str = Field("remo32", pattern=r"^[a-zA-Z0-9_/-]{1,64}$")
    mqtt_keepalive: int = Field(30, ge=5, le=600)

    @model_validator(mode="after")
    def _check_transport(self) -> Esp32Settings:
        if not self.enabled:
            return self
        if self.transport == "http" and not self.base_url:
            raise ValueError('для transport = "http" требуется base_url')
        if self.transport == "mqtt" and not self.mqtt_host:
            raise ValueError('для transport = "mqtt" требуется mqtt_host')
        return self


class WolSettings(BaseModel):
    """Wake-on-LAN силами самого контроллера.

    Работает, только если контроллер находится в одной сети с целевым ПК:
    широковещательный пакет не проходит через Tailscale. Если контроллер
    снаружи — пробуждение уходит через ESP32.
    """

    model_config = ConfigDict(extra="forbid")

    enabled: bool = True
    repeat: int = Field(3, ge=1, le=10)
    prefer_esp32: bool = Field(
        False,
        description="Сначала пробовать ESP32, потом собственный пакет. По умолчанию наоборот.",
    )


class ControllerSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="REMO32_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
        toml_file=_config_path(),
    )

    server: ServerSettings = Field(default_factory=ServerSettings)
    auth: AuthSettings = Field(default_factory=AuthSettings)
    poller: PollerSettings = Field(default_factory=PollerSettings)
    esp32: Esp32Settings = Field(default_factory=Esp32Settings)
    wol: WolSettings = Field(default_factory=WolSettings)
    pcs: list[PcConfig] = Field(default_factory=list)
    data_dir: Path = Field(
        Path("~/.local/share/remo32"),
        description="Где хранятся passkey и служебные файлы",
    )

    @field_validator("pcs")
    @classmethod
    def _unique_pc_ids(cls, v: list[PcConfig]) -> list[PcConfig]:
        seen: set[str] = set()
        for pc in v:
            if pc.id in seen:
                raise ValueError(f"дублирующийся идентификатор ПК: {pc.id}")
            seen.add(pc.id)
        return v

    @model_validator(mode="after")
    def _check_auth(self) -> ControllerSettings:
        if self.auth.password_enabled and self.auth.resolve_password_hash() is None:
            raise ConfigurationError(
                f"не задан хэш пароля. Сгенерируйте его командой "
                f"`remo32-controller --hash-password` и положите в {PASSWORD_HASH_ENV}"
            )
        if self.auth.webauthn_enabled and not self.auth.webauthn_rp_id:
            # Не ошибка: passkey просто не будет предложен, пока домен не задан.
            object.__setattr__(self.auth, "webauthn_enabled", False)
        return self

    def resolved_data_dir(self) -> Path:
        path = self.data_dir.expanduser()
        path.mkdir(parents=True, exist_ok=True)
        return path

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (
            init_settings,
            env_settings,
            dotenv_settings,
            TomlConfigSettingsSource(settings_cls),
            file_secret_settings,
        )


def load_settings(**overrides: Any) -> ControllerSettings:
    try:
        return ControllerSettings(**overrides)
    except ConfigurationError:
        raise
    except Exception as exc:
        raise ConfigurationError(f"конфигурация контроллера некорректна: {exc}") from exc


def generate_session_secret() -> str:
    return secrets.token_urlsafe(48)
