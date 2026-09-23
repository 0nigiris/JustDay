"""Терминал: границы доступа и поведение сессий."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from remo32_agent.config import AgentSettings, TerminalSettings
from remo32_agent.context import AgentContext
from remo32_agent.execution import RecordingRunner
from remo32_agent.terminal.audit import TerminalAudit
from remo32_agent.terminal.session import TerminalConfig, build_attach_argv


def test_attach_command_reuses_or_creates_session() -> None:
    """new-session -A подключается к существующей сессии, а не плодит новые."""
    argv = build_attach_argv(TerminalConfig(session_name="remo32-main", workdir="/tmp"))
    assert argv[:6] == ["tmux", "-u", "new-session", "-A", "-s", "remo32-main"]
    assert argv[6:8] == ["-c", "/tmp"]


def test_session_name_is_prefixed_and_sanitised(agent_settings: AgentSettings) -> None:
    """Терминал не должен подключаться к посторонним tmux-сессиям."""
    ctx = AgentContext(agent_settings, runner=RecordingRunner())
    assert ctx.terminal_session_name("main") == "remo32-main"
    assert ctx.terminal_session_name("remo32-main") == "remo32-main"
    # Опасные символы вырезаются, имя остаётся внутри своего пространства.
    assert ctx.terminal_session_name("../../root") == "remo32-root"
    assert ctx.terminal_session_name("$(reboot)") == "remo32-reboot"
    assert ctx.terminal_session_name("") == "remo32-main"


def test_websocket_refused_when_terminal_disabled(agent_client) -> None:  # type: ignore[no-untyped-def]
    """По умолчанию терминал выключен, и подключиться нельзя."""
    with (
        pytest.raises(Exception),  # noqa: B017 — starlette закрывает соединение
        agent_client.websocket_connect("/api/terminal/ws"),
    ):
        pass


def test_websocket_requires_token(tmp_path: Path, agent_settings: AgentSettings) -> None:
    from fastapi.testclient import TestClient

    from remo32_agent.app import create_app

    agent_settings.terminal = TerminalSettings(enabled=True, audit_log=tmp_path / "audit.log")
    app = create_app(agent_settings, runner=RecordingRunner(), configure_logs=False)
    with (
        TestClient(app) as client,
        pytest.raises(Exception),  # noqa: B017
        client.websocket_connect("/api/terminal/ws?token=неверный"),
    ):
        pass


def test_audit_log_is_written_and_private(tmp_path: Path) -> None:
    path = tmp_path / "sub" / "audit.log"
    audit = TerminalAudit(path)
    audit.record("terminal_open", session="remo32-main", peer="100.64.0.1")
    audit.record("terminal_input", session="remo32-main", bytes=12)

    assert path.stat().st_mode & 0o077 == 0
    entries = [json.loads(line) for line in path.read_text().splitlines()]
    assert [e["event"] for e in entries] == ["terminal_open", "terminal_input"]
    assert entries[0]["peer"] == "100.64.0.1"
    assert "ts" in entries[0]


def test_audit_survives_unwritable_path(tmp_path: Path) -> None:
    """Невозможность вести журнал не должна ронять агент."""
    audit = TerminalAudit(Path("/proc/нельзя-писать/audit.log"))
    audit.record("terminal_open", session="x")  # не должно бросить


def test_terminal_disabled_by_default() -> None:
    assert TerminalSettings().enabled is False


# --- ротация журнала аудита --------------------------------------------------


def test_журнал_аудита_подрезается_по_размеру(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Разросшийся журнал откладывается в .1, запись продолжается в новый.

    Журнал пишется в каждую сессию и сам не заканчивается: без этого он
    однажды заполнил бы диск молча.
    """
    from remo32_agent.terminal.audit import TerminalAudit

    path = tmp_path / "audit.log"
    audit = TerminalAudit(path, max_bytes=200, keep=2)

    for i in range(50):
        audit.record("команда", command=f"строка номер {i}")

    assert path.exists()
    assert path.stat().st_size < 200 * 2  # текущий файл остался небольшим
    assert (tmp_path / "audit.log.1").exists()
    # Имя второго поколения — audit.log.2, а не audit.log.1.2.
    assert not list(tmp_path.glob("*.1.*"))


def test_старые_поколения_журнала_удаляются(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """Хранить бесконечно — это просто отложить ту же проблему."""
    from remo32_agent.terminal.audit import TerminalAudit

    path = tmp_path / "audit.log"
    audit = TerminalAudit(path, max_bytes=100, keep=2)
    for i in range(200):
        audit.record("команда", command=f"довольно длинная строка номер {i}")

    generations = sorted(p.name for p in tmp_path.iterdir())
    assert generations == ["audit.log", "audit.log.1", "audit.log.2"]


def test_ротацию_можно_выключить(tmp_path) -> None:  # type: ignore[no-untyped-def]
    """0 означает «не подрезать»: на чужой машине это может быть нужно."""
    from remo32_agent.terminal.audit import TerminalAudit

    path = tmp_path / "audit.log"
    audit = TerminalAudit(path, max_bytes=0, keep=3)
    for i in range(100):
        audit.record("команда", command=f"строка номер {i}")

    assert [p.name for p in tmp_path.iterdir()] == ["audit.log"]
