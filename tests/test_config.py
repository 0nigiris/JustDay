"""Проверка конфигурации: она должна отказывать в небезопасных настройках."""

from __future__ import annotations

from pathlib import Path

import pytest

from remo32_agent.actions.models import ExecAction, ShellScriptAction, SystemdAction, TmuxAction
from remo32_agent.config import AgentSettings, SecuritySettings, load_settings
from remo32_core.errors import ConfigurationError


def test_agent_refuses_to_start_without_token(monkeypatch: pytest.MonkeyPatch) -> None:
    """Без токена агент не запускается — открытый агент опаснее выключенного."""
    monkeypatch.delenv("REMO32_AGENT_TOKEN", raising=False)
    with pytest.raises(ConfigurationError, match="токен"):
        load_settings()


def test_agent_rejects_short_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("REMO32_AGENT_TOKEN", "коротко")
    with pytest.raises(ConfigurationError, match="слишком короткий"):
        load_settings()


def test_insecure_mode_must_be_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    """Работа без токена возможна, но только если её включили осознанно."""
    monkeypatch.delenv("REMO32_AGENT_TOKEN", raising=False)
    settings = AgentSettings(security=SecuritySettings(allow_insecure_no_token=True))
    assert settings.security.resolve_token() is None


def test_token_file_must_not_be_world_readable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("REMO32_AGENT_TOKEN", raising=False)
    token_file = tmp_path / "agent.token"
    token_file.write_text("a" * 32)
    token_file.chmod(0o644)

    security = SecuritySettings(token_file=token_file)
    with pytest.raises(ConfigurationError, match="доступен посторонним"):
        security.resolve_token()

    token_file.chmod(0o600)
    assert security.resolve_token() == "a" * 32


def test_duplicate_action_ids_rejected() -> None:
    with pytest.raises(ValueError, match="дублирующийся"):
        AgentSettings(
            actions=[
                ExecAction(id="same", name="Первое", argv=["true"]),
                ExecAction(id="same", name="Второе", argv=["true"]),
            ]
        )


def test_shell_script_requires_absolute_path() -> None:
    with pytest.raises(ValueError, match="абсолютным"):
        ShellScriptAction(id="s", name="Скрипт", script="relative/path.sh")


def test_systemd_verb_is_whitelisted() -> None:
    """systemctl не должен получать произвольный глагол вроде mask."""
    with pytest.raises(ValueError):
        SystemdAction(id="bad", name="Плохое", kind="systemd_user", unit="x.service", verb="mask")


def test_systemd_unit_name_is_validated() -> None:
    with pytest.raises(ValueError):
        SystemdAction(
            id="bad",
            name="Плохое",
            kind="systemd_user",
            unit="x.service; rm -rf /",
            verb="start",
        )


def test_tmux_command_is_quoted_by_us_not_by_user() -> None:
    """Аргументы экранируем мы, поэтому склеить инъекцию через конфиг нельзя."""
    action = TmuxAction(
        id="t",
        name="Тест",
        session="s",
        argv=["echo", "привет; rm -rf /"],
    )
    command = action.command_string()
    assert "rm -rf /" in command
    # Опасная часть целиком внутри кавычек, а не отдельной командой.
    assert command.startswith("echo '")
    assert command.count("'") >= 2


def test_action_id_pattern_rejects_path_traversal() -> None:
    with pytest.raises(ValueError):
        ExecAction(id="../../etc/passwd", name="Плохое", argv=["true"])


def test_controller_requires_password_hash(monkeypatch: pytest.MonkeyPatch) -> None:
    from remo32_controller.config import load_settings as load_controller

    monkeypatch.delenv("REMO32_PASSWORD_HASH", raising=False)
    with pytest.raises(ConfigurationError, match="хэш пароля"):
        load_controller()


def test_controller_pc_url_must_be_http(
    password_hash: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    from remo32_controller.config import ControllerSettings, PcConfig

    monkeypatch.setenv("REMO32_PASSWORD_HASH", password_hash)
    with pytest.raises(ValueError, match="http"):
        ControllerSettings(pcs=[PcConfig(id="x", name="X", agent_url="ftp://host")])


def test_esp32_http_transport_requires_url() -> None:
    from remo32_controller.config import Esp32Settings

    with pytest.raises(ValueError, match="base_url"):
        Esp32Settings(transport="http")


def test_esp32_mqtt_transport_requires_host() -> None:
    from remo32_controller.config import Esp32Settings

    with pytest.raises(ValueError, match="mqtt_host"):
        Esp32Settings(transport="mqtt")


def test_secrets_never_appear_in_example_configs() -> None:
    """В примерах конфигурации не должно быть заполненных секретов.

    Проверяем не текст, а разобранные значения: имена вроде
    ``allow_insecure_no_token`` содержат слово «token», но секретом не являются.
    """
    import tomllib

    secret_keys = {"token", "password", "wifi_password", "mqtt_password", "secret", "api_key"}
    root = Path(__file__).resolve().parent.parent

    def walk(node: object, path: str = "") -> list[str]:
        found: list[str] = []
        if isinstance(node, dict):
            for key, value in node.items():
                where = f"{path}.{key}" if path else key
                if key in secret_keys and isinstance(value, str) and value.strip():
                    found.append(where)
                found.extend(walk(value, where))
        elif isinstance(node, list):
            for index, item in enumerate(node):
                found.extend(walk(item, f"{path}[{index}]"))
        return found

    for name in ("agent.example.toml", "controller.example.toml"):
        data = tomllib.loads((root / "config" / name).read_text(encoding="utf-8"))
        leaked = walk(data)
        assert not leaked, f"в {name} заполнены секреты: {leaked}"
        # Заодно убеждаемся, что туда не попал хэш пароля.
        assert "$argon2" not in (root / "config" / name).read_text(encoding="utf-8")
