"""Настройки мозга, которые прямо влияют на счёт.

Проверяем не «что передали в SDK», а то, из-за чего был перерасход: схемы
инструментов, загружаемые целиком, и разговор, растущий без потолка.
"""

from __future__ import annotations

from justday import brain


class TestСхемыИнструментов:
    def test_по_умолчанию_по_требованию(self) -> None:
        assert brain._tool_search_env("on") == {"ENABLE_TOOL_SEARCH": "1"}

    def test_auto_оставляет_решение_claude_code(self) -> None:
        assert brain._tool_search_env("auto") == {"ENABLE_TOOL_SEARCH": "auto"}

    def test_off_ничего_не_ставит(self) -> None:
        """Переменной быть не должно вовсе: пустая строка означала бы другое."""
        assert brain._tool_search_env("off") == {}


class TestПотолокРазговора:
    def test_ноль_значит_не_вмешиваться(self) -> None:
        assert brain._window_env(0) == {}

    def test_значение_уходит_как_есть(self) -> None:
        assert brain._window_env(200_000) == {"CLAUDE_CODE_AUTO_COMPACT_WINDOW": "200000"}


class TestМолчание:
    """«Ответ не нужен» модель пишет словами — читать это вслух не надо."""

    def test_заглушки_узнаются(self) -> None:
        for текст in ("ok", "Готово.", "нечего добавить", "No response needed",
                      "молча", "ответ не нужен"):
            assert brain.SILENCE.match(текст), текст

    def test_настоящий_ответ_не_глушится(self) -> None:
        for текст in ("Готово, музыка играет.", "ок, но есть нюанс", "Сделал 40%."):
            assert not brain.SILENCE.match(текст), текст


class TestЧеловечныеПодписи:
    def test_команда_показывается_целиком_если_короткая(self) -> None:
        assert brain.humanize_tool("Bash", {"command": "ls -la"}) == "ls -la"

    def test_длинный_скрипт_называется_по_смыслу(self) -> None:
        команда = "python3 -c 'import sys\\n" + "print(1)\\n" * 20 + "'"
        assert brain.humanize_tool("Bash", {"command": команда}) == "Считаю в Python"

    def test_описание_важнее_команды(self) -> None:
        got = brain.humanize_tool("Bash", {"command": "rm -rf /tmp/x", "description": "Убираю мусор"})
        assert got == "Убираю мусор"

    def test_одобрение_видит_команду_как_есть(self) -> None:
        """В запросе разрешения нельзя подменять команду красивым названием."""
        команда = "sudo dnf remove firefox"
        assert команда in brain.describe_tool("Bash", {"command": команда})

    def test_длинная_строка_обрезается_одной_строкой(self) -> None:
        got = brain.one_line("а\nб\nв" + "г" * 200)
        assert "\n" not in got and got.endswith("…") and len(got) <= 90
