"""Сбор полного снимка состояния машины.

Главное правило модуля: **ни один сбойный датчик не должен помешать
остальным**. Каждый сборщик обёрнут, его имя при падении попадает в
``SystemStats.degraded``, а поле остаётся ``None``.
"""

from __future__ import annotations

import os
import platform
import socket
import time
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import psutil

from remo32_agent.stats.gpu import collect_gpus
from remo32_core.log import get_logger
from remo32_core.models import (
    CpuStats,
    DiskStats,
    GpuStats,
    MemoryStats,
    NetworkStats,
    SystemStats,
    TemperatureReading,
)

log = get_logger("agent.stats")

# Псевдофайловые системы: показывать их пользователю бессмысленно.
_SKIP_FSTYPES = frozenset(
    {
        "autofs",
        "binfmt_misc",
        "bpf",
        "cgroup",
        "cgroup2",
        "configfs",
        "debugfs",
        "devpts",
        "devtmpfs",
        "efivarfs",
        "fuse.gvfsd-fuse",
        "fuse.portal",
        "fusectl",
        "hugetlbfs",
        "mqueue",
        "proc",
        "pstore",
        "ramfs",
        "securityfs",
        "selinuxfs",
        "squashfs",
        "sysfs",
        "tracefs",
    }
)

_SKIP_IFACE_PREFIXES = ("lo", "veth", "docker", "br-", "virbr")


def _cpu() -> CpuStats:
    load: tuple[float, float, float] | None
    try:
        raw = os.getloadavg()
        load = (raw[0], raw[1], raw[2])
    except (OSError, AttributeError):
        load = None  # Windows до 3.11 и некоторые контейнеры

    freq_mhz: float | None = None
    try:
        freq = psutil.cpu_freq()
        freq_mhz = freq.current if freq else None
    except (OSError, NotImplementedError, AttributeError):
        freq_mhz = None  # виртуалки и ARM часто не отдают частоту

    return CpuStats(
        usage_percent=psutil.cpu_percent(interval=None),
        core_count=psutil.cpu_count(logical=True),
        frequency_mhz=freq_mhz,
        load_average=load,
    )


def _memory() -> MemoryStats:
    vm = psutil.virtual_memory()
    swap_total: int | None
    swap_used: int | None
    try:
        sw = psutil.swap_memory()
        swap_total, swap_used = sw.total, sw.used
    except (OSError, RuntimeError):
        swap_total = swap_used = None
    return MemoryStats(
        total_bytes=vm.total,
        used_bytes=vm.used,
        available_bytes=vm.available,
        usage_percent=vm.percent,
        swap_total_bytes=swap_total,
        swap_used_bytes=swap_used,
    )


def _disks() -> list[DiskStats]:
    out: list[DiskStats] = []
    seen: set[str] = set()
    for part in psutil.disk_partitions(all=False):
        if part.fstype in _SKIP_FSTYPES or part.device in seen:
            continue
        seen.add(part.device)
        try:
            usage = psutil.disk_usage(part.mountpoint)
        except (PermissionError, OSError):
            # Примонтированный, но недоступный раздел — показываем без цифр.
            out.append(DiskStats(mountpoint=part.mountpoint, device=part.device))
            continue
        out.append(
            DiskStats(
                mountpoint=part.mountpoint,
                device=part.device,
                total_bytes=usage.total,
                used_bytes=usage.used,
                free_bytes=usage.free,
                usage_percent=usage.percent,
            )
        )
    return out


def _networks() -> list[NetworkStats]:
    counters = psutil.net_io_counters(pernic=True)
    stats = psutil.net_if_stats()
    out: list[NetworkStats] = []
    for name, c in counters.items():
        if name.startswith(_SKIP_IFACE_PREFIXES):
            continue
        st = stats.get(name)
        out.append(
            NetworkStats(
                interface=name,
                bytes_sent=c.bytes_sent,
                bytes_received=c.bytes_recv,
                packets_sent=c.packets_sent,
                packets_received=c.packets_recv,
                errors_in=c.errin,
                errors_out=c.errout,
                is_up=st.isup if st else None,
            )
        )
    return out


def _temperatures() -> list[TemperatureReading]:
    getter = getattr(psutil, "sensors_temperatures", None)
    if getter is None:
        return []  # Windows/macOS — psutil этого не умеет
    out: list[TemperatureReading] = []
    for chip, entries in (getter() or {}).items():
        for entry in entries:
            label = f"{chip}/{entry.label}" if entry.label else chip
            out.append(
                TemperatureReading(
                    label=label,
                    celsius=entry.current,
                    high_celsius=entry.high,
                    critical_celsius=entry.critical,
                )
            )
    return out


def _uptime() -> tuple[float | None, datetime | None]:
    try:
        boot = psutil.boot_time()
    except (OSError, RuntimeError):
        return None, None
    return max(0.0, time.time() - boot), datetime.fromtimestamp(boot, tz=UTC)


def collect_stats() -> SystemStats:
    """Снимок состояния машины. Никогда не бросает исключений."""
    degraded: list[str] = []

    def safe[T](name: str, fn: Callable[[], T], fallback: T) -> T:
        try:
            return fn()
        except Exception as exc:
            log.warning("сборщик статистики упал", collector=name, error=str(exc))
            degraded.append(name)
            return fallback

    # Заглушки объявлены с типами: пустой литерал не даёт вывести
    # содержимое списка, и проверка типов теряла бы смысл.
    no_uptime: tuple[float | None, datetime | None] = (None, None)
    no_disks: list[DiskStats] = []
    no_networks: list[NetworkStats] = []
    no_temperatures: list[TemperatureReading] = []
    no_gpus: list[GpuStats] = []
    no_hostname: str | None = None

    uptime_seconds, boot_time = safe("uptime", _uptime, no_uptime)

    return SystemStats(
        hostname=safe("hostname", socket.gethostname, no_hostname),
        platform=platform.system().lower(),
        uptime_seconds=uptime_seconds,
        boot_time=boot_time,
        cpu=safe("cpu", _cpu, CpuStats()),
        memory=safe("memory", _memory, MemoryStats()),
        disks=safe("disks", _disks, no_disks),
        networks=safe("networks", _networks, no_networks),
        temperatures=safe("temperatures", _temperatures, no_temperatures),
        gpus=safe("gpus", collect_gpus, no_gpus),
        degraded=degraded,
    )


def prime_cpu_percent() -> None:
    """Первый вызов ``cpu_percent`` всегда возвращает 0.0.

    Дёргаем его на старте агента, чтобы первый же запрос статистики отдал
    осмысленное число, а не ноль.
    """
    try:
        psutil.cpu_percent(interval=None)
    except Exception as exc:
        log.debug("не удалось инициализировать cpu_percent", error=str(exc))


def summary_line(stats: SystemStats) -> dict[str, Any]:
    """Компактное представление для лога."""
    return {
        "cpu": stats.cpu.usage_percent,
        "mem": stats.memory.usage_percent,
        "gpus": len(stats.gpus),
        "degraded": stats.degraded or None,
    }
