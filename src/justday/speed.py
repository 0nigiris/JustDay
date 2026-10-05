"""Замеры скорости: `justday test speed`.

Без цифр «оптимизировать» — гадание. Каждый замер — одна строка: что мерили, сколько вышло и
какой потолок мы считаем терпимым. Всё, что выше потолка, в конце собирается списком «медленное».
Модель зовётся дважды хайку на одно слово — это копейки лимита, и ради честной цифры стоит.
"""
from __future__ import annotations

import json
import os
import shutil
import statistics
import subprocess
import time
from collections.abc import Callable
from pathlib import Path

from . import config

# замер → потолок в секундах. Выше — попадает в список «медленное».
LIMITS = {
    "демон: ответ на status": 0.15,
    "быстрый путь: разбор «врубай»": 0.02,
    "каталог программ, холодный": 0.5,
    "каталог программ, из кэша": 0.01,
    "claude -p, хайку, голый: до слова": 6.0,
    "claude -p, хайку, с нашим плагином: до слова": 9.0,
    "ход голоса, медиана по журналу": 12.0,
    "opencode run, один ход до слова": 15.0,
}


def _once(fn: Callable[[], object], n: int = 1) -> float:
    best = []
    for _ in range(n):
        t = time.perf_counter()
        fn()
        best.append(time.perf_counter() - t)
    return statistics.median(best)


def _claude(extra: list[str]) -> float:
    """Секунды от запуска `claude -p` до готового ответа в одно слово."""
    cmd = [shutil.which("claude") or "claude", "-p", "Ответь одним словом: да", "--model", "haiku",
           "--output-format", "json", "--no-session-persistence", *extra]
    t = time.perf_counter()
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=120, cwd=str(config.STATE_DIR))
    took = time.perf_counter() - t
    if json.loads(out.stdout or "{}").get("is_error"):
        raise RuntimeError("claude вернул ошибку (лимит?)")
    return took


def _opencode() -> float:
    """Секунды от `opencode run` до слова ответа. Ступень лестницы платит это на каждой задаче."""
    from . import shell
    cmd = ["opencode", "run", "--format", "json", "-m", "openrouter/qwen/qwen3-coder", "ответь одним словом: да"]
    t = time.perf_counter()
    try:
        out = subprocess.run(cmd, env=shell.env(), capture_output=True, text=True, timeout=100)
    except subprocess.TimeoutExpired:
        return 100.0   # висит на запуске, не отвечая вовсе
    if '"type":"text"' not in out.stdout:
        raise RuntimeError("слова не вышло: " + (out.stderr or out.stdout)[-80:])
    return time.perf_counter() - t


def _turns_from_journal(limit: int = 200) -> float:
    """Медиана длины хода по настоящему журналу — то, что человек правда ждал, а не лабораторная цифра."""
    ms = []
    for line in config.EVENTS_FILE.read_text(encoding="utf-8").splitlines()[-20000:]:
        if '"turn_done"' in line:
            try:
                e = json.loads(line)
            except ValueError:
                continue
            if not e.get("error") and e.get("ms"):
                ms.append(e["ms"] / 1000)
    if not ms:
        raise RuntimeError("в журнале нет ходов")
    return statistics.median(ms[-limit:])


def _island_cpu(seconds: float = 3.0) -> float:
    """Доля одного ядра, которую островок ест в покое. Это не секунды, потому и без потолка в LIMITS."""
    def ticks() -> float:
        total = 0.0
        for d in Path("/proc").glob("[0-9]*"):
            try:
                if (d / "comm").read_text().strip() not in ("quickshell", "qs"):
                    continue
                f = (d / "stat").read_text().rsplit(")", 1)[1].split()
                total += int(f[11]) + int(f[12])
            except (OSError, IndexError, ValueError):
                continue
        return total / os.sysconf("SC_CLK_TCK")
    a = ticks()
    time.sleep(seconds)
    return (ticks() - a) / seconds


def measure() -> list[tuple[str, float | None, str]]:
    """[(имя, секунды | None, пояснение)] — None, если замерить нечем."""
    from . import desktop, dispatch, localllm, media
    from .cli import control

    rows: list[tuple[str, float | None, str]] = []

    def add(name: str, fn: Callable[[], float | None], note: str = "") -> None:
        try:
            rows.append((name, fn(), note))
        except Exception as e:
            rows.append((name, None, f"не вышло: {str(e)[:80]}"))

    def status() -> float:
        if not control("status", timeout=5).get("ok"):
            raise RuntimeError("демон не запущен")
        return _once(lambda: control("status", timeout=5), 5)
    add("демон: ответ на status", status)
    add("быстрый путь: разбор «врубай»", lambda: _once(lambda: media.parse("врубай"), 20))

    def apps_cold() -> float:
        desktop._apps_cache = None
        return _once(desktop.list_apps)
    add("каталог программ, холодный", apps_cold)
    add("каталог программ, из кэша", lambda: _once(desktop.list_apps, 20))

    def judge() -> float:
        if not localllm.available():
            raise RuntimeError("местной модели нет — судьи на горячем пути и так нет")
        return _once(lambda: dispatch.level_for("который час"))
    add("судья (местная модель)", judge, "с 3 октября на горячем пути его нет (brain.ask_judge=never)")
    add("claude -p, хайку, голый: до слова", lambda: _claude(["--strict-mcp-config"]))
    add("claude -p, хайку, с нашим плагином: до слова",
        lambda: _claude(["--plugin-dir", str(config.REPO_DIR / "plugin")]))
    add("ход голоса, медиана по журналу", _turns_from_journal)
    if os.environ.get("JUSTDAY_SPEED_OPENCODE") and shutil.which("opencode"):   # зовёт модель, идёт 30+ секунд
        add("opencode run, один ход до слова", _opencode)
    add("остров в покое, ядер CPU (меньше — лучше)", _island_cpu, "порог 0.05 ядра")
    return rows


def report() -> str:
    """Печатает таблицу, возвращает строку-итог (исключение, если что-то медленное)."""
    slow = []
    for name, sec, note in measure():
        if sec is None:
            print(f"  – {name:<46} {note}")
            continue
        limit = LIMITS.get(name)
        if name.startswith("остров"):
            bad, shown = sec > 0.05, f"{sec:.3f}"
        else:
            bad, shown = bool(limit) and sec > limit, f"{sec:.3f}s" if sec < 1 else f"{sec:.1f}s"
        print(f"  {'⚠' if bad else '✔'} {name:<46} {shown:>8}  {note}")
        if bad:
            slow.append(name)
    if slow:
        raise RuntimeError("медленное: " + "; ".join(slow))
    return "всё в пределах"
