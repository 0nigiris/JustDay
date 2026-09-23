"""Настройки симулятора (только через аргументы командной строки и окружение)."""

from __future__ import annotations

from typing import Literal

from pydantic_settings import BaseSettings, SettingsConfigDict


class SimulatorSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="REMO32_SIM_", extra="forbid")

    device_id: str = "esp32-main"
    mode: Literal["http", "mqtt", "both"] = "http"

    host: str = "127.0.0.1"
    port: int = 8090
    token: str | None = None

    mqtt_host: str | None = None
    mqtt_port: int = 1883
    mqtt_tls: bool = False
    mqtt_username: str | None = None
    mqtt_password: str | None = None
    mqtt_topic_prefix: str = "remo32"
    status_interval_seconds: float = 10.0

    wifi_ssid: str = "СИМУЛЯЦИЯ"
    send_real_wol: bool = False
    log_level: str = "INFO"
