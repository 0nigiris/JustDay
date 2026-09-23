"""Точка входа агента: ``remo32-agent`` или ``python -m remo32_agent``."""

from __future__ import annotations

import argparse
import sys

import uvicorn

from remo32_agent import __version__
from remo32_agent.config import generate_token, load_settings
from remo32_core.errors import ConfigurationError
from remo32_core.log import configure_logging, get_logger

log = get_logger("agent.main")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="remo32-agent", description="Агент Remo32 для управляемого ПК"
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--host", help="Переопределить адрес прослушивания")
    parser.add_argument("--port", type=int, help="Переопределить порт")
    parser.add_argument("--check", action="store_true", help="Проверить конфигурацию и выйти")
    parser.add_argument(
        "--generate-token", action="store_true", help="Напечатать новый токен и выйти"
    )
    args = parser.parse_args(argv)

    if args.generate_token:
        print(generate_token())
        return 0

    configure_logging(level="INFO", fmt="console", component="agent")

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
            agent_id=settings.agent_id,
            host=host,
            port=port,
            actions=len(settings.actions),
            terminal=settings.terminal.enabled,
        )
        return 0

    from remo32_agent.app import create_app

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
