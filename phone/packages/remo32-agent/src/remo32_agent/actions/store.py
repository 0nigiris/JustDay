"""Кнопки, заведённые через интерфейс.

Действия приходят из двух мест, и это разделение намеренное.

``agent.toml`` пишет хозяин машины руками. Там его комментарии, его порядок,
его отступы — файл принадлежит человеку, и переписывать его программой нельзя:
однажды сохранённая кнопка стёрла бы всё, что он объяснял себе на будущее.
Такие действия отдаются интерфейсу только на чтение.

``actions.toml`` принадлежит программе. Его формат — плоский список, его
пишет и перечитывает только этот модуль. Потерять там нечего, кроме самих
кнопок, и именно он стоит за кнопкой «Добавить» в интерфейсе.

Файл перечитывается по времени правки, а не кэшируется навсегда: кнопку можно
завести с телефона, а можно дописать в файл руками — оба пути должны работать
без перезапуска службы.
"""

from __future__ import annotations

import os
import tempfile
import tomllib
from pathlib import Path
from typing import Any

from pydantic import TypeAdapter, ValidationError

from remo32_agent.actions.models import ActionConfig
from remo32_core.errors import ConfigurationError

_ADAPTER: TypeAdapter[list[ActionConfig]] = TypeAdapter(list[ActionConfig])

DEFAULT_STORE_PATH = Path("~/.config/remo32/actions.toml")

_HEADER = """# Кнопки Remo32, заведённые через интерфейс.
#
# Этот файл пишет программа. Править руками можно — изменения подхватятся
# без перезапуска, — но комментарии и порядок строк при следующем сохранении
# из интерфейса будут потеряны.
#
# Кнопки, которые нужно сохранить навсегда, держите в agent.toml:
# оттуда их никто не перепишет, но и менять их с телефона нельзя.
"""


class ActionStore:
    """Список действий в отдельном файле, которым владеет программа."""

    def __init__(self, path: Path | str = DEFAULT_STORE_PATH) -> None:
        self._path = Path(path).expanduser()
        self._cache: list[ActionConfig] = []
        self._mtime: float | None = None
        self._loaded = False

    @property
    def path(self) -> Path:
        return self._path

    # --- чтение ---------------------------------------------------------

    def load(self) -> list[ActionConfig]:
        """Действия из файла, перечитанные если файл изменился.

        Отсутствующий файл — не ошибка: это просто «кнопок ещё нет».
        """
        try:
            mtime = self._path.stat().st_mtime
        except FileNotFoundError:
            self._cache = []
            self._mtime = None
            self._loaded = True
            return []

        if self._loaded and self._mtime == mtime:
            return self._cache

        self._cache = self._parse(self._path.read_bytes())
        self._mtime = mtime
        self._loaded = True
        return self._cache

    @staticmethod
    def _parse(raw: bytes) -> list[ActionConfig]:
        try:
            data: dict[str, Any] = tomllib.loads(raw.decode("utf-8"))
        except (tomllib.TOMLDecodeError, UnicodeDecodeError) as exc:
            raise ConfigurationError(f"actions.toml не читается: {exc}") from exc

        raw_actions = data.get("actions", [])
        if not isinstance(raw_actions, list):
            raise ConfigurationError("в actions.toml ключ actions должен быть списком")

        try:
            return _ADAPTER.validate_python(raw_actions)
        except ValidationError as exc:
            raise ConfigurationError(f"кнопка в actions.toml описана неверно: {exc}") from exc

    # --- запись ---------------------------------------------------------

    def save(self, actions: list[ActionConfig]) -> None:
        """Переписывает файл целиком.

        Запись атомарная: сначала во временный файл рядом, потом ``rename``.
        Иначе обрыв питания посреди сохранения оставил бы обрезанный файл, и
        агент при следующем старте не поднялся бы вовсе — из-за кнопки.
        """
        seen: set[str] = set()
        for action in actions:
            if action.id in seen:
                raise ConfigurationError(f"дублирующийся идентификатор кнопки: {action.id}")
            seen.add(action.id)

        self._path.parent.mkdir(parents=True, exist_ok=True)
        body = _HEADER + "\n" + "\n".join(_dump(a) for a in actions)

        handle, tmp_name = tempfile.mkstemp(
            dir=self._path.parent, prefix=".actions-", suffix=".toml"
        )
        tmp = Path(tmp_name)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as fh:
                fh.write(body)
                fh.flush()
                os.fsync(fh.fileno())
            tmp.chmod(0o600)
            tmp.replace(self._path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise

        self._cache = list(actions)
        self._mtime = self._path.stat().st_mtime
        self._loaded = True


def _dump(action: ActionConfig) -> str:
    """Одна секция ``[[actions]]``.

    Свой сериализатор вместо библиотеки: писать нужно ровно один формат,
    зато без лишней зависимости и с предсказуемым порядком полей — файл,
    сохранённый дважды подряд, обязан совпасть побайтово.
    """
    data = action.model_dump(mode="json", exclude_none=True, exclude_defaults=True)
    data["id"] = action.id
    data["name"] = action.name
    data["kind"] = str(action.kind)

    order = ["id", "name", "kind", "description", "icon", "group"]
    keys = order + sorted(k for k in data if k not in order)

    lines = ["[[actions]]"]
    for key in keys:
        if key not in data:
            continue
        lines.append(f"{key} = {_toml_value(data[key])}")
    return "\n".join(lines) + "\n"


def _toml_value(value: Any) -> str:
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, list):
        return "[" + ", ".join(_toml_value(v) for v in value) + "]"
    if isinstance(value, dict):
        inner = ", ".join(f"{_toml_key(k)} = {_toml_value(v)}" for k, v in value.items())
        return "{" + inner + "}"
    return _toml_string(str(value))


def _toml_key(key: str) -> str:
    if key and all(c.isalnum() or c in "_-" for c in key):
        return key
    return _toml_string(key)


def _toml_string(value: str) -> str:
    escaped = (
        value.replace("\\", "\\\\")
        .replace('"', '\\"')
        .replace("\n", "\\n")
        .replace("\r", "\\r")
        .replace("\t", "\\t")
    )
    return f'"{escaped}"'
