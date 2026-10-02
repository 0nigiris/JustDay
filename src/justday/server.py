"""Режим сервера: компьютер выключен для человека и работает для ассистента.

Зачем. Человек уходит спать, а работа остаётся: собрать, проверить, дождаться возвращения лимита.
Гасить машину нельзя — работа встанет; оставлять как есть тоже плохо: экраны горят всю ночь, в
пустой комнате играет музыка, а через десять минут всё засыпает само и работа опять встаёт.

Что делает режим: гасит экраны, останавливает то, что играет, глушит звук, запрещает засыпание и
заводит сторожа, который сам вернёт машину человеку через несколько часов. Всё, что меняется,
записывается в файл состояния и возвращается обратно в `off()` — включая снятую с паузы музыку.

Сеанс **не** блокируется нарочно: ассистент управляет окнами того же сеанса, и блокировка отняла
бы у него руки ровно в тот момент, когда он остаётся работать один. Ввод мы тоже не отключаем, и
это решено осознанно: машина, у которой отняты мышь и клавиатура, а канал с телефона почему-то не
ответил, — кирпич. Пока в комнате никого, разницы нет, а цена ошибки разная.

Выход. Любое движение мышью будит экраны само — это делает монитор, а не мы. Поэтому режим
кончается не «когда человек вернулся», а когда его выключили: `justday server off`, или сам,
по сроку сторожа. Так честнее, чем угадывать по движению мыши, которое бывает и от кошки.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import time
from pathlib import Path

from . import config

STATE = Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "justday-server-mode.json"
# Сторож: отдельная служба-таймер, которая сама выключит режим. Нужна на случай, когда выключить
# его стало некому: работа оборвалась, окно закрыли, человек забыл. Без неё забытый режим значит
# машину, которая не спит неделю.
OFF_UNIT = "justday-server-off"


def _run(*cmd: str, timeout: float = 10) -> bool:
    if not shutil.which(cmd[0]):
        return False
    try:
        return subprocess.run(cmd, capture_output=True, timeout=timeout).returncode == 0
    except (OSError, subprocess.SubprocessError):
        return False


def _out(*cmd: str, timeout: float = 10) -> str:
    """Вывод команды или пустая строка. Нет команды — не беда: часть умений просто не будет."""
    if not shutil.which(cmd[0]):
        return ""
    try:
        done = subprocess.run(cmd, capture_output=True, timeout=timeout, text=True)
    except (OSError, subprocess.SubprocessError):
        return ""
    return done.stdout if done.returncode == 0 else ""


def _opts() -> dict:
    return (config.load().get("session") or {}).get("server_mode") or {}


def _screens(on: bool) -> bool:
    """Погасить или зажечь экраны. Это DPMS, а не выключение: мышь будит их сама."""
    return _run("kscreen-doctor", f"--dpms={'on' if on else 'off'}")


def _mute(on: bool) -> bool:
    return _run("wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1" if on else "0")


def _playing() -> list[str]:
    """Кто играет прямо сейчас. Имена, а не «все»: снимать с паузы надо ровно тех же.

    Глухой звук не останавливает ни фильм, ни ролик в браузере: видео продолжает идти, греть
    машину и мотать серию за серией. Поэтому играющее ставится на паузу, а не только глушится.
    """
    names = [n.strip() for n in _out("playerctl", "-l").splitlines() if n.strip()]
    return [n for n in names if _out("playerctl", "-p", n, "status").strip() == "Playing"]


def _players(action: str, names: list[str]) -> list[str]:
    """`pause` или `play` названным проигрывателям. Возвращает тех, кто послушался."""
    return [n for n in names if _run("playerctl", "-p", n, action)]


def _keep_awake(why: str) -> int:
    """Запретить засыпание, пока идёт работа. Возвращает pid сторожа, 0 — не вышло.

    Сторож — отдельный процесс systemd-inhibit, который просто спит: пока он жив, система не
    уснёт. Это надёжнее, чем менять настройки энергосбережения: мы ничего не ломаем человеку, и
    всё возвращается само, если нас убьют.
    """
    if not shutil.which("systemd-inhibit"):
        return 0
    try:
        p = subprocess.Popen(
            ["systemd-inhibit", "--what=idle:sleep:handle-lid-switch", "--who=JustDay",
             f"--why={why}", "--mode=block", "sleep", "infinity"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True)
        return p.pid
    except OSError:
        return 0


def awake(why: str = "ночная работа") -> int:
    """Запретить машине засыпать, ничего больше не выключая. Возвращает pid сторожа, 0 — не вышло.

    Это половина режима сервера: экран и звук остаются как есть. Нужно ночной работе — заснувшая
    машина не доделает задачу, а гасить человеку экран, когда он просто оставил работу на ночь,
    незачем.
    """
    return _keep_awake(why)


def _watchdog_on(hours: float) -> bool:
    """Завести сторожа, который сам выключит режим через `hours` часов.

    Делается службой systemd, а не своим процессом нарочно: наш процесс умрёт вместе с работой,
    а служба доживёт и вернёт человеку машину, даже если выключать режим стало некому.
    """
    cli = shutil.which("justday")
    if hours <= 0 or not cli:
        return False
    _watchdog_off()
    # `--quiet`: сторож срабатывает по сроку, а не потому, что человек вернулся. Зажечь экраны он
    # должен, а включать музыку — нет: концерт в пустой комнате никто не просил.
    return _run("systemd-run", "--user", "--collect", f"--unit={OFF_UNIT}",
                f"--on-active={int(hours * 3600)}",
                "--description=JustDay: вернуть машину человеку",
                cli, "server", "off", "--quiet")


def _watchdog_off() -> None:
    for unit in (f"{OFF_UNIT}.timer", f"{OFF_UNIT}.service"):
        _run("systemctl", "--user", "stop", unit)


def state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def on(why: str = "работа ассистента", hours: float = 0.0) -> dict:
    """Включить режим сервера. `hours` — через сколько сторож вернёт машину человеку."""
    was = state()
    if was.get("on"):
        return {"ok": True, "already": True, **was}
    opts = _opts()
    hours = hours or float(opts.get("hours") or 10)
    out: dict = {"on": True, "why": why, "since": time.time(), "hours": hours}
    # Порядок важен: экраны гасим последними. Если что-то не выйдет, человек ещё увидит, что
    # именно, — а гашение экрана посреди списка превращает любую беду в тёмный экран без слов.
    if opts.get("pause_players", True):
        out["paused"] = _players("pause", _playing())
    if opts.get("mute", True):
        out["muted"] = _mute(True)
    out["guard"] = _keep_awake(why)
    out["watchdog"] = _watchdog_on(hours)
    if opts.get("screens_off", True):
        out["screens_off"] = _screens(False)
    try:
        STATE.write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    except OSError as e:
        return {"ok": False, "error": str(e)}
    out["ok"] = True
    return out


def off(resume: bool = True) -> dict:
    """Вернуть всё как было: экраны, звук, музыку, засыпание, сторожа.

    Делается до конца даже без файла состояния: после перезагрузки или сорванной работы включать
    экран всё равно надо, а лишний `kscreen-doctor --dpms=on` не вредит никому.

    `resume=False` — вернуть всё, кроме музыки. Так режим кончает сторож: он сработал по сроку, а
    не потому, что человек пришёл, и включать музыку в пустой комнате незачем.
    """
    was = state()
    out: dict = {"ok": True, "on": False, "screens_on": _screens(True)}
    _watchdog_off()
    pid = int(was.get("guard") or 0)
    if pid:
        try:
            os.kill(pid, 15)
        except (OSError, ProcessLookupError):
            pass
    if was.get("muted"):
        out["unmuted"] = _mute(False)
    if was.get("paused") and resume:
        # Снимаем с паузы ровно тех, кого сами остановили: включать всё, что нашлось, значит
        # устроить человеку утренний концерт из того, что он сам выключил вечером.
        out["resumed"] = _players("play", list(was["paused"]))
    STATE.unlink(missing_ok=True)
    return out


def status() -> dict:
    was = state()
    pid = int(was.get("guard") or 0)
    left = 0.0
    if was.get("on") and was.get("since") and was.get("hours"):
        left = max(0.0, float(was["since"]) + float(was["hours"]) * 3600 - time.time())
    return {"ok": True, "on": bool(was.get("on")), "why": was.get("why", ""),
            "guard_alive": bool(pid) and Path(f"/proc/{pid}").exists(),
            "paused": was.get("paused", []),
            "hours_left": round(left / 3600, 2),
            "config": _opts() or None}
