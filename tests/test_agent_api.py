"""API агента: аутентификация, статистика, действия, питание."""

from __future__ import annotations

from remo32_agent.execution import RecordingRunner

TOKEN = "test-token-" + "x" * 24


def test_ping_is_public(agent_client) -> None:  # type: ignore[no-untyped-def]
    response = agent_client.get("/ping", headers={"X-Remo32-Agent-Token": ""})
    assert response.status_code == 200
    assert response.json()["pong"] is True


def test_health_requires_token(agent_app) -> None:  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient

    with TestClient(agent_app) as client:
        response = client.get("/api/health")
        assert response.status_code == 401
        body = response.json()
        assert body["ok"] is False
        assert body["error"]["code"] == "unauthorized"


def test_wrong_token_rejected(agent_app) -> None:  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient

    with TestClient(agent_app) as client:
        response = client.get("/api/health", headers={"X-Remo32-Agent-Token": "wrong-token"})
        assert response.status_code == 401


def test_health_reports_state(agent_client) -> None:  # type: ignore[no-untyped-def]
    body = agent_client.get("/api/health").json()
    assert body["ok"] is True
    assert body["data"]["platform"] == "linux"
    assert body["data"]["action_count"] == 5
    assert body["data"]["terminal_enabled"] is False


def test_stats_never_crashes_and_marks_unavailable(agent_client) -> None:  # type: ignore[no-untyped-def]
    data = agent_client.get("/api/stats").json()["data"]
    assert data["platform"] == "linux"
    assert data["cpu"]["core_count"] > 0
    # Недоступные датчики отдаются как null, а не отсутствуют.
    assert "load_average" in data["cpu"]
    assert isinstance(data["degraded"], list)


def test_actions_listing_includes_availability(agent_client) -> None:  # type: ignore[no-untyped-def]
    actions = agent_client.get("/api/actions").json()["data"]
    by_id = {a["id"]: a for a in actions}
    assert by_id["missing-script"]["available"] is False
    assert by_id["beep"]["available"] is True


def test_unknown_action_returns_404(agent_client) -> None:  # type: ignore[no-untyped-def]
    response = agent_client.post("/api/actions/такого-нет")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "action_not_found"


def test_action_id_cannot_escape_to_other_paths(agent_client) -> None:  # type: ignore[no-untyped-def]
    """Идентификатор действия не должен превращаться в путь."""
    response = agent_client.post("/api/actions/..%2F..%2Fpower%2Fshutdown")
    assert response.status_code in (404, 405)


def test_shutdown_goes_through_recording_runner(agent_client, runner: RecordingRunner) -> None:  # type: ignore[no-untyped-def]
    """Ключевой тест безопасности: реальная машина не выключается."""
    body = agent_client.post("/api/power/shutdown").json()
    assert body["ok"] is True
    assert body["data"]["success"] is True
    assert runner.last_argv == ["shutdown", "-P", "+1"]


def test_terminal_info_when_disabled(agent_client) -> None:  # type: ignore[no-untyped-def]
    data = agent_client.get("/api/terminal").json()["data"]
    assert data["enabled"] is False
    assert data["sessions"] == []


def test_request_id_present_in_body_and_header(agent_client) -> None:  # type: ignore[no-untyped-def]
    response = agent_client.get("/api/health")
    assert response.headers["X-Remo32-Request-Id"]
    assert response.json()["request_id"] == response.headers["X-Remo32-Request-Id"]


def test_incoming_request_id_is_preserved(agent_client) -> None:  # type: ignore[no-untyped-def]
    """Контроллер и агент должны писать в лог один и тот же идентификатор."""
    response = agent_client.get("/api/health", headers={"X-Remo32-Request-Id": "abc123"})
    assert response.json()["request_id"] == "abc123"


def test_openapi_is_generated(agent_client) -> None:  # type: ignore[no-untyped-def]
    spec = agent_client.get("/openapi.json").json()
    assert "/api/actions/{action_id}" in spec["paths"]
    assert spec["info"]["title"] == "Remo32 Agent"
