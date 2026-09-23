"""Надиктовка с телефона: звук доезжает до ассистента и нигде не остаётся.

Путь у записи длинный — браузер, контроллер, агент, сокет JustDay, — и на
каждом участке её легко потерять или, наоборот, сохранить там, где не надо.
Здесь проверяется и то, и другое.
"""

from __future__ import annotations

import os
from typing import Any

import pytest
from conftest import TEST_PASSWORD
from fastapi.testclient import TestClient

from remo32_controller.config import ControllerSettings

AUDIO = b"\x1a\x45\xdf\xa3" + b"opus" * 400  # похоже на webm и заведомо длиннее порога


# Заглядываем на диск из обычных функций, а не из корутин: правило о
# блокирующем вводе-выводе внутри async справедливо, но проверить временный
# файл нужно именно синхронно — ровно в тот момент, когда он ещё существует.
def снимок(path: str) -> tuple[bytes, int]:
    with open(path, "rb") as fh:
        return fh.read(), os.stat(path).st_mode


def есть_на_диске(path: str) -> bool:
    return os.path.exists(path)


class TestАгент:
    """Ручка на самом компьютере: она единственная имеет дело с файлом."""

    def test_запись_уходит_ассистенту(self, agent_client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
        видел: dict[str, Any] = {}

        async def fake(audio: bytes, suffix: str = ".webm") -> dict[str, Any]:
            видел["bytes"] = audio
            видел["suffix"] = suffix
            return {"ok": True, "text": "поставь таймер", "result": "готово"}

        monkeypatch.setattr("remo32_agent.justday.dictate", fake)
        response = agent_client.post("/api/justday/dictate?suffix=.m4a", content=AUDIO)
        assert response.status_code == 200
        assert response.json()["data"]["text"] == "поставь таймер"
        assert видел["bytes"] == AUDIO
        assert видел["suffix"] == ".m4a"

    def test_пустая_запись_это_ошибка_человека(self, agent_client) -> None:  # type: ignore[no-untyped-def]
        """Нажали и сразу отпустили. Это 400, а не 500: ломаться тут нечему."""
        response = agent_client.post("/api/justday/dictate", content=b"")
        assert response.status_code == 400
        assert response.json()["ok"] is False

    def test_слишком_длинная_запись_не_принимается(self, agent_client) -> None:  # type: ignore[no-untyped-def]
        """Предел стоит раньше распознавания: минута речи весит меньше мегабайта."""
        response = agent_client.post("/api/justday/dictate", content=b"0" * (9 * 1024 * 1024))
        assert response.status_code == 400

    @pytest.mark.parametrize("suffix", ["../../etc/passwd", ".sh; rm", "", ".TOOLONGX"])
    def test_расширение_не_пускают_в_имя_файла(self, agent_client, suffix: str) -> None:  # type: ignore[no-untyped-def]
        """Расширение попадает в имя временного файла, поэтому оно проверяется.

        Без проверки сюда пролезал бы любой путь — а файл создаёт сервис,
        работающий от имени владельца компьютера.
        """
        response = agent_client.post(
            "/api/justday/dictate", params={"suffix": suffix}, content=AUDIO
        )
        assert response.status_code == 422

    @pytest.mark.asyncio
    async def test_файл_живёт_только_до_ответа(self, monkeypatch) -> None:
        """Голос не должен оставаться на диске ни на секунду дольше нужного."""
        from remo32_agent import justday

        путь: dict[str, str] = {}

        async def fake_call(command: str, timeout: float = 0, **payload: Any) -> dict[str, Any]:
            путь["path"] = payload["path"]
            # Пока ассистент разбирает запись, файл обязан существовать и
            # читаться только владельцем.
            содержимое, права = снимок(payload["path"])
            assert содержимое == AUDIO
            assert права & 0o077 == 0
            return {"ok": True, "text": "проверка"}

        monkeypatch.setattr(justday, "call", fake_call)
        got = await justday.dictate(AUDIO, ".webm")
        assert got["text"] == "проверка"
        assert not есть_на_диске(путь["path"])

    @pytest.mark.asyncio
    async def test_файл_убирается_и_после_сбоя(self, monkeypatch) -> None:
        from remo32_agent import justday

        путь: dict[str, str] = {}

        async def fake_call(command: str, timeout: float = 0, **payload: Any) -> dict[str, Any]:
            путь["path"] = payload["path"]
            raise TimeoutError("ассистент не ответил")

        monkeypatch.setattr(justday, "call", fake_call)
        with pytest.raises(TimeoutError):
            await justday.dictate(AUDIO)
        assert not есть_на_диске(путь["path"])


class TestКонтроллер:
    """Телефон разговаривает только с контроллером — и только после входа."""

    @pytest.fixture
    def anon(self, controller_settings: ControllerSettings):  # type: ignore[no-untyped-def]
        from remo32_controller.app import create_app

        with TestClient(create_app(controller_settings, configure_logs=False)) as client:
            yield client

    @pytest.fixture
    def client(self, anon: TestClient) -> TestClient:
        assert anon.post("/api/auth/login", json={"password": TEST_PASSWORD}).status_code == 200
        return anon

    def test_без_входа_микрофон_не_работает(self, anon: TestClient) -> None:
        response = anon.post("/api/pcs/testpc/justday/dictate", content=AUDIO)
        assert response.status_code == 401

    def test_запись_доезжает_до_агента(
        self, client: TestClient, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        видел: dict[str, Any] = {}

        async def fake(self: object, audio: bytes, suffix: str = ".webm") -> dict[str, Any]:
            видел["bytes"] = audio
            видел["suffix"] = suffix
            return {"ok": True, "text": "включи музыку", "result": "включаю"}

        monkeypatch.setattr(
            "remo32_controller.agent_client.AgentClient.justday_dictate", fake, raising=True
        )
        response = client.post("/api/pcs/testpc/justday/dictate?suffix=.webm", content=AUDIO)
        assert response.status_code == 200
        assert response.json()["data"]["result"] == "включаю"
        assert видел["bytes"] == AUDIO

    def test_пустую_запись_контроллер_не_пересылает(self, client: TestClient) -> None:
        response = client.post("/api/pcs/testpc/justday/dictate", content=b"")
        assert response.status_code == 400
