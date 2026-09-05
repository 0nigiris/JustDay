"""Точка входа контроллера."""

from __future__ import annotations

import argparse
import getpass
import sys

import uvicorn

from remo32_controller import __version__
from remo32_core.errors import ConfigurationError
from remo32_core.log import configure_logging, get_logger

log = get_logger("controller.main")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="remo32-controller", description="Центральный контроллер Remo32"
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--host")
    parser.add_argument("--port", type=int)
    parser.add_argument("--check", action="store_true", help="Проверить конфигурацию и выйти")
    parser.add_argument(
        "--hash-password",
        action="store_true",
        help="Спросить пароль и напечатать его argon2-хэш для REMO32_PASSWORD_HASH",
    )
    parser.add_argument(
        "--gen-secret", action="store_true", help="Напечатать новый ключ подписи сессий"
    )
    args = parser.parse_args(argv)

    if args.hash_password:
        from remo32_controller.auth.passwords import hash_password

        password = getpass.getpass("Новый пароль: ")
        again = getpass.getpass("Повторите: ")
        if password != again:
            print("пароли не совпадают", file=sys.stderr)
            return 1
        try:
            print(hash_password(password))
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        return 0

    if args.gen_secret:
        from remo32_controller.config import generate_session_secret

        print(generate_session_secret())
        return 0

    configure_logging(level="INFO", fmt="console", component="controller")

    from remo32_controller.config import load_settings

    try:
        settings = load_settings()
    except ConfigurationError as exc:
        log.error("конфигурация некорректна", error=exc.message)
        return 2

    host = args.host or settings.server.host
    port = args.port or settings.server.port

    if args.check:
        log.info(
            "конфигурация в порядке",
            host=host,
            port=port,
            pcs=[pc.id for pc in settings.pcs],
            esp32=settings.esp32.transport if settings.esp32.enabled else "выключен",
        )
        return 0

    from remo32_controller.app import create_app

    uvicorn.run(
        create_app(settings, configure_logs=False),
        host=host,
        port=port,
        log_config=None,
        access_log=False,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
