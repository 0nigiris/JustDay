"""Раздача APK и обновление приложения на телефоне."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def apk(tmp_path: Path) -> Path:
    """Поддельный APK. Содержимое неважно — важны размер и сумма."""
    path = tmp_path / "remo32.apk"
    path.write_bytes(b"PK\x03\x04" + b"a" * 500)
    (tmp_path / "remo32.json").write_text(
        json.dumps(
            {
                "version_code": 1480170,
                "version_name": "2026.09.07-abc1234",
                "size_bytes": path.stat().st_size,
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
                "built_at": "2026-09-07T19:43:50Z",
            }
        ),
        encoding="utf-8",
    )
    return path


@pytest.fixture
def app_client(controller_settings, apk: Path):  # type: ignore[no-untyped-def]
    from remo32_controller.app import create_app

    controller_settings.android_app.apk_path = apk
    with TestClient(create_app(controller_settings, configure_logs=False)) as client:
        yield client


def _login(client: TestClient) -> None:
    from tests.conftest import TEST_PASSWORD

    response = client.post("/api/auth/login", json={"password": TEST_PASSWORD})
    assert response.status_code == 200, response.text


class TestРаздача:
    def test_без_входа_не_отдаётся(self, app_client: TestClient) -> None:
        """APK не секрет, но открытая раздача файла, который человек
        установит на телефон не глядя, — плохая мысль."""
        assert app_client.get("/api/app/latest").status_code == 401
        assert app_client.get("/api/app/download").status_code == 401

    def test_версия_читается_из_метаданных(self, app_client: TestClient) -> None:
        _login(app_client)
        data = app_client.get("/api/app/latest").json()["data"]
        assert data["version_code"] == 1480170
        assert data["version_name"] == "2026.09.07-abc1234"
        assert data["download_url"] == "/api/app/download"

    def test_файл_отдаётся_целиком(self, app_client: TestClient, apk: Path) -> None:
        _login(app_client)
        response = app_client.get("/api/app/download")
        assert response.status_code == 200
        assert response.content == apk.read_bytes()
        assert response.headers["content-type"] == "application/vnd.android.package-archive"
        # Имя с версией: иначе в «Загрузках» лежит десяток одинаковых remo32.apk.
        assert "2026.09.07-abc1234" in response.headers["content-disposition"]

    def test_сумма_совпадает_с_файлом(self, app_client: TestClient) -> None:
        """Телефон сверяет её после загрузки: оборванная закачка иначе
        доходит до установщика и получает невнятное «пакет повреждён»."""
        _login(app_client)
        data = app_client.get("/api/app/latest").json()["data"]
        body = app_client.get("/api/app/download").content
        assert hashlib.sha256(body).hexdigest() == data["sha256"]
        assert data["size_bytes"] == len(body)

    def test_без_метаданных_сумма_считается_на_месте(
        self, app_client: TestClient, apk: Path
    ) -> None:
        apk.with_suffix(".json").unlink()
        _login(app_client)
        data = app_client.get("/api/app/latest").json()["data"]
        assert data["sha256"] == hashlib.sha256(apk.read_bytes()).hexdigest()
        # Версия неизвестна — значит телефон ничего не предложит, а не
        # предложит установить «что-то».
        assert data["version_code"] == 0

    def test_несобранное_приложение_это_не_ошибка_сервера(
        self, app_client: TestClient, apk: Path
    ) -> None:
        apk.unlink()
        _login(app_client)
        response = app_client.get("/api/app/latest")
        assert response.status_code == 404
        assert "build.sh" in response.json()["error"]["message"]

    def test_выключенная_раздача(self, controller_settings, apk: Path) -> None:  # type: ignore[no-untyped-def]
        from remo32_controller.app import create_app

        controller_settings.android_app.apk_path = apk
        controller_settings.android_app.enabled = False
        with TestClient(create_app(controller_settings, configure_logs=False)) as client:
            _login(client)
            assert client.get("/api/app/latest").status_code == 404


class TestВерсияСборки:
    def test_версия_не_константа_и_растёт(self) -> None:
        """versionCode обязан расти сам.

        Раньше в сборщике стояло ``${VERSION_CODE:-1}``: каждая сборка
        выходила версией 1, Android считал её той же самой, и обновление
        превращалось в «удалить приложение и поставить заново».

        Проверяем сам сборщик текстом, а не запуском: Android SDK на машине
        с тестами может и не быть, а ошибка здесь ровно текстовая.
        """
        import re
        import time

        script = Path("android/build.sh").read_text(encoding="utf-8")
        match = re.search(r'VERSION_CODE="\$\{VERSION_CODE:-(.+?)\}"', script)
        assert match, "в build.sh больше нет вычисляемого VERSION_CODE"

        formula = match.group(1)
        assert formula != "1", "версия снова стала константой — обновления сломаются"
        assert "date" in formula, "версия должна зависеть от времени сборки"

        # То же вычисление, что и в скрипте: минуты от условного начала.
        now = int(time.time())
        code = (now - 1700000000) // 60
        assert 0 < code < 2_100_000_000, "не помещается в int32 — предел Android"
        assert (now + 60 - 1700000000) // 60 == code + 1, "не растёт со временем"
