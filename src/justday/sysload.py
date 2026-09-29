"""Нагрузка машины: процессор, память, диск, сеть, температуры, видеокарта, тяжёлые программы.

Всё читается из ``/proc`` и ``/sys`` — ни psutil, ни других зависимостей. Причина не в экономии:
эти файлы есть на любом Linux и не требуют прав, а `psutil` пришлось бы тащить в набор «только
текст», где от него нет никакой пользы.

Числа здесь двух родов, и путать их нельзя. Память, температуры и диск — мгновенные: прочитал и
знаешь. Процессор и сеть — разностные: смысл имеет только «сколько прошло между двумя взглядами»,
поэтому :class:`Load` помнит прошлый взгляд. Один экземпляр живёт в демоне, и опрашивать его чаще
раза в секунду бессмысленно — цифры станут дёргаными, а не точными.

Зачем это ассистенту, а не только глазам. «Почему тормозит?» — вопрос, на который нельзя ответить
без этих чисел, и ассистент получает ровно те же, что видно на островке. Дальше он может предложить
закрыть то, что съедает машину; закрытие идёт обычным путём подтверждения, как и всякое действие,
которое трудно отменить.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from pathlib import Path

PROC = Path("/proc")
CLOCK = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
PAGE = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096

# Диски, которые не диски: разделы (sda1), устройства отображения, оптика, память на шине.
SKIP_DISK = re.compile(r"^(loop|ram|dm-|sr|zram|md)")
# Сетевые устройства, которые не сеть: локальная петля и виртуальные мосты контейнеров.
SKIP_NET = re.compile(r"^(lo|docker|br-|veth|virbr|tun|tap)")


def _read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""


# ───────────────────────────── мгновенное ─────────────────────────────


def memory() -> dict:
    """Память и подкачка в мегабайтах. `used` считаем как сама система: без кэша, который свободен."""
    info: dict[str, int] = {}
    for line in _read(PROC / "meminfo").splitlines():
        name, _, rest = line.partition(":")
        value = rest.strip().split(" ")[0]
        if value.isdigit():
            info[name] = int(value) // 1024
    total, avail = info.get("MemTotal", 0), info.get("MemAvailable", 0)
    swap_total, swap_free = info.get("SwapTotal", 0), info.get("SwapFree", 0)
    return {"total": total, "used": max(0, total - avail), "avail": avail,
            "percent": round((total - avail) / total * 100, 1) if total else 0.0,
            "swap_total": swap_total, "swap_used": max(0, swap_total - swap_free)}


def temperatures() -> list[dict]:
    """Датчики из hwmon: имя и градусы. Берём только те, у которых есть подпись."""
    out = []
    for chip in sorted(Path("/sys/class/hwmon").glob("hwmon*")):
        chip_name = _read(chip / "name").strip() or chip.name
        for sensor in sorted(chip.glob("temp*_input")):
            label = _read(sensor.with_name(sensor.name.replace("_input", "_label"))).strip()
            raw = _read(sensor).strip()
            if not raw.isdigit():
                continue
            out.append({"chip": chip_name, "label": label or sensor.stem,
                        "c": round(int(raw) / 1000, 1)})
    return out


def hot() -> dict | None:
    """Самый горячий важный датчик: процессор, если он есть, иначе просто самый горячий.

    Показывать на островке имеет смысл одно число, и это должна быть температура процессора, а не
    какого-нибудь контроллера накопителя, который всегда теплее."""
    sensors = temperatures()
    if not sensors:
        return None
    # Сначала общий датчик процессора, если он есть: «Package id 0» у Intel, «Tctl» у AMD. Отдельное
    # ядро бывает горячее пакета на несколько градусов, и показывать его — значит пугать зря.
    whole = [s for s in sensors if "package" in s["label"].lower() or "tctl" in s["label"].lower()]
    if whole:
        return max(whole, key=lambda s: s["c"])
    cpu = [s for s in sensors if s["chip"] in ("k10temp", "coretemp", "zenpower")]
    return max(cpu or sensors, key=lambda s: s["c"])


def disks() -> list[dict]:
    """Занятое место на смонтированных разделах — в гигабайтах."""
    out = []
    seen: set[str] = set()
    for line in _read(PROC / "self/mounts").splitlines():
        parts = line.split()
        if len(parts) < 3:
            continue
        device, where, kind = parts[0], parts[1].replace("\\040", " "), parts[2]
        if not device.startswith("/dev/") or kind in ("squashfs", "iso9660"):
            continue
        # Один диск — одна строка. На btrfs подтома `/` и `/home` живут на одном устройстве, и без
        # этого список показывал одно и то же место дважды.
        if device in seen:
            continue
        seen.add(device)
        try:
            st = os.statvfs(where)
        except OSError:
            continue
        total = st.f_blocks * st.f_frsize
        free = st.f_bavail * st.f_frsize
        if not total:
            continue
        out.append({"where": where, "total_gb": round(total / 1e9, 1),
                    "free_gb": round(free / 1e9, 1),
                    "percent": round((total - free) / total * 100, 1)})
    # По одному разделу на точку монтирования, самые большие первыми: /home важнее /boot/efi.
    out.sort(key=lambda d: -d["total_gb"])
    return out


def gpu() -> dict | None:
    """Видеокарта NVIDIA: загрузка, память, температура. Нет nvidia-smi — нет и ответа.

    AMD и Intel читаются иначе (amdgpu в hwmon, i915 в sysfs) и появятся отдельно: врать про
    «загрузку 0%» там, где её просто негде взять, хуже, чем не показывать строку вовсе."""
    if not shutil.which("nvidia-smi"):
        return None
    try:
        got = subprocess.run(
            ["nvidia-smi", "--query-gpu=name,utilization.gpu,memory.used,memory.total,temperature.gpu",
             "--format=csv,noheader,nounits"], capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    if got.returncode or not got.stdout.strip():
        return None
    parts = [p.strip() for p in got.stdout.strip().splitlines()[0].split(",")]
    if len(parts) < 5:
        return None
    def num(s: str) -> float:
        try:
            return float(s)
        except ValueError:
            return 0.0
    return {"name": parts[0].replace("NVIDIA ", ""), "percent": num(parts[1]),
            "mem_used": int(num(parts[2])), "mem_total": int(num(parts[3])), "c": num(parts[4])}


def uptime() -> float:
    raw = _read(PROC / "uptime").split(" ")
    try:
        return float(raw[0])
    except (ValueError, IndexError):
        return 0.0


def loadavg() -> list[float]:
    parts = _read(PROC / "loadavg").split(" ")
    try:
        return [float(p) for p in parts[:3]]
    except ValueError:
        return [0.0, 0.0, 0.0]


# ───────────────────────────── разностное ─────────────────────────────


class Load:
    """Взгляд на машину, помнящий предыдущий. Один на весь демон."""

    def __init__(self) -> None:
        self._cpu: dict[str, tuple[int, int]] = {}
        self._net: dict[str, tuple[int, int]] = {}
        self._io: dict[str, tuple[int, int]] = {}
        self._when = 0.0
        self._procs: dict[int, tuple[int, float]] = {}

    # ---- процессор

    def cpu(self) -> dict:
        """Загрузка процессора в процентах: всего и по ядрам.

        Считается по времени простоя: доля непростаивавшего времени между двумя взглядами. Первый
        взгляд сравнивать не с чем и честно отдаёт нули, а не выдумывает число."""
        total = 0.0
        cores: list[float] = []
        for line in _read(PROC / "stat").splitlines():
            if not line.startswith("cpu"):
                break
            parts = line.split()
            name, values = parts[0], [int(v) for v in parts[1:] if v.isdigit()]
            if len(values) < 5:
                continue
            busy = sum(values) - values[3] - (values[4] if len(values) > 4 else 0)
            whole = sum(values)
            was = self._cpu.get(name)
            self._cpu[name] = (busy, whole)
            share = 0.0
            if was and (d := whole - was[1]) > 0:
                share = round(max(0.0, min(100.0, (busy - was[0]) / d * 100)), 1)
            if name == "cpu":
                total = share
            else:
                cores.append(share)
        return {"percent": total, "cores": cores, "count": len(cores) or os.cpu_count() or 1}

    # ---- сеть и диск

    def net(self) -> dict:
        """Скорость сети в килобайтах в секунду, сложенная по настоящим устройствам."""
        now = time.monotonic()
        rx = tx = 0
        for line in _read(PROC / "net/dev").splitlines()[2:]:
            name, _, rest = line.partition(":")
            name = name.strip()
            if SKIP_NET.match(name):
                continue
            parts = rest.split()
            if len(parts) < 9:
                continue
            got, sent = int(parts[0]), int(parts[8])
            was = self._net.get(name)
            self._net[name] = (got, sent)
            if was and now > self._when:
                gap = now - self._when
                rx += max(0, got - was[0]) / gap
                tx += max(0, sent - was[1]) / gap
        speed = {"rx_kb": round(rx / 1024, 1), "tx_kb": round(tx / 1024, 1)}
        return speed

    def io(self) -> dict:
        """Чтение и запись на диски, мегабайты в секунду."""
        now = time.monotonic()
        read = write = 0.0
        for line in _read(PROC / "diskstats").splitlines():
            parts = line.split()
            if len(parts) < 10 or SKIP_DISK.match(parts[2]):
                continue
            name = parts[2]
            # Разделы пропускаем: их числа уже входят в числа самого диска.
            if name[-1].isdigit() and not name.startswith("nvme"):
                continue
            if re.match(r"^nvme\d+n\d+p\d+$", name):
                continue
            sectors_r, sectors_w = int(parts[5]), int(parts[9])
            was = self._io.get(name)
            self._io[name] = (sectors_r, sectors_w)
            if was and now > self._when:
                gap = now - self._when
                read += max(0, sectors_r - was[0]) * 512 / gap
                write += max(0, sectors_w - was[1]) * 512 / gap
        return {"read_mb": round(read / 1e6, 1), "write_mb": round(write / 1e6, 1)}

    # ---- тяжёлые программы

    def top(self, limit: int = 6) -> list[dict]:
        """Что съедает машину прямо сейчас: по процессору, с памятью рядом.

        Проценты процессора — тоже разностные, по времени между взглядами; делятся на число ядер,
        чтобы «100%» значило «вся машина», а не «одно ядро из шестнадцати»."""
        now = time.monotonic()
        cores = os.cpu_count() or 1
        rows = []
        fresh: dict[int, tuple[int, float]] = {}
        for entry in PROC.iterdir():
            if not entry.name.isdigit():
                continue
            pid = int(entry.name)
            stat = _read(entry / "stat")
            if not stat:
                continue
            # Имя в скобках может содержать пробелы и сами скобки: берём по последней.
            close = stat.rfind(")")
            if close < 0:
                continue
            name = stat[stat.find("(") + 1:close]
            parts = stat[close + 2:].split()
            if len(parts) < 22:
                continue
            try:
                ticks = int(parts[11]) + int(parts[12])       # utime + stime
                rss = int(parts[21]) * PAGE // (1024 * 1024)  # страницы → МБ
            except (ValueError, IndexError):
                continue
            fresh[pid] = (ticks, now)
            was = self._procs.get(pid)
            share = 0.0
            if was and (gap := now - was[1]) > 0.2:
                share = round(max(0.0, (ticks - was[0]) / CLOCK / gap / cores * 100), 1)
            rows.append({"pid": pid, "name": name, "cpu": share, "mem_mb": rss})
        self._procs = fresh
        rows.sort(key=lambda r: (-r["cpu"], -r["mem_mb"]))
        return rows[:limit]

    # ---- всё вместе

    def snapshot(self, *, procs: int = 6) -> dict:
        """Один полный взгляд — то, что уходит островку и ассистенту."""
        cpu = self.cpu()
        net, io = self.net(), self.io()
        self._when = time.monotonic()
        return {"at": time.time(), "cpu": cpu, "memory": memory(), "net": net, "io": io,
                "gpu": gpu(), "hot": hot(), "disks": disks()[:4], "load": loadavg(),
                "uptime": uptime(), "top": self.top(procs)}


def human_summary(snap: dict) -> str:
    """Одна строка для голоса и для журнала: «процессор 12%, память 9.4 из 31 ГБ, 48°»."""
    cpu = snap.get("cpu", {}).get("percent", 0)
    mem = snap.get("memory", {})
    parts = [f"процессор {cpu:.0f}%"]
    if mem.get("total"):
        parts.append(f"память {mem['used'] / 1024:.1f} из {mem['total'] / 1024:.0f} ГБ")
    if (g := snap.get("gpu")):
        parts.append(f"видеокарта {g['percent']:.0f}%")
    if (h := snap.get("hot")):
        parts.append(f"{h['c']:.0f}°")
    if (top := snap.get("top")) and top and top[0]["cpu"] > 15:
        parts.append(f"больше всех — {top[0]['name']} ({top[0]['cpu']:.0f}%)")
    return ", ".join(parts)


if __name__ == "__main__":   # python -m justday.sysload
    import json

    load = Load()
    load.snapshot()          # первый взгляд не с чем сравнивать
    time.sleep(1.0)
    got = load.snapshot()
    print(human_summary(got))
    print(json.dumps(got, ensure_ascii=False, indent=2)[:2200])
