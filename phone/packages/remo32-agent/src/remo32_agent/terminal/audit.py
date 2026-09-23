"""Журнал аудита удалённого терминала.

Пишется всегда, когда терминал включён. Файл открывается в режиме
дозаписи с правами 0600 и никогда не отдаётся через API — читать его
можно только с самой машины.
"""

from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from remo32_core.log import get_logger

log = get_logger("agent.terminal.audit")


class TerminalAudit:
    def __init__(self, path: Path | None, *, max_bytes: int = 2_000_000, keep: int = 3) -> None:
        self._path = path.expanduser() if path else None
        self._ready = False
        self._max_bytes = max_bytes
        self._keep = keep

    def _ensure(self) -> bool:
        if self._path is None:
            return False
        if self._ready:
            return True
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            # Создаём сразу с 0600, чтобы между созданием и chmod не было окна.
            fd = os.open(self._path, os.O_CREAT | os.O_APPEND | os.O_WRONLY, 0o600)
            os.close(fd)
            os.chmod(self._path, 0o600)
        except OSError as exc:
            log.error("не удалось открыть журнал аудита", path=str(self._path), error=str(exc))
            self._path = None
            return False
        self._ready = True
        return True

    def _rotate_if_needed(self) -> None:
        """Откладывает разросшийся журнал в .1 и начинает новый.

        Подрезаем по размеру, а не по времени: важно не «за какой период»
        сохранилась история, а то, что она не съест диск. Самое старое
        поколение удаляется — иначе задача просто откладывается.

        Сбой ротации не должен мешать записи: журнал, который перестал
        писаться из-за собственной уборки, хуже слишком большого.
        """
        if self._path is None or self._max_bytes <= 0:
            return

        # Имена поколений строим приписыванием к полному имени, а не через
        # with_suffix: тот заменяет расширение, и «terminal-audit.log.1»
        # превратился бы в «terminal-audit.log.1.2».
        def generation(number: int) -> Path:
            return self._path.with_name(f"{self._path.name}.{number}")  # type: ignore[union-attr]

        try:
            if not self._path.exists() or self._path.stat().st_size < self._max_bytes:
                return
            generation(self._keep).unlink(missing_ok=True)
            for number in range(self._keep - 1, 0, -1):
                older = generation(number)
                if older.exists():
                    older.rename(generation(number + 1))
            self._path.rename(generation(1))
            self._ready = False  # новый файл создастся снова с правами 0600
            log.info("журнал аудита подрезан", keep=self._keep)
        except OSError as exc:
            log.warning("не удалось подрезать журнал аудита", error=str(exc))

    def record(self, event: str, **fields: Any) -> None:
        self._rotate_if_needed()
        if not self._ensure() or self._path is None:
            return
        entry = {
            "ts": datetime.now(UTC).isoformat(),
            "event": event,
            **fields,
        }
        try:
            with self._path.open("a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as exc:
            log.error("не удалось записать в журнал аудита", error=str(exc))
