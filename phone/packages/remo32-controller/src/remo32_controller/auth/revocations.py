"""Отозванные сессии, пережившие перезапуск.

Сессия — это подписанный токен: сервер не хранит его и по одной подписи не
может отличить действующий от отменённого. Значит список отмен нужно вести
отдельно, и вести на диске.

Раньше он жил в памяти процесса, и «Выйти» переставало действовать после
первого же перезапуска службы: украденная сессия воскресала и работала
оставшиеся тридцать дней. Обновление контроллера — обычное дело, так что
это была не теоретическая дыра.

Здесь два механизма, и второй важнее первого:

* точечный отзыв по идентификатору сессии — обычный выход;
* граница времени: все токены, выданные раньше отметки, недействительны.
  Это «выйти на всех устройствах» — единственный ответ на «кажется, у меня
  увели телефон», когда сам токен неизвестен.
"""

from __future__ import annotations

import json
import os
import tempfile
import time
from pathlib import Path

from remo32_core.log import get_logger

log = get_logger("controller.auth.revocations")


class RevocationStore:
    """Список отмен. Файл маленький и читается целиком.

    Путь ``None`` означает «только в памяти»: так удобно в тестах, но в
    рабочей системе это молча ломает выход — перезапуск службы воскрешает
    все отозванные сессии. Поэтому контроллер всегда передаёт файл.
    """

    def __init__(self, path: Path | str | None) -> None:
        self._path = Path(path).expanduser() if path is not None else None
        self._revoked: set[str] = set()
        self._not_before: float = 0.0
        if self._path is not None:
            self._load()

    # --- чтение ---------------------------------------------------------

    def _load(self) -> None:
        if self._path is None:
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return
        except (OSError, ValueError) as exc:
            # Испорченный файл не должен мешать входу, но и молча
            # открывать отозванные сессии тоже нельзя: пишем в журнал.
            log.warning("список отзывов не читается", path=str(self._path), error=str(exc))
            return

        self._revoked = {str(x) for x in data.get("revoked", [])}
        self._not_before = float(data.get("not_before", 0))

    def is_revoked(self, jti: str | None, issued_at: float | None) -> bool:
        if jti is not None and jti in self._revoked:
            return True
        return issued_at is not None and issued_at < self._not_before

    @property
    def not_before(self) -> float:
        return self._not_before

    # --- запись ---------------------------------------------------------

    def revoke(self, jti: str) -> None:
        self._revoked.add(jti)
        self._save()

    def revoke_all(self) -> None:
        """Обрубает все выданные сессии разом.

        Заодно очищает поимённый список: он больше не нужен, всё старое и
        так отсечено по времени, а файл не должен расти вечно.
        """
        self._not_before = time.time()
        self._revoked.clear()
        self._save()
        log.warning("отозваны все сессии")

    def _save(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {"revoked": sorted(self._revoked), "not_before": self._not_before},
            ensure_ascii=False,
        )
        handle, tmp_name = tempfile.mkstemp(dir=self._path.parent, prefix=".sessions-")
        tmp = Path(tmp_name)
        try:
            with os.fdopen(handle, "w", encoding="utf-8") as fh:
                fh.write(payload)
                fh.flush()
                os.fsync(fh.fileno())
            tmp.chmod(0o600)
            tmp.replace(self._path)
        except BaseException:
            tmp.unlink(missing_ok=True)
            raise
