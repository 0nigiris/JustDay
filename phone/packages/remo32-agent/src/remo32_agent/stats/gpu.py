"""Сбор статистики GPU.

Три источника, каждый опционален. Если ничего не нашлось — возвращается
пустой список, и это нормальный ответ, а не ошибка: на серверном ПК
видеокарты может не быть вовсе.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from remo32_core.log import get_logger
from remo32_core.models import GpuStats

log = get_logger("agent.stats.gpu")

_NVIDIA_FIELDS = (
    "index",
    "name",
    "utilization.gpu",
    "memory.total",
    "memory.used",
    "temperature.gpu",
    "power.draw",
    "fan.speed",
)
_NVIDIA_TIMEOUT = 5.0


def _to_float(raw: str) -> float | None:
    """nvidia-smi для отсутствующих величин печатает [N/A] или [Not Supported]."""
    raw = raw.strip()
    if not raw or raw.startswith("[") or raw.lower() in {"n/a", "unknown"}:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def collect_nvidia() -> list[GpuStats]:
    try:
        proc = subprocess.run(  # noqa: S603 — фиксированный argv, без оболочки
            [
                "nvidia-smi",
                f"--query-gpu={','.join(_NVIDIA_FIELDS)}",
                "--format=csv,noheader,nounits",
            ],
            capture_output=True,
            text=True,
            timeout=_NVIDIA_TIMEOUT,
            check=False,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired, OSError) as exc:
        log.debug("nvidia-smi недоступен", error=str(exc))
        return []

    if proc.returncode != 0:
        log.debug("nvidia-smi вернул ошибку", returncode=proc.returncode)
        return []

    gpus: list[GpuStats] = []
    for line in proc.stdout.strip().splitlines():
        parts = [p.strip() for p in line.split(",")]
        if len(parts) != len(_NVIDIA_FIELDS):
            continue
        idx = _to_float(parts[0])
        mem_total = _to_float(parts[3])
        mem_used = _to_float(parts[4])
        gpus.append(
            GpuStats(
                index=int(idx) if idx is not None else 0,
                name=parts[1] or None,
                vendor="nvidia",
                utilization_percent=_to_float(parts[2]),
                # nvidia-smi отдаёт мегабайты, наружу везде байты
                memory_total_bytes=int(mem_total * 1024 * 1024) if mem_total else None,
                memory_used_bytes=int(mem_used * 1024 * 1024) if mem_used else None,
                temperature_celsius=_to_float(parts[5]),
                power_watts=_to_float(parts[6]),
                fan_percent=_to_float(parts[7]),
            )
        )
    return gpus


def _read_int(path: Path) -> int | None:
    try:
        return int(path.read_text().strip())
    except (OSError, ValueError):
        return None


def collect_amd() -> list[GpuStats]:
    """AMD через sysfs (amdgpu). Без внешних утилит."""
    gpus: list[GpuStats] = []
    for index, card in enumerate(sorted(Path("/sys/class/drm").glob("card[0-9]*"))):
        device = card / "device"
        busy = device / "gpu_busy_percent"
        if not busy.exists():
            continue
        vram_total = _read_int(device / "mem_info_vram_total")
        vram_used = _read_int(device / "mem_info_vram_used")
        temp = None
        for hwmon in (device / "hwmon").glob("hwmon*"):
            raw = _read_int(hwmon / "temp1_input")
            if raw is not None:
                temp = raw / 1000.0  # millidegrees → °C
                break
        gpus.append(
            GpuStats(
                index=index,
                name=card.name,
                vendor="amd",
                utilization_percent=_read_int(busy),
                memory_total_bytes=vram_total,
                memory_used_bytes=vram_used,
                temperature_celsius=temp,
            )
        )
    return gpus


def collect_gpus() -> list[GpuStats]:
    """Все доступные GPU. Сбой одного вендора не мешает другому."""
    gpus: list[GpuStats] = []
    for collector in (collect_nvidia, collect_amd):
        try:
            gpus.extend(collector())
        except Exception as exc:
            log.warning("сборщик GPU упал", collector=collector.__name__, error=str(exc))
    return gpus
