"""Сбор статистики: устойчивость к недоступным датчикам."""

from __future__ import annotations

import pytest

from remo32_agent.stats import collector
from remo32_agent.stats.gpu import collect_gpus, collect_nvidia
from remo32_core.models import SystemStats


def test_collect_stats_returns_valid_model() -> None:
    stats = collector.collect_stats()
    assert isinstance(stats, SystemStats)
    assert stats.platform == "linux"
    assert stats.cpu.core_count is not None


def test_broken_collector_degrades_instead_of_crashing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Сломанный датчик попадает в degraded, остальные продолжают работать."""

    def boom() -> None:
        raise RuntimeError("датчик умер")

    monkeypatch.setattr(collector, "_temperatures", boom)
    stats = collector.collect_stats()
    assert "temperatures" in stats.degraded
    assert stats.temperatures == []
    # Остальное собралось.
    assert stats.cpu.core_count is not None
    assert stats.memory.total_bytes is not None


def test_all_collectors_can_fail_without_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def boom(*args: object, **kwargs: object) -> None:
        raise OSError("всё сломалось")

    for name in ("_cpu", "_memory", "_disks", "_networks", "_temperatures", "_uptime"):
        monkeypatch.setattr(collector, name, boom)
    monkeypatch.setattr(collector, "collect_gpus", boom)

    stats = collector.collect_stats()
    assert len(stats.degraded) >= 6
    # Модель всё равно валидна: интерфейсу есть что показать.
    assert stats.cpu.usage_percent is None


def test_missing_nvidia_smi_returns_empty(monkeypatch: pytest.MonkeyPatch) -> None:
    """Отсутствие видеокарты — не ошибка."""

    def not_found(*args: object, **kwargs: object) -> None:
        raise FileNotFoundError

    monkeypatch.setattr("subprocess.run", not_found)
    assert collect_nvidia() == []
    assert collect_gpus() == []


def test_nvidia_na_values_become_none(monkeypatch: pytest.MonkeyPatch) -> None:
    """nvidia-smi печатает [N/A] — это должно стать null, а не сломать разбор."""
    import subprocess

    class FakeProc:
        returncode = 0
        stdout = "0, GeForce RTX 3060, 12, 12288, 1024, 45, [N/A], [Not Supported]\n"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeProc())
    gpus = collect_nvidia()
    assert len(gpus) == 1
    assert gpus[0].name == "GeForce RTX 3060"
    assert gpus[0].utilization_percent == 12
    assert gpus[0].memory_total_bytes == 12288 * 1024 * 1024
    assert gpus[0].power_watts is None
    assert gpus[0].fan_percent is None


def test_malformed_nvidia_line_is_skipped(monkeypatch: pytest.MonkeyPatch) -> None:
    import subprocess

    class FakeProc:
        returncode = 0
        stdout = "мусор\n0, GPU, 1, 2, 3, 4, 5, 6\n"

    monkeypatch.setattr(subprocess, "run", lambda *a, **k: FakeProc())
    assert len(collect_nvidia()) == 1
