"""Файлы на телефоне: что видно, что отдаётся и куда выйти нельзя.

Главная проверка здесь — не «список показался», а «за разрешённую папку не
выйти ни адресом, ни ссылкой». Остальное — удобство, а это граница доступа.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from remo32_agent import files
from remo32_core.errors import ActionInvalidError, NotFoundError


@pytest.fixture
def browser(sandbox: Path) -> files.Browser:
    return files.Browser([files.Root("box", "Песочница", sandbox.resolve())])


# --------------------------------------------------------------------- список


def test_top_shows_folders_without_real_paths(browser: files.Browser, sandbox: Path) -> None:
    top = browser.top()
    assert [r.id for r in top.roots] == ["box"]
    assert [e.name for e in top.entries] == ["Песочница"]
    assert str(sandbox) not in top.model_dump_json()  # настоящего пути телефон не видит


def test_listing_puts_folders_first_and_hides_dotfiles(browser: files.Browser) -> None:
    got = browser.listing("box")
    assert [e.name for e in got.entries] == ["вложенная", "заметка.txt"]
    assert got.entries[0].dir and not got.entries[1].dir
    assert got.parent == ""  # «назад» ведёт к списку папок


def test_hidden_files_appear_only_when_asked(sandbox: Path) -> None:
    open_box = files.Browser(
        [files.Root("box", "Песочница", sandbox.resolve())], show_hidden=True
    )
    assert ".скрытое" in [e.name for e in open_box.listing("box").entries]


def test_kind_and_address_let_the_phone_open_a_nested_file(browser: files.Browser) -> None:
    inner = browser.listing("box/вложенная")
    assert inner.path == "box/вложенная" and inner.parent == "box"
    (shot,) = inner.entries
    assert (shot.path, shot.kind) == ("box/вложенная/снимок.png", "image")


def test_a_folder_bigger_than_the_limit_is_cut_and_says_so(sandbox: Path) -> None:
    small = files.Browser([files.Root("box", "Песочница", sandbox.resolve())], max_entries=16)
    for i in range(40):
        (sandbox / f"файл-{i}.txt").write_text("x", encoding="utf-8")
    got = small.listing("box")
    assert got.truncated and len(got.entries) == 16


# --------------------------------------------------------------------- граница


@pytest.mark.parametrize(
    "address",
    ["box/../секрет", "box/..", "box/вложенная/../../секрет", "box/./../секрет"],
)
def test_no_address_walks_out_of_the_folder(browser: files.Browser, address: str) -> None:
    with pytest.raises(ActionInvalidError):
        browser.resolve(address)


@pytest.mark.parametrize("address", ["", "/", "secret", "/etc/passwd", "../etc"])
def test_unopened_folders_do_not_exist_for_the_phone(browser: files.Browser, address: str) -> None:
    with pytest.raises((NotFoundError, ActionInvalidError)):
        browser.resolve(address)


def test_a_symlink_out_is_refused_and_not_even_listed(browser: files.Browser) -> None:
    with pytest.raises(NotFoundError):
        browser.listing("box/наружу")
    assert "наружу" not in [e.name for e in browser.listing("box").entries]


def test_a_file_bigger_than_the_limit_is_not_handed_over(sandbox: Path) -> None:
    tiny = files.Browser([files.Root("box", "Песочница", sandbox.resolve())], max_bytes=4)
    with pytest.raises(ActionInvalidError, match="больше предела"):
        tiny.file("box/заметка.txt")


def test_a_folder_is_not_a_file_and_the_other_way_round(browser: files.Browser) -> None:
    with pytest.raises(ActionInvalidError, match="папка"):
        browser.file("box/вложенная")
    with pytest.raises(ActionInvalidError, match="файл"):
        browser.listing("box/заметка.txt")


def test_the_file_comes_back_with_its_real_type(browser: files.Browser) -> None:
    real, kind = browser.file("box/заметка.txt")
    assert real.read_text(encoding="utf-8") == "привет"
    assert kind.startswith("text/plain")


# ------------------------------------------------------------------------ ручки


def test_api_lists_and_reads(agent_client) -> None:  # type: ignore[no-untyped-def]
    top = agent_client.get("/api/files").json()["data"]
    assert [e["name"] for e in top["entries"]] == ["Песочница"]

    inside = agent_client.get("/api/files", params={"path": "box"}).json()["data"]
    assert [e["name"] for e in inside["entries"]] == ["вложенная", "заметка.txt"]

    got = agent_client.get("/api/files/read", params={"path": "box/заметка.txt"})
    assert got.status_code == 200
    assert got.text == "привет"
    # Имя файла нужно телефону, чтобы сохранить его под тем же именем; русское
    # имя уходит в заголовок закодированным, как это и предписано.
    from urllib.parse import unquote

    assert "заметка.txt" in unquote(got.headers["content-disposition"])
    # Текст и картинку телефон показывает сам — значит не «скачать», а «открыть».
    assert got.headers["content-disposition"].startswith("inline")


def test_api_refuses_a_way_out(agent_client) -> None:  # type: ignore[no-untyped-def]
    assert agent_client.get("/api/files", params={"path": "box/../секрет"}).status_code == 400
    assert agent_client.get("/api/files", params={"path": "нет"}).status_code == 404
    assert agent_client.get("/api/files/read", params={"path": "box/наружу"}).status_code == 404


def test_files_can_be_switched_off_entirely(agent_settings, runner) -> None:  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient

    from remo32_agent.app import create_app
    from tests.conftest import TEST_TOKEN

    agent_settings.files.enabled = False
    app = create_app(agent_settings, runner=runner, configure_logs=False)
    with TestClient(app) as client:
        client.headers.update({"X-Remo32-Agent-Token": TEST_TOKEN})
        got = client.get("/api/files")
        assert got.status_code == 403
        assert got.json()["error"]["code"] == "files_disabled"


def test_a_file_leaving_the_machine_is_announced(agent_client, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Уведомление на компьютере — не украшение, а способ заметить чужой доступ."""
    said: list[str] = []

    async def fake_show(body: str, **kw: object) -> bool:
        said.append(body)
        return True

    monkeypatch.setattr("remo32_agent.notify.show", fake_show)
    agent_client.get("/api/files/read", params={"path": "box/заметка.txt"})
    assert said == ["Файл ушёл на телефон: заметка.txt"]


# ------------------------------------------------------------------- контроллер
#
# Контроллер для файлов — труба. Проверяем именно это: что он не читает файл в
# память, передаёт запрос части и не подменяет заголовки, по которым телефон
# решает, как файл показать и под каким именем сохранить.


@pytest.fixture
def controller_app(controller_settings):  # type: ignore[no-untyped-def]
    from remo32_controller.app import create_app

    return create_app(controller_settings, configure_logs=False)


@pytest.fixture
def phone(controller_app):  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient

    from tests.conftest import TEST_PASSWORD

    with TestClient(controller_app) as client:
        assert client.post("/api/auth/login", json={"password": TEST_PASSWORD}).status_code == 200
        yield client


def test_controller_asks_the_agent_and_keeps_the_envelope(phone, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    async def fake_files(self, path: str = "") -> dict[str, object]:  # type: ignore[no-untyped-def]
        assert path == "box/вложенная"
        return {
            "path": path,
            "name": "вложенная",
            "parent": "box",
            "entries": [{"path": f"{path}/снимок.png", "name": "снимок.png", "kind": "image"}],
        }

    monkeypatch.setattr("remo32_controller.agent_client.AgentClient.files", fake_files)
    got = phone.get("/api/pcs/testpc/files", params={"path": "box/вложенная"})
    assert got.status_code == 200
    body = got.json()
    assert body["ok"] and body["data"]["entries"][0]["name"] == "снимок.png"


def test_controller_streams_the_file_and_passes_the_range(phone, monkeypatch) -> None:  # type: ignore[no-untyped-def]
    import httpx

    seen: dict[str, object] = {}

    async def fake_stream(self, where, *, params=None, headers=None, timeout=120.0):  # type: ignore[no-untyped-def]
        seen.update(where=where, params=params, headers=headers)

        async def chunks():
            yield b"\xff\xd8"
            yield b"\xff\xd9"

        return httpx.Response(
            206,
            content=chunks(),
            headers={
                "Content-Type": "image/jpeg",
                "Content-Range": "bytes 0-3/4",
                # Русское имя в заголовке живёт закодированным — так его и
                # ставит FastAPI на стороне агента.
                "Content-Disposition": (
                    "inline; filename*=utf-8''%D1%81%D0%BD%D0%B8%D0%BC%D0%BE%D0%BA.jpg"
                ),
                "X-Agent-Internal": "not for the phone",
            },
        )

    monkeypatch.setattr("remo32_controller.agent_client.AgentClient.open_stream", fake_stream)
    got = phone.get(
        "/api/pcs/testpc/files/read",
        params={"path": "box/снимок.jpg"},
        headers={"Range": "bytes=0-3"},
    )
    assert got.status_code == 206
    assert got.content == b"\xff\xd8\xff\xd9"
    # Запрос части дошёл до агента — иначе видео на телефоне не мотается.
    assert seen["headers"] == {"Range": "bytes=0-3"}
    assert seen["params"] == {"path": "box/снимок.jpg"}
    assert got.headers["content-range"] == "bytes 0-3/4"
    from urllib.parse import unquote

    assert "снимок.jpg" in unquote(got.headers["content-disposition"])
    # Лишние заголовки агента до телефона не доходят.
    assert "x-agent-internal" not in {k.lower() for k in got.headers}


def test_the_file_routes_need_a_session(controller_app) -> None:  # type: ignore[no-untyped-def]
    from fastapi.testclient import TestClient

    with TestClient(controller_app) as anon:
        for url in ("/api/pcs/testpc/files", "/api/pcs/testpc/files/read?path=box/з.txt"):
            assert anon.get(url).status_code == 401
