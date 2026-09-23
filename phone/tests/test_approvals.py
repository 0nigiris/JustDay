"""Подтверждение входа и sudo с телефона.

Проверяется главное свойство: без явного подтверждения ничего не
разрешается. Отказ должен быть исходом по умолчанию — при истёкшем сроке,
при повторном использовании, при выключенной возможности и при любой
неожиданности.
"""

from __future__ import annotations

import json
import subprocess
import sys
import time
from pathlib import Path

import pytest

from remo32_agent.approvals import ApprovalStore

PAM_SCRIPT = Path(__file__).resolve().parents[1] / "deploy" / "scripts" / "remo32-pam.py"


@pytest.fixture
def store(tmp_path: Path) -> ApprovalStore:
    return ApprovalStore(tmp_path / "approvals", enabled=True)


class TestХранилище:
    def test_пустое_место_это_пустой_список(self, store: ApprovalStore) -> None:
        assert store.list() == []

    def test_запрос_создаётся_ожидающим(self, store: ApprovalStore) -> None:
        approval = store.create("sudo", source="pts/1", command="/usr/bin/dnf update")
        assert approval.state == "pending"
        assert store.get(approval.id) is not None

    def test_каталог_и_файл_закрыты_от_чужих(self, store: ApprovalStore) -> None:
        """Одобрение — это пропуск к root. Права здесь не формальность."""
        approval = store.create("sudo")
        assert store.directory.stat().st_mode & 0o077 == 0
        assert (store.directory / f"{approval.id}.json").stat().st_mode & 0o077 == 0

    def test_просроченное_не_отдаётся_и_убирается(self, store: ApprovalStore) -> None:
        approval = store.create("sudo", ttl_seconds=1)
        time.sleep(1.1)
        assert store.get(approval.id) is None
        assert store.list() == []

    def test_решение_записывается(self, store: ApprovalStore) -> None:
        approval = store.create("sudo")
        assert store.decide(approval.id, True).state == "approved"
        assert store.decide(approval.id, False).state == "denied"

    def test_решение_по_несуществующему(self, store: ApprovalStore) -> None:
        with pytest.raises(KeyError):
            store.decide("нет-такого", True)

    def test_идентификатор_не_уводит_из_каталога(self, store: ApprovalStore) -> None:
        """Идентификатор приходит из адреса запроса — путь должен остаться
        внутри каталога, что бы в нём ни прислали."""
        with pytest.raises((KeyError, ValueError)):
            store.decide("../../../etc/passwd", True)


@pytest.mark.skipif(not PAM_SCRIPT.exists(), reason="нет скрипта PAM")
class TestСторонаPam:
    """Скрипт, который PAM запускает вместо проверки пароля.

    Код 0 означает «пустить без пароля», поэтому каждый тест здесь — про
    то, что ноль не возвращается зря.
    """

    def _run(self, *args: str, user: str = "tester") -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, str(PAM_SCRIPT), *args, "--user", user],
            capture_output=True,
            text=True,
            timeout=30,
        )

    def test_без_одобрения_отказ(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
        # Подставляем несуществующего пользователя: каталог найти негде.
        assert self._run("check", "--kind", "login").returncode != 0

    def test_неизвестный_пользователь_это_отказ(self) -> None:
        result = self._run("check", "--kind", "login", user="нет-такого-пользователя")
        assert result.returncode == 1
        assert "нет такого пользователя" in result.stderr

    def test_одобрение_срабатывает_один_раз(self, tmp_path: Path) -> None:
        """Одноразовость — половина защиты: иначе одно нажатие открывало бы
        дверь до конца срока, сколько бы раз её ни дёрнули."""
        import pwd

        me = pwd.getpwuid(__import__("os").getuid()).pw_name
        home = Path(pwd.getpwnam(me).pw_dir)
        directory = home / ".local/share/remo32/approvals"
        directory.mkdir(parents=True, exist_ok=True)

        marker = directory / "тест-одноразовости.json"
        marker.write_text(
            json.dumps(
                {
                    "id": "тест-одноразовости",
                    "kind": "other",
                    "state": "approved",
                    "user": me,
                    "expires_at": time.time() + 60,
                }
            ),
            encoding="utf-8",
        )
        try:
            assert self._run("check", "--kind", "other", user=me).returncode == 0
            assert self._run("check", "--kind", "other", user=me).returncode != 0
        finally:
            marker.unlink(missing_ok=True)

    def test_отказ_с_телефона_не_пускает(self, tmp_path: Path) -> None:
        import os
        import pwd
        import threading

        me = pwd.getpwuid(os.getuid()).pw_name
        directory = Path(pwd.getpwnam(me).pw_dir) / ".local/share/remo32/approvals"
        result: dict[str, int] = {}

        def run() -> None:
            done = self._run("request", "--kind", "other", "--wait", "10", user=me)
            result["code"] = done.returncode

        thread = threading.Thread(target=run)
        thread.start()
        time.sleep(1.5)

        store = ApprovalStore(directory, enabled=True)
        pending = [a for a in store.list() if a.kind == "other"]
        assert pending, "запрос не появился"
        store.decide(pending[0].id, False)

        thread.join(timeout=20)
        assert result["code"] != 0, "отказ с телефона обязан приводить к запросу пароля"
