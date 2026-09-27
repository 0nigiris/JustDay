"""Память переключателей: что было нажато в прошлый раз.

Кнопка-переключатель обязана помнить своё состояние между нажатиями, иначе
после перезапуска службы свет «включался» дважды подряд. Файл крошечный —
идентификатор кнопки и одно «да/нет», — и лежит рядом с самими кнопками.

Ничего, кроме состояния, здесь не хранится: что именно делает кнопка,
описано в её конфигурации и проверяется обычной валидацией.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

from remo32_core.log import get_logger

log = get_logger("agent.actions.toggles")

DEFAULT_PATH = Path("~/.config/remo32/toggles.json")


class ToggleState:
    """Состояние переключателей, переживающее перезапуск."""

    def __init__(self, path: Path | str = DEFAULT_PATH) -> None:
        self._path = Path(path).expanduser()

    def _read(self) -> dict[str, bool]:
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}
        return {str(k): bool(v) for k, v in raw.items()} if isinstance(raw, dict) else {}

    def is_on(self, action_id: str, default: bool = False) -> bool:
        return self._read().get(action_id, default)

    def set(self, action_id: str, on: bool) -> None:
        """Запись атомарная: оборванная на середине оставила бы пустой файл,
        и все переключатели разом забыли бы своё состояние."""
        state = self._read()
        state[action_id] = on
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=str(self._path.parent), prefix=".toggles-")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as fh:
                json.dump(state, fh, ensure_ascii=False, indent=2)
            os.replace(tmp, self._path)
            self._path.chmod(0o600)
        except OSError:
            log.warning("состояние переключателя не сохранилось", action=action_id)
            Path(tmp).unlink(missing_ok=True)

    def forget(self, action_id: str) -> None:
        state = self._read()
        if state.pop(action_id, None) is None:
            return
        self._path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
