"""Общие приспособления для тестов.

Главное правило набора: ни один тест не выполняет настоящих системных
команд. Везде, где агент мог бы что-то запустить, подставляется
:class:`RecordingRunner`, который только записывает вызовы.

Поэтому запуск ``pytest`` физически не способен выключить компьютер.
"""

from __future__ import annotations

import os
from collections.abc import Iterator
from pathlib import Path

import pytest

# Секреты для тестов задаются до импорта настроек: конфигурация проверяет
# их наличие на этапе создания объекта.
os.environ.setdefault("REMO32_AGENT_TOKEN", "test-token-" + "x" * 24)
os.environ.setdefault("REMO32_PASSWORD_HASH", "")

from remo32_agent.actions.models import (
    DesktopAction,
    ExecAction,
    ShellScriptAction,
    SystemdAction,
    TmuxAction,
)
from remo32_agent.config import (
    ActionsSettings,
    AgentSettings,
    PowerSettings,
    SecuritySettings,
    ServerSettings,
    TerminalSettings,
)
from remo32_agent.execution import RecordingRunner
from remo32_controller.auth.passwords import hash_password
from remo32_controller.config import (
    AuthSettings,
    ControllerSettings,
    Esp32Settings,
    PcConfig,
    PollerSettings,
    WolSettings,
)
from remo32_controller.config import (
    ServerSettings as CtlServerSettings,
)

TEST_TOKEN = "test-token-" + "x" * 24
TEST_PASSWORD = "тестовый-пароль-12345"


@pytest.fixture
def runner() -> RecordingRunner:
    """Исполнитель, который ничего не исполняет."""
    return RecordingRunner()


@pytest.fixture
def sample_actions() -> list[object]:
    return [
        ExecAction(id="beep", name="Пикнуть", argv=["/usr/bin/true"], group="Тест"),
        TmuxAction(
            id="claude",
            name="Claude Code",
            session="claude",
            workdir="/tmp",
            argv=["claude", "-c"],
            group="Разработка",
        ),
        SystemdAction(
            id="mc-start",
            name="Minecraft: старт",
            kind="systemd_user",
            unit="minecraft.service",
            verb="start",
            group="Minecraft",
        ),
        DesktopAction(id="obs", name="OBS", argv=["/usr/bin/true"], group="Игры"),
        ShellScriptAction(
            id="missing-script",
            name="Отсутствующий скрипт",
            script="/nonexistent/remo32/script.sh",
            group="Тест",
        ),
    ]


@pytest.fixture
def agent_settings(tmp_path: Path, sample_actions: list[object]) -> AgentSettings:
    return AgentSettings(
        agent_id="testpc",
        display_name="Тестовый ПК",
        server=ServerSettings(host="127.0.0.1", port=8765, log_level="ERROR"),
        security=SecuritySettings(),
        # dry_run НЕ включаем: хотим проверить, что именно ушло бы в систему,
        # а безопасность обеспечивает RecordingRunner.
        power=PowerSettings(dry_run=False, delay_seconds=5),
        terminal=TerminalSettings(enabled=False, audit_log=tmp_path / "audit.log"),
        # Хранилище кнопок обязательно уводим в tmp_path: со значением по
        # умолчанию тест писал бы в ~/.config/remo32/actions.toml и стирал
        # настоящие кнопки того, кто запустил pytest.
        actions_editor=ActionsSettings(store_path=tmp_path / "actions.toml"),
        actions=sample_actions,
    )


@pytest.fixture
def agent_app(agent_settings: AgentSettings, runner: RecordingRunner):  # type: ignore[no-untyped-def]
    from remo32_agent.app import create_app

    return create_app(agent_settings, runner=runner, configure_logs=False)


@pytest.fixture
def agent_client(agent_app):  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient

    with TestClient(agent_app) as client:
        client.headers.update({"X-Remo32-Agent-Token": TEST_TOKEN})
        yield client


@pytest.fixture
def password_hash() -> str:
    return hash_password(TEST_PASSWORD)


@pytest.fixture
def controller_settings(tmp_path: Path, password_hash: str) -> Iterator[ControllerSettings]:
    previous = os.environ.get("REMO32_PASSWORD_HASH")
    os.environ["REMO32_PASSWORD_HASH"] = password_hash
    settings = ControllerSettings(
        server=CtlServerSettings(host="127.0.0.1", port=8080, log_level="ERROR"),
        auth=AuthSettings(
            password_enabled=True,
            webauthn_enabled=False,
            cookie_secure=False,
            max_failed_attempts=3,
            lockout_seconds=60,
        ),
        poller=PollerSettings(interval_seconds=1.0, timeout_seconds=0.5),
        esp32=Esp32Settings(transport="mock", poll_interval_seconds=60.0),
        wol=WolSettings(enabled=False),  # в тестах не шлём пакеты в реальную сеть
        pcs=[
            PcConfig(
                id="testpc",
                name="Тестовый ПК",
                agent_url="http://127.0.0.1:59901",
                mac_address="5c:f9:dd:11:22:33",
                terminal_enabled=False,
                hosts_controller=True,
            ),
            PcConfig(
                id="nomac",
                name="ПК без MAC",
                agent_url="http://127.0.0.1:59902",
            ),
        ],
        data_dir=tmp_path / "data",
    )
    yield settings
    if previous is None:
        os.environ.pop("REMO32_PASSWORD_HASH", None)
    else:
        os.environ["REMO32_PASSWORD_HASH"] = previous
