"""Конфигурация агента.

Источники, в порядке возрастания приоритета:

1. значения по умолчанию из этого файла;
2. TOML-файл (путь в ``REMO32_AGENT_CONFIG``);
3. переменные окружения с префиксом ``REMO32_AGENT_``;
4. файл ``.env`` рядом с рабочим каталогом.

Секретов в TOML нет и быть не должно: токен доступа читается только из
переменной окружения или из отдельного файла, путь к которому задан в
конфигурации. Так конфиг можно спокойно коммитить.
"""

from __future__ import annotations

import os
import secrets
from pathlib import Path
from typing import Any, Literal

from pydantic import Field, SecretStr, field_validator, model_validator
from pydantic_settings import (
    BaseSettings,
    PydanticBaseSettingsSource,
    SettingsConfigDict,
    TomlConfigSettingsSource,
)

from remo32_agent.actions.models import ActionConfig
from remo32_core.errors import ConfigurationError

DEFAULT_CONFIG_PATHS = (
    Path("config/agent.toml"),
    Path("~/.config/remo32/agent.toml"),
    Path("/etc/remo32/agent.toml"),
)

TOKEN_ENV_VAR = "REMO32_AGENT_TOKEN"  # noqa: S105 — имя переменной, не значение
MIN_TOKEN_LENGTH = 24


def _config_path() -> Path | None:
    explicit = os.environ.get("REMO32_AGENT_CONFIG")
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


class ServerSettings(BaseSettings):
    """Где агент слушает.

    По умолчанию ``127.0.0.1`` — агент не виден никому, кроме самой машины.
    Чтобы контроллер мог достучаться, адрес нужно задать осознанно: либо
    адрес Tailscale, либо адрес в домашней сети.
    """

    host: str = "127.0.0.1"
    port: int = Field(8765, ge=1, le=65535)
    log_level: Literal["DEBUG", "INFO", "WARNING", "ERROR"] = "INFO"
    log_format: Literal["console", "json"] = "console"


class SecuritySettings(BaseSettings):
    """Аутентификация контроллера перед агентом.

    Даже внутри Tailscale агент требует токен: сеть Tailscale — это ещё не
    аутентификация приложения, и в тайлнете могут оказаться чужие узлы.
    """

    token: SecretStr | None = Field(
        None, description="Задаётся ТОЛЬКО через окружение или token_file"
    )
    token_file: Path | None = Field(None, description="Файл с токеном; права должны быть 0600")
    allow_insecure_no_token: bool = Field(
        False,
        description=(
            "Разрешить работу без токена. Только для локальной разработки — "
            "агент при этом громко ругается в лог."
        ),
    )

    def resolve_token(self) -> str | None:
        """Достаёт токен из окружения или файла."""
        from_env = os.environ.get(TOKEN_ENV_VAR)
        if from_env:
            return from_env.strip()
        if self.token is not None:
            return self.token.get_secret_value()
        if self.token_file is not None:
            path = self.token_file.expanduser()
            if not path.is_file():
                raise ConfigurationError(f"файл токена не найден: {path}")
            mode = path.stat().st_mode & 0o077
            if mode:
                raise ConfigurationError(
                    f"файл токена доступен посторонним ({oct(path.stat().st_mode & 0o777)}); "
                    f"выполните: chmod 600 {path}"
                )
            return path.read_text(encoding="utf-8").strip()
        return None


class PowerSettings(BaseSettings):
    shutdown_enabled: bool = True
    restart_enabled: bool = True
    lock_enabled: bool = True
    dry_run: bool = Field(False, description="Логировать операции питания, но не выполнять их")
    delay_seconds: int = Field(5, ge=0, le=3600)


class TerminalSettings(BaseSettings):
    """Удалённый терминал.

    Выключен по умолчанию. Это самая мощная возможность системы, и её
    включение должно быть осознанным действием, а не побочным эффектом
    установки.
    """

    enabled: bool = False
    session_prefix: str = Field("remo32", pattern=r"^[A-Za-z0-9_-]{1,32}$")
    default_session: str = Field("main", pattern=r"^[A-Za-z0-9_-]{1,32}$")
    shell: str | None = Field(None, description="Оболочка; по умолчанию — из $SHELL")
    max_sessions: int = Field(4, ge=1, le=32)
    idle_timeout_seconds: int = Field(3600, ge=60, le=86400)
    audit_log: Path | None = Field(
        Path("~/.local/share/remo32/terminal-audit.log"),
        description="Куда писать журнал подключений и ввода",
    )
    scrollback_lines: int = Field(2000, ge=100, le=50_000)

    # Журнал пишется в каждую сессию и сам не заканчивается. На домашней
    # машине он растёт медленно, но растёт всегда — и однажды заполнит
    # диск молча, потому что смотреть в него никто не ходит.
    audit_max_bytes: int = Field(
        2_000_000,
        ge=0,
        description="Размер, после которого журнал откладывается в .1. 0 — не подрезать",
    )
    audit_keep: int = Field(
        3, ge=1, le=20, description="Сколько прошлых журналов хранить (.1, .2, ...)"
    )


class AgentSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="REMO32_AGENT_",
        env_nested_delimiter="__",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="forbid",
        toml_file=_config_path(),
    )

    agent_id: str = Field(
        "local", pattern=r"^[a-z0-9][a-z0-9_-]{0,63}$", description="Идентификатор этого ПК"
    )
    display_name: str = Field("Этот ПК", max_length=120)
    server: ServerSettings = Field(default_factory=ServerSettings)
    security: SecuritySettings = Field(default_factory=SecuritySettings)
    power: PowerSettings = Field(default_factory=PowerSettings)
    terminal: TerminalSettings = Field(default_factory=TerminalSettings)
    actions: list[ActionConfig] = Field(default_factory=list)

    @field_validator("actions")
    @classmethod
    def _unique_ids(cls, v: list[ActionConfig]) -> list[ActionConfig]:
        seen: set[str] = set()
        for action in v:
            if action.id in seen:
                raise ValueError(f"дублирующийся идентификатор действия: {action.id}")
            seen.add(action.id)
        return v

    @model_validator(mode="after")
    def _check_security(self) -> AgentSettings:
        token = self.security.resolve_token()
        if token is None and not self.security.allow_insecure_no_token:
            raise ConfigurationError(
                f"не задан токен агента. Установите переменную {TOKEN_ENV_VAR} "
                f"или security.token_file, либо явно включите "
                f"security.allow_insecure_no_token для локальной разработки"
            )
        if token is not None and len(token) < MIN_TOKEN_LENGTH:
            raise ConfigurationError(
                f"токен слишком короткий: минимум {MIN_TOKEN_LENGTH} символов "
                f"(сгенерируйте: python -c 'import secrets;print(secrets.token_urlsafe(32))')"
            )
        return self

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


def load_settings(**overrides: Any) -> AgentSettings:
    """Загружает конфигурацию, превращая ошибки валидации в понятный текст."""
    try:
        return AgentSettings(**overrides)
    except ConfigurationError:
        raise
    except Exception as exc:
        raise ConfigurationError(f"конфигурация агента некорректна: {exc}") from exc


def generate_token() -> str:
    """Токен для первичной настройки."""
    return secrets.token_urlsafe(32)
