"""Запуск симулятора: ``remo32-espsim``."""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import sys

import uvicorn

from remo32_core.log import configure_logging, get_logger
from remo32_espsim import __version__
from remo32_espsim.config import SimulatorSettings
from remo32_espsim.device import SimulatedDevice
from remo32_espsim.http_server import create_app

log = get_logger("espsim")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="remo32-espsim",
        description="Программный симулятор аппаратного контроллера ESP32 (не прошивка!)",
    )
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--device-id", default="esp32-main")
    parser.add_argument("--mode", choices=["http", "mqtt", "both"], default="http")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8090)
    parser.add_argument("--token", help="Токен, который потребуется от контроллера")
    parser.add_argument("--mqtt-host")
    parser.add_argument("--mqtt-port", type=int, default=1883)
    parser.add_argument("--mqtt-tls", action="store_true")
    parser.add_argument("--mqtt-username")
    parser.add_argument("--mqtt-password")
    parser.add_argument("--topic-prefix", default="remo32")
    parser.add_argument(
        "--real-wol",
        action="store_true",
        help=(
            "Отправлять НАСТОЯЩИЙ magic packet. Симулятор работает на обычном "
            "компьютере в вашей сети, поэтому пробуждение будет работать "
            "по-настоящему ещё до появления платы."
        ),
    )
    args = parser.parse_args(argv)

    configure_logging(level="INFO", fmt="console", component="espsim")

    settings = SimulatorSettings(
        device_id=args.device_id,
        mode=args.mode,
        host=args.host,
        port=args.port,
        token=args.token,
        mqtt_host=args.mqtt_host,
        mqtt_port=args.mqtt_port,
        mqtt_tls=args.mqtt_tls,
        mqtt_username=args.mqtt_username,
        mqtt_password=args.mqtt_password,
        mqtt_topic_prefix=args.topic_prefix,
        send_real_wol=args.real_wol,
    )

    device = SimulatedDevice(
        settings.device_id,
        wifi_ssid=settings.wifi_ssid,
        send_real_wol=settings.send_real_wol,
    )

    log.warning(
        "ЭТО СИМУЛЯТОР, А НЕ ЖЕЛЕЗО. Ничто из происходящего не подтверждает "
        "работоспособность настоящей платы",
        device_id=settings.device_id,
        mode=settings.mode,
        real_wol=settings.send_real_wol,
    )

    if settings.mode == "mqtt":
        from remo32_espsim.mqtt_client import run_mqtt

        with contextlib.suppress(KeyboardInterrupt):
            asyncio.run(run_mqtt(device, settings))
        return 0

    app = create_app(device, settings.token)

    if settings.mode == "both":
        if not settings.mqtt_host:
            log.error("для режима both требуется --mqtt-host")
            return 2

        from remo32_espsim.mqtt_client import run_mqtt

        @app.on_event("startup")
        async def _start_mqtt() -> None:
            asyncio.create_task(run_mqtt(device, settings))  # noqa: RUF006

    uvicorn.run(app, host=settings.host, port=settings.port, log_config=None, access_log=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
