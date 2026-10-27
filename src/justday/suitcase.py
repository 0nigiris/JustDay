"""«Чемодан»: перенос настроек и ключей на другой компьютер одним зашифрованным файлом.

Беда. На школьном ПК человеку лень настраивать всё заново, а ключи нельзя ни пересылать открытым
текстом, ни оставлять на чужой машине. Чемодан — один файл `.jdcase`, зашифрованный паролем, который
знает только он (тот же openssl + pbkdf2, что и у флешки). Внутри: настройки, закрепки и ключи.
Память разговоров и контакты не едут: они личные, и на чужом ПК им нечего делать.
"""
from __future__ import annotations

from pathlib import Path

from . import config, portable

VERSION = 1
# Файлы данных, которые едут вместе с настройками: имя → где лежит.
FILES = {"pins.json": config.DATA_DIR / "pins.json"}


def pack(passphrase: str) -> bytes:
    if not passphrase:
        raise ValueError("чемодан без пароля не собирается: в нём ключи")
    body = {"v": VERSION, "files": {}, "secrets": config.list_secrets()}
    if config.CONFIG_FILE.exists():
        body["config"] = config.CONFIG_FILE.read_text(encoding="utf-8")
    for name, path in FILES.items():
        if path.exists():
            body["files"][name] = path.read_text(encoding="utf-8")
    return portable.seal(body, passphrase)


def unpack(blob: bytes, passphrase: str, replace_config: bool = True) -> dict:
    """Разложить чемодан по местам. Прежний config.toml не теряется: уезжает в config.toml.before-suitcase."""
    body = portable.unseal(blob, passphrase)
    if body.get("v") != VERSION:
        raise RuntimeError("чемодан от другой версии JustDay")
    out = {"secrets": 0, "files": 0, "config": False}
    if replace_config and body.get("config"):
        config.CONFIG_DIR.mkdir(parents=True, exist_ok=True)
        if config.CONFIG_FILE.exists():
            config.CONFIG_FILE.replace(config.CONFIG_FILE.with_name("config.toml.before-suitcase"))
        config.write_private(config.CONFIG_FILE, body["config"])
        out["config"] = True
    for name, text in (body.get("files") or {}).items():
        if name in FILES:                      # только известные имена: чужой чемодан не пишет куда хочет
            FILES[name].parent.mkdir(parents=True, exist_ok=True)
            FILES[name].write_text(text, encoding="utf-8")
            out["files"] += 1
    for key, value in (body.get("secrets") or {}).items():
        config.set_secret(key, str(value))
        out["secrets"] += 1
    return out


def save(path: str, passphrase: str) -> Path:
    dest = Path(path).expanduser()
    if dest.suffix != ".jdcase":
        dest = dest.with_name(dest.name + ".jdcase")
    dest.write_bytes(pack(passphrase))
    dest.chmod(0o600)
    return dest
