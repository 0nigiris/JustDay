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
    def __init__(self, path: Path | None) -> None:
        self._path = path.expanduser() if path else None
        self._ready = False

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

    def record(self, event: str, **fields: Any) -> None:
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
