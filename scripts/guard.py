#!/usr/bin/env python3
"""Сторож: первое же физическое касание мыши или клавиатуры — фото с вебкамеры и замок экрана.

Зачем: он уходит, оставив экран включённым (чтобы ассистент видел экран), а дверь в комнату
открыта. Запирать заранее нельзя — ассистент потеряет снимки экрана; значит, запирать в тот миг,
когда кто-то тронет компьютер, и запомнить его лицо.

Слушаются только устройства с физическим USB-адресом (phys начинается с «usb-»): виртуальные
(ydotool, gsr-ui) нажимают сами программы, и от них замок срабатывал бы впустую. Хватает прав
пользователя: logind выдаёт ACL на клавиатуру и мышь сидящему за местом. Срабатывает один раз
и выходит — когда он вернётся и отопрёт экран, сторож уже не мешает.

    scripts/guard.py [--delay СЕК]          по умолчанию 15 с, чтобы успеть отойти
    systemd-run --user --unit=justday-storozh .venv/bin/python scripts/guard.py    в фоне; снять: systemctl --user stop justday-storozh
"""

import argparse
import glob
import os
import select
import struct
import subprocess
import time
from datetime import datetime
from pathlib import Path

EVENT = struct.Struct("llHHi")  # struct input_event на 64-битной машине
TOUCH = {1, 2, 3}  # EV_KEY, EV_REL, EV_ABS; EV_SYN и EV_MSC шлёт и сама клавиатура
OUT = Path(subprocess.run(["xdg-user-dir", "PICTURES"], capture_output=True, text=True).stdout.strip()
           or Path.home() / "Pictures") / "Сторож"


def devices() -> dict[int, str]:
    fds = {}
    for path in sorted(glob.glob("/dev/input/event*")):
        sys_dir = f"/sys/class/input/{os.path.basename(path)}/device"
        try:
            phys = Path(sys_dir, "phys").read_text().strip()
            name = Path(sys_dir, "name").read_text().strip()
            if phys.startswith("usb-"):
                fds[os.open(path, os.O_RDONLY | os.O_NONBLOCK)] = name
        except OSError:
            pass  # нет прав (планшет, кнопки корпуса) — не наше
    return fds


def seat_session() -> str:
    for line in subprocess.run(["loginctl", "list-sessions", "--no-legend"],
                               capture_output=True, text=True).stdout.splitlines():
        cols = line.split()
        if len(cols) > 3 and cols[2] == os.environ.get("USER", "oni") and cols[3].startswith("seat"):
            return cols[0]
    return ""


def alarm(who: str) -> None:
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    OUT.mkdir(parents=True, exist_ok=True)
    # Камера и замок одновременно: снимок занимает ~2 с, замок ждать не должен. Четыре кадра раз в
    # секунду: первый — лицо в момент касания, следующие — как он смотрит на замок. Первые кадры
    # камеры тёмные, пока не выставится экспозиция, поэтому 10 пропускаем.
    cam = subprocess.Popen(["ffmpeg", "-loglevel", "error", "-f", "v4l2", "-video_size", "1280x720",
                            "-i", "/dev/video0", "-vf", r"select=gte(n\,10),fps=1", "-frames:v", "4",
                            str(OUT / f"{stamp}_%d.jpg")])
    sid = seat_session()
    subprocess.run(["loginctl", "lock-session", *([sid] if sid else [])])
    cam.wait(timeout=30)
    with open(OUT / "журнал.txt", "a", encoding="utf-8") as log:
        log.write(f"{stamp}  тронули: {who}; экран заперт; фото {stamp}_1..4.jpg\n")
    # Его нет дома: фото должно дойти до телефона сразу, а не ждать, пока он вернётся к экрану.
    # Отправка — после замка и записи на диск: без сети фото всё равно останутся.
    try:
        from justday import telegram
        shots = sorted(OUT.glob(f"{stamp}_*.jpg"))
        for i, shot in enumerate(shots[:2]):
            telegram.photo(shot, f"Сторож: тронули {who}, экран заперт ({stamp})" if i == 0 else "")
    except Exception as e:  # сеть, токен, что угодно: замок уже сработал
        with open(OUT / "журнал.txt", "a", encoding="utf-8") as log:
            log.write(f"{stamp}  в телеграм не ушло: {e}\n")


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--delay", type=float, default=15)
    delay = ap.parse_args().delay
    fds = devices()
    if not fds:
        raise SystemExit("нет доступа ни к одной мыши или клавиатуре")
    print(f"слушаю: {', '.join(sorted(set(fds.values())))}; включаюсь через {delay:.0f} с", flush=True)
    armed_at = time.monotonic() + delay
    while True:
        ready, _, _ = select.select(list(fds), [], [])
        for fd in ready:
            data = os.read(fd, EVENT.size * 64)
            hit = any(EVENT.unpack_from(data, i)[2] in TOUCH for i in range(0, len(data), EVENT.size))
            if hit and time.monotonic() >= armed_at:
                alarm(fds[fd])
                print(f"сработал: {fds[fd]}; фото в {OUT}", flush=True)
                return


if __name__ == "__main__":
    main()
