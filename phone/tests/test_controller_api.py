"""API контроллера: доступ, конверт ответа, поведение при отказах."""

from __future__ import annotations

import pytest
from conftest import TEST_PASSWORD
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


@pytest.fixture
def client(anon: TestClient) -> TestClient:
    response = anon.post("/api/auth/login", json={"password": TEST_PASSWORD})
    assert response.status_code == 200
    return anon


PROTECTED = [
    ("GET", "/api/pcs"),
    ("GET", "/api/pcs/testpc"),
    ("GET", "/api/pcs/testpc/stats"),
    ("POST", "/api/pcs/testpc/wake"),
    ("POST", "/api/pcs/testpc/shutdown"),
    ("POST", "/api/pcs/testpc/restart"),
    ("GET", "/api/pcs/testpc/actions"),
    ("POST", "/api/pcs/testpc/actions/beep"),
    ("GET", "/api/esp32/status"),
    ("POST", "/api/esp32/refresh"),
    ("GET", "/api/events"),
]


@pytest.mark.parametrize(("method", "path"), PROTECTED)
def test_every_endpoint_requires_login(anon: TestClient, method: str, path: str) -> None:
    """Tailscale — не аутентификация: без входа не должно работать ничего."""
    response = anon.request(method, path)
    assert response.status_code == 401, path
    assert response.json()["error"]["code"] == "unauthorized"


def test_health_is_public_but_reveals_little(anon: TestClient) -> None:
    data = anon.get("/api/health").json()["data"]
    assert data["pcs_total"] == 2
    assert set(data) == {
        "status",
        "version",
        "pcs_total",
        "pcs_online",
        "esp32_state",
        "esp32_simulated",
        "terminal_enabled_pcs",
    }


def test_login_with_wrong_password_fails(anon: TestClient) -> None:
    response = anon.post("/api/auth/login", json={"password": "неверный"})
    assert response.status_code == 401


def test_login_sets_httponly_cookie(anon: TestClient) -> None:
    response = anon.post("/api/auth/login", json={"password": TEST_PASSWORD})
    cookie = response.headers.get("set-cookie", "")
    assert "HttpOnly" in cookie
    assert "SameSite=lax" in cookie.replace("samesite", "SameSite")


def test_logout_invalidates_session(client: TestClient) -> None:
    assert client.get("/api/pcs").status_code == 200
    client.post("/api/auth/logout")
    assert client.get("/api/pcs").status_code == 401


def test_pcs_listing_works_even_when_all_offline(client: TestClient) -> None:
    """Недоступные ПК не должны мешать отдать список."""
    body = client.get("/api/pcs").json()
    assert body["ok"] is True
    assert {pc["id"] for pc in body["data"]} == {"testpc", "nomac"}


def test_unknown_pc_returns_404(client: TestClient) -> None:
    response = client.get("/api/pcs/нет-такого")
    assert response.status_code == 404
    assert response.json()["error"]["code"] == "pc_not_found"


def test_offline_pc_stats_returns_503_not_500(client: TestClient) -> None:
    """Выключенный ПК — ожидаемое состояние, а не поломка контроллера."""
    response = client.get("/api/pcs/testpc/stats")
    assert response.status_code == 503
    assert response.json()["error"]["code"] in {"device_unreachable", "device_timeout"}


def test_wake_without_mac_is_reported(client: TestClient) -> None:
    response = client.post("/api/pcs/nomac/wake")
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "wake_failed"


def test_esp32_status_marks_simulation(client: TestClient) -> None:
    data = client.get("/api/esp32/status").json()["data"]
    assert data["simulated"] is True


def test_kvm_switch_without_hardware_returns_501(client: TestClient) -> None:
    response = client.post("/api/esp32/switch", json={"pc_id": "testpc"})
    assert response.status_code == 501
    assert response.json()["error"]["code"] == "capability_unavailable"


def test_validation_error_has_stable_shape(client: TestClient) -> None:
    response = client.post("/api/esp32/gpio", json={"pin": 999, "level": True})
    assert response.status_code == 422
    body = response.json()
    assert body["ok"] is False
    assert body["error"]["code"] == "validation_error"


def test_every_response_carries_request_id(client: TestClient) -> None:
    for path in ("/api/pcs", "/api/health", "/api/auth/status"):
        response = client.get(path)
        assert response.json()["request_id"] == response.headers["X-Remo32-Request-Id"]


def test_openapi_documents_everything(anon: TestClient) -> None:
    spec = anon.get("/openapi.json").json()
    paths = spec["paths"]
    for required in (
        "/api/pcs",
        "/api/pcs/{pc_id}/stats",
        "/api/pcs/{pc_id}/wake",
        "/api/pcs/{pc_id}/actions/{action_id}",
        "/api/esp32/status",
    ):
        assert required in paths, required


def test_web_interface_is_served(anon: TestClient) -> None:
    response = anon.get("/")
    assert response.status_code == 200
    assert "JustDay" in response.text
    assert response.headers["content-type"].startswith("text/html")


def test_bruteforce_is_throttled(anon: TestClient, controller_settings: ControllerSettings) -> None:
    for _ in range(controller_settings.auth.max_failed_attempts):
        anon.post("/api/auth/login", json={"password": "неверный"})
    response = anon.post("/api/auth/login", json={"password": TEST_PASSWORD})
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "forbidden"


def test_agent_token_mismatch_does_not_log_user_out(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Расхождение токенов агента — ошибка настройки, а не выход из системы.

    Если бы контроллер отдавал 401, браузер решил бы, что сессия истекла, и
    выбросил владельца на экран входа из-за чужой проблемы.
    """
    from remo32_core.errors import AgentAuthError

    async def reject(*args: object, **kwargs: object) -> None:
        raise AgentAuthError("агент отверг токен контроллера")

    monkeypatch.setattr("remo32_controller.agent_client.AgentClient.stats", reject, raising=True)
    response = client.get("/api/pcs/testpc/stats")
    assert response.status_code == 502
    assert response.json()["error"]["code"] == "agent_unauthorized"


class TestСтатикаИКэш:
    """Обновление интерфейса должно доезжать до уже открытого браузера.

    Однажды это не сработало: страница отдавалась без Cache-Control, браузер
    оставил у себя прежний app.js и продолжил выполнять его — со ссылками на
    элементы, которых в новой разметке уже нет. Экран оставался пустым, а в
    журнале сервера было чисто.
    """

    def test_страница_просит_сверяться_с_сервером(self, anon: TestClient) -> None:
        response = anon.get("/")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-cache"

    def test_статика_просит_сверяться_с_сервером(self, anon: TestClient) -> None:
        response = anon.get("/static/app.js")
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-cache"

    def test_адреса_статики_несут_метку_версии(self, anon: TestClient) -> None:
        html = anon.get("/").text
        assert "__ASSET_VERSION__" not in html, "подстановка версии не сработала"
        assert "/static/app.js?v=" in html
        assert "/static/style.css?v=" in html

    def test_скрытые_элементы_действительно_скрыты(self, anon: TestClient) -> None:
        """Атрибут hidden обязан побеждать наши собственные правила display.

        Браузер скрывает hidden правилом с нулевой специфичностью, и любое
        `#main { display: flex }` его перебивает. Так интерфейс однажды и
        сломался целиком: экран входа рисовался поверх пульта, а окно
        подтверждения — поверх всего, и закрыть его было нельзя.
        """
        import re

        from remo32_controller.app import WEB_DIR

        css = (WEB_DIR / "style.css").read_text(encoding="utf-8")
        assert re.search(r"\[hidden\][^{]*\{[^}]*display:\s*none\s*!important", css), (
            "в style.css нет правила [hidden] { display: none !important }"
        )

        # Ни один скрываемый элемент не должен полагаться на удачу.
        html = (WEB_DIR / "index.html").read_text(encoding="utf-8")
        скрываемые = set(re.findall(r'id="([^"]+)"[^>]*\shidden', html))
        assert {"main", "login", "sheet"} <= скрываемые, (
            f"разметка изменилась, тест смотрит не туда: {скрываемые}"
        )

    def test_метка_версии_меняется_вместе_с_файлом(self, anon: TestClient) -> None:
        import os
        import re

        from remo32_controller.app import WEB_DIR

        def версия() -> str:
            html = anon.get("/").text
            match = re.search(r"/static/app\.js\?v=(\d+)", html)
            assert match
            return match.group(1)

        было = версия()
        # Метка — время правки самого свежего файла интерфейса, а не app.js.
        # Поэтому сдвигаем время относительно уже полученной метки, иначе
        # правка более старого файла ничего не изменит и тест соврёт.
        target = WEB_DIR / "app.js"
        stat = target.stat()
        os.utime(target, (stat.st_atime, int(было) + 60))
        try:
            assert версия() != было
        finally:
            os.utime(target, (stat.st_atime, stat.st_mtime))

    def test_манифест_и_значок_отдаются(self, anon: TestClient) -> None:
        """Без них приложение не ставится на телефон как самостоятельное.

        Файлы легко потерять при переносе: они не упоминаются ни в одном
        импорте, только в разметке.
        """
        assert anon.get("/static/manifest.webmanifest").status_code == 200
        assert anon.get("/static/icon.svg").status_code == 200

    def test_манифест_ссылается_на_существующий_значок(self, anon: TestClient) -> None:
        import json

        manifest = json.loads(anon.get("/static/manifest.webmanifest").text)
        for icon in manifest["icons"]:
            assert anon.get(icon["src"]).status_code == 200, icon["src"]
