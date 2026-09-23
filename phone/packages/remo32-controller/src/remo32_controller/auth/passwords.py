"""Пароли.

Argon2id — современный стандарт для хранения паролей: он специально
медленный и требовательный к памяти, поэтому перебор дорог.

Сам пароль в системе не хранится нигде: только хэш, и только в переменной
окружения или в файле с правами 0600.
"""

from __future__ import annotations

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError

from remo32_core.log import get_logger

log = get_logger("controller.auth.passwords")

# Параметры по умолчанию у argon2-cffi разумны для домашнего сервера:
# ~64 МБ памяти и несколько десятков миллисекунд на проверку.
_hasher = PasswordHasher()


def hash_password(password: str) -> str:
    if len(password) < 8:
        raise ValueError("пароль должен быть не короче 8 символов")
    return _hasher.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    """Проверяет пароль. Любая ошибка означает «не совпал».

    Ошибки перехватываются широко намеренно: в переменную с хэшем легко
    попасть мусору при копировании, и это должно приводить к вежливому
    отказу во входе, а не к пятисотке.
    """
    try:
        _hasher.verify(stored_hash, password)
    except (VerifyMismatchError, VerificationError):
        return False
    except InvalidHashError:
        log.error("хэш пароля повреждён или имеет неверный формат")
        return False
    except (UnicodeEncodeError, ValueError, TypeError) as exc:
        log.error("хэш пароля непригоден для проверки", error=str(exc))
        return False
    return True


def needs_rehash(stored_hash: str) -> bool:
    try:
        return _hasher.check_needs_rehash(stored_hash)
    except InvalidHashError:
        return False
