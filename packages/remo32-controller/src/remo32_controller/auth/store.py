"""Хранилище зарегистрированных passkey.

Обычный JSON-файл: ключей у одного человека единицы, база данных здесь
была бы лишней зависимостью ради ничего.

В файле нет секретов в привычном смысле — только публичные ключи и
счётчики. Тем не менее права 0600: подмена содержимого равносильна
подмене владельца системы.
"""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

from remo32_core.log import get_logger

log = get_logger("controller.auth.store")


@dataclass(slots=True)
class StoredCredential:
    """Зарегистрированный passkey."""

    credential_id: str
    """base64url — идентификатор ключа."""

    public_key: str
    """base64url — открытый ключ в формате COSE."""

    sign_count: int
    label: str
    created_at: str
    last_used_at: str | None = None
    transports: list[str] | None = None


class CredentialStore:
    def __init__(self, path: Path) -> None:
        self._path = path.expanduser()
        self._credentials: dict[str, StoredCredential] = {}
        self._load()

    def _load(self) -> None:
        if not self._path.is_file():
            return
        try:
            raw = json.loads(self._path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            log.error("не удалось прочитать хранилище passkey", error=str(exc))
            return
        for item in raw.get("credentials", []):
            try:
                cred = StoredCredential(**item)
            except TypeError as exc:
                log.warning("пропущена повреждённая запись passkey", error=str(exc))
                continue
            self._credentials[cred.credential_id] = cred
        log.info("загружены passkey", count=len(self._credentials))

    def _save(self) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"version": 1, "credentials": [asdict(c) for c in self._credentials.values()]}
        # Пишем во временный файл и переименовываем: так файл никогда не
        # окажется наполовину записанным, если процесс упадёт.
        tmp = self._path.with_suffix(".tmp")
        fd = os.open(tmp, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, ensure_ascii=False, indent=2)
        os.replace(tmp, self._path)

    def add(self, credential: StoredCredential) -> None:
        self._credentials[credential.credential_id] = credential
        self._save()
        log.info("зарегистрирован passkey", label=credential.label)

    def remove(self, credential_id: str) -> bool:
        if self._credentials.pop(credential_id, None) is None:
            return False
        self._save()
        return True

    def get(self, credential_id: str) -> StoredCredential | None:
        return self._credentials.get(credential_id)

    def all(self) -> list[StoredCredential]:
        return list(self._credentials.values())

    def __len__(self) -> int:
        return len(self._credentials)

    def touch(self, credential_id: str, sign_count: int) -> None:
        """Обновляет счётчик после успешного входа.

        Счётчик защищает от клонирования аутентификатора: если он не растёт,
        значит ключ, возможно, скопирован.
        """
        cred = self._credentials.get(credential_id)
        if cred is None:
            return
        cred.sign_count = sign_count
        cred.last_used_at = datetime.now(UTC).isoformat()
        self._save()
