"""Цикл ассистента: свой круг дел, пока человек ничем его не занял (п.28 плана 13 октября).

Шаги лежат в config.toml, `[[cycle.steps]]`, и целиком его: что делать (`run` — команда оболочки),
когда (`at = "05:00"` раз в сутки после этого часа или `every_hours = N`), только ли без него
(`away = true`) и включён ли шаг (`on`). Подтверждений цикл не спрашивает — значит, необратимого
(письма, оплата, удаление) в шаги класть нельзя; умолчания только смотрят и обновляют.

Каждый шаг идёт отдельной службой `justday-cycle` (systemd-run), а не ребёнком демона: шаг
«обновить JustDay» перезапускает демон, и ребёнок погиб бы вместе с ним посреди установки. Одно имя
службы заодно не даёт двум шагам идти разом.
"""
from __future__ import annotations

import fcntl
import json
import os
import re
import shutil
import subprocess
import sys
import time

from . import config

DIR = config.STATE_DIR / "цикл"
LAST = DIR / "last.json"
UNIT = "justday-cycle"
TIMEOUT = 1800  # шаг дольше получаса — завис; следующий круг его не ждёт


def steps(cfg: dict | None = None) -> list[dict]:
    return list(((cfg or config.load()).get("cycle") or {}).get("steps") or [])


def edit(index: int, field: str, value: str) -> list[dict]:
    """Update one safe schedule field or move a step; the command itself is never editable here."""
    current = steps()
    if not 0 <= index < len(current):
        raise ValueError("номер шага вне списка")
    if field == "order":
        delta = {"up": -1, "down": 1}.get(value)
        target = index + delta if delta is not None else -1
        if not 0 <= target < len(current):
            return current
        current[index], current[target] = current[target], current[index]
    elif field in {"on", "away"}:
        if value.lower() not in {"true", "false"}:
            raise ValueError("ожидается true или false")
        current[index][field] = value.lower() == "true"
    elif field == "at":
        if not re.fullmatch(r"(?:[01]\d|2[0-3]):[0-5]\d", value):
            raise ValueError("время должно быть в формате ЧЧ:ММ")
        current[index].pop("every_hours", None)
        current[index]["at"] = value
    elif field == "every_hours":
        try:
            hours = float(value)
        except ValueError as e:
            raise ValueError("интервал должен быть числом часов") from e
        if not 0.1 <= hours <= 8760:
            raise ValueError("интервал должен быть от 0,1 до 8760 часов")
        current[index].pop("at", None)
        current[index]["every_hours"] = hours
    else:
        raise ValueError("можно менять только включение, расписание, условие отсутствия и порядок")
    config.set_cycle_steps(current)
    return current


def last() -> dict:
    try:
        return json.loads(LAST.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _at_today(at: str, now: float) -> float:
    h, m = (int(x) for x in at.split(":"))
    lt = time.localtime(now)
    return time.mktime((lt.tm_year, lt.tm_mon, lt.tm_mday, h, m, 0, 0, 0, -1))


def due(step: dict, ran: float, now: float, here: bool | None) -> bool:
    """Пора ли шагу. here — сидит ли он за машиной (None — неизвестно, островок молчит)."""
    if not step.get("on", True) or not step.get("run"):
        return False
    # None — островок не ответил, а «не знаю» за человека не считается: шаг «без него» ждёт явного «ушёл»
    if step.get("away") and here is not False:
        return False
    if step.get("at"):
        mark = _at_today(step["at"], now)
        return now >= mark and ran < mark
    return now - ran >= float(step.get("every_hours") or 24) * 3600


def next_due(cfg: dict, here: bool | None, now: float | None = None) -> dict | None:
    now = time.time() if now is None else now
    seen = last()
    return next((s for s in steps(cfg) if due(s, float(seen.get(s.get("name", ""), 0)), now, here)), None)


def running() -> bool:
    return subprocess.run(["systemctl", "--user", "is-active", "--quiet", f"{UNIT}.service"],
                          capture_output=True).returncode == 0


def launch(name: str) -> bool:
    """Отдать шаг отдельной службе и сразу вернуться. False — служба уже занята или systemd-run нет."""
    if not shutil.which("systemd-run"):
        return False
    subprocess.run(["systemctl", "--user", "reset-failed", f"{UNIT}.service"], capture_output=True)
    cmd = [sys.executable, "-m", "justday.cli", "cycle", "run", name]
    return subprocess.run(["systemd-run", "--user", f"--unit={UNIT}", "--collect", "--quiet",
                           f"-pRuntimeMaxSec={TIMEOUT}", *cmd], capture_output=True, timeout=15).returncode == 0


def run(name: str) -> int:
    """Выполнить шаг здесь же и записать в журнал дня. Возвращает код команды."""
    step = next((s for s in steps() if s.get("name") == name), None)
    if not step:
        raise SystemExit(f"в цикле нет шага «{name}» (justday cycle — список)")
    DIR.mkdir(parents=True, exist_ok=True)
    # Ручной `justday cycle run` идёт мимо службы, и systemd его не видит: без этой блокировки два
    # шага «обновить» шли бы параллельно и топтали одну установку. Держится, пока жив процесс.
    with open(DIR / "run.lock", "w") as lock:
        try:
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            print(f"другой шаг цикла уже идёт — «{name}» не запускаю")
            return 75
        return _run_step(step)


def _run_step(step: dict) -> int:
    name = step["name"]
    # время запуска, а не конца: упавший или зависший шаг тоже считается сделанным в этот круг,
    # иначе демон дёргал бы его каждую минуту до утра
    seen = last()
    seen[name] = time.time()
    tmp = LAST.with_suffix(".tmp")
    tmp.write_text(json.dumps(seen, ensure_ascii=False), encoding="utf-8")
    os.replace(tmp, LAST)
    t0 = time.time()
    try:
        # `justday` в шаге — тот же, что запустил цикл, даже если ~/.local/bin нет в PATH службы
        env = {**os.environ, "PATH": f"{os.path.dirname(sys.executable)}:{os.environ.get('PATH', '')}"}
        p = subprocess.run(step["run"], shell=True, capture_output=True, text=True, timeout=TIMEOUT,
                           stdin=subprocess.DEVNULL, env=env)
        code, out = p.returncode, (p.stdout + p.stderr).strip()
    except subprocess.TimeoutExpired:
        code, out = 124, f"не уложился в {TIMEOUT // 60} минут"
    took = round(time.time() - t0)
    line = f"- {time.strftime('%H:%M', time.localtime(t0))} {name} — {'готово' if code == 0 else f'ошибка {code}'} ({took} с)\n"
    if code != 0 and out:
        line += "".join(f"    {s}\n" for s in out.splitlines()[-8:])
    with (DIR / f"{time.strftime('%Y-%m-%d')}.md").open("a", encoding="utf-8") as f:
        f.write(line)
    if code != 0 and shutil.which("notify-send"):
        subprocess.run(["notify-send", "-a", "JustDay", f"Цикл: «{name}» не вышел", (out.splitlines() or [""])[-1][:200]],
                       capture_output=True, timeout=5)
    return code


def journal(day: str = "") -> str:
    p = DIR / f"{day or time.strftime('%Y-%m-%d')}.md"
    return p.read_text(encoding="utf-8") if p.exists() else ""
