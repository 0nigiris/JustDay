"""Сообщения, оставленные без связи, и планы из Obsidian.

Смысл этой пары в том, что компьютера рядом может не быть. Значит, проверяем
не «дошло ли», а «не потерялось ли»: текст уходит ассистенту как есть, вместе
со временем, когда его набрали, а планы читаются и закрываются теми же
словами, какими их видит человек в Obsidian.
"""

from __future__ import annotations

from typing import Any

import pytest
from fastapi.testclient import TestClient

from remo32_controller.config import ControllerSettings


@pytest.fixture
def controller_app(controller_settings: ControllerSettings):  # type: ignore[no-untyped-def]
    from remo32_controller.app import create_app

    return create_app(controller_settings, configure_logs=False)


@pytest.fixture
def anon(controller_app):  # type: ignore[no-untyped-def]
    with TestClient(controller_app) as client:
        yield client


class TestОчередьСообщений:
    def test_сообщение_уходит_ассистенту_со_временем(self, agent_client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        видел: dict[str, Any] = {}

        async def fake(command: str, **payload: Any) -> dict[str, Any]:
            видел.update(cmd=command, **payload)
            return {"ok": True, "id": "abc", "pending": 1}

        monkeypatch.setattr("remo32_agent.justday.call", fake)
        response = agent_client.post(
            "/api/justday/inbox", json={"text": "купить хлеб", "created": 1700000000.0}
        )
        assert response.status_code == 200
        assert response.json()["data"]["pending"] == 1
        assert видел["cmd"] == "inbox_add"
        assert видел["text"] == "купить хлеб"
        # Важно именно время набора: сообщение могло пролежать в телефоне сутки.
        assert видел["created"] == 1700000000.0
        assert видел["source"] == "phone"

    def test_пустое_сообщение_не_принимается(self, agent_client) -> None:  # type: ignore[no-untyped-def]
        assert agent_client.post("/api/justday/inbox", json={"text": ""}).status_code == 422

    def test_слишком_длинное_не_принимается(self, agent_client) -> None:  # type: ignore[no-untyped-def]
        response = agent_client.post("/api/justday/inbox", json={"text": "а" * 4001})
        assert response.status_code == 422

    def test_список_отдаётся_как_есть(self, agent_client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        async def fake(command: str, **payload: Any) -> dict[str, Any]:
            assert command == "inbox_list"
            return {"ok": True, "items": [{"id": "1", "text": "привет"}], "pending": 0}

        monkeypatch.setattr("remo32_agent.justday.call", fake)
        data = agent_client.get("/api/justday/inbox").json()["data"]
        assert data["items"][0]["text"] == "привет"


class TestПланы:
    def test_открытые_пункты_по_умолчанию(self, agent_client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        видел: dict[str, Any] = {}

        async def fake(command: str, **payload: Any) -> dict[str, Any]:
            видел.update(cmd=command, **payload)
            return {"ok": True, "items": [{"n": 1, "text": "купить микрофон", "done": False}]}

        monkeypatch.setattr("remo32_agent.justday.call", fake)
        data = agent_client.get("/api/justday/plans").json()["data"]
        assert data["items"][0]["text"] == "купить микрофон"
        assert видел["cmd"] == "plan_list"
        assert видел["open"] is True

    def test_закрытые_показываем_по_просьбе(self, agent_client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        видел: dict[str, Any] = {}

        async def fake(command: str, **payload: Any) -> dict[str, Any]:
            видел.update(**payload)
            return {"ok": True, "items": []}

        monkeypatch.setattr("remo32_agent.justday.call", fake)
        agent_client.get("/api/justday/plans", params={"closed": "true"})
        assert видел["open"] is False

    def test_добавление_и_закрытие_идут_разными_командами(self, agent_client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        команды: list[str] = []

        async def fake(command: str, **payload: Any) -> dict[str, Any]:
            команды.append(command)
            return {"ok": True}

        monkeypatch.setattr("remo32_agent.justday.call", fake)
        agent_client.post("/api/justday/plans", json={"text": "позвонить", "note": "с телефона"})
        agent_client.post("/api/justday/plans", json={"text": "позвонить", "done": True})
        assert команды == ["plan_add", "plan_done"]


class TestОболочкаБезСети:
    """То, без чего приложение не откроется в дороге."""

    def test_service_worker_отдаётся_из_корня(self, anon) -> None:  # type: ignore[no-untyped-def]
        response = anon.get("/sw.js")
        assert response.status_code == 200
        assert "javascript" in response.headers["content-type"]
        # Заглушки должны быть заменены: иначе кэш не соберётся.
        assert "__PRECACHE__" not in response.text
        assert "__ASSET_VERSION__" not in response.text

    def test_в_кэш_попадает_вся_оболочка(self) -> None:
        from remo32_controller.app import precache_list

        files = precache_list()
        assert "/" in files
        assert any(f.startswith("/static/app.js") for f in files)
        assert any(f.startswith("/static/style.css") for f in files)
        assert any("/static/icons/" in f for f in files)
        # Стенд для разработки в приложение не едет.
        assert not any("preview" in f for f in files)

    def test_favicon_не_404(self, anon) -> None:  # type: ignore[no-untyped-def]
        response = anon.get("/favicon.ico")
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("image/")


@pytest.mark.parametrize("path", ["/sw.js", "/favicon.ico"])
def test_оболочка_доступна_без_входа(anon, path: str) -> None:  # type: ignore[no-untyped-def]
    """Иначе приложение без связи показало бы экран входа вместо пульта."""
    assert anon.get(path).status_code == 200
