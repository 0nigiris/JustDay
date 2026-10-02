"""Необязательные части окружения: что установлено, чего нет и как доставить.

Распознавание речи и нейросетевой голос весят гигабайты, и нужны они не всем: без микрофона
ассистенту нечего слушать, без наушников незачем говорить вслух, а без видеокарты NVIDIA
полтора гигабайта библиотек CUDA скачиваются впустую. Поэтому установщик спрашивает, что
ставить, а этот модуль знает, что в итоге лежит в окружении, и умеет доставить остальное.

    justday parts                 # что есть, чего нет, сколько это весит
    justday parts add speech      # доставить распознавание речи
    justday parts remove cuda     # освободить место
"""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path

from . import config


@dataclass(frozen=True)
class Part:
    name: str
    module: str          # по нему и проверяем: установлено ли на самом деле
    size: str
    what: str            # что появляется вместе с ней
    without: str         # как живётся без неё


PARTS: dict[str, Part] = {
    "speech": Part(
        "speech", "faster_whisper", "~550 МБ",
        "распознавание речи: говорить с ассистентом голосом, имя «Джарвис», диктовка, субтитры",
        "остаётся текстом — горячая клавиша и поле ввода",
    ),
    "voice": Part(
        "voice", "torch", "~750 МБ",
        "нейросетевой голос Silero — тот, которым ассистент отвечает по умолчанию",
        "говорит espeak-ng: разборчиво, но по-роботски",
    ),
    "shell": Part(
        "shell", "textual", "~10 МБ",
        "окно своей оболочки: `justday terminal` с лестницей движков, строкой состояния и вводом",
        "оболочка работает строкой: `justday terminal \"задача\"`",
    ),
    "cuda": Part(
        "cuda", "nvidia.cublas", "~2.2 ГБ",
        "распознавание речи на видеокарте NVIDIA — в несколько раз быстрее",
        "речь распознаётся на процессоре",
    ),
}


def have(name: str) -> bool:
    """Установлена ли часть. Проверка по модулю, а не по записи в настройках: только это и правда."""
    part = PARTS.get(name)
    if part is None:
        return False
    try:
        return importlib.util.find_spec(part.module) is not None
    except (ImportError, ValueError):
        return False


def installed() -> list[str]:
    return [name for name in PARTS if have(name)]


def gpu() -> bool:
    return bool(shutil.which("nvidia-smi"))


def suggested() -> list[str]:
    """Что имеет смысл поставить на этой машине: речь и голос, а CUDA — только с видеокартой NVIDIA."""
    return ["speech", "voice"] + (["cuda"] if gpu() else [])


def missing_note(name: str) -> str:
    """Одна строка для ответа пользователю, когда часть понадобилась, а её нет."""
    part = PARTS[name]
    return f"{part.what.split(':')[0]} не установлено ({part.size}). Доставить: justday parts add {name}"


def sync(add: tuple[str, ...] = (), drop: tuple[str, ...] = (), dry: bool = False, show: bool = False) -> tuple[bool, str]:
    """Пересобрать окружение с нужным набором частей. Возвращает (получилось, вывод или команда).

    show=True отдаёт вывод прямо в терминал: uv рисует свою шкалу, и видно, что скачивание идёт."""
    want = set(installed()) | set(add)
    want -= set(drop)
    unknown = (set(add) | set(drop)) - set(PARTS)
    if unknown:
        return False, f"неизвестная часть: {', '.join(sorted(unknown))}"
    uv = shutil.which("uv") or str(Path.home() / ".local/bin/uv")
    cmd = [uv, "sync", "--python", "3.12"]
    for name in PARTS:                       # порядок как в PARTS: предсказуемая команда в логах
        if name in want:
            cmd += ["--extra", name]
    if dry:
        return True, " ".join(cmd)
    if show:
        return subprocess.run(cmd, cwd=config.REPO_DIR).returncode == 0, ""
    p = subprocess.run(cmd, cwd=config.REPO_DIR, capture_output=True, text=True)
    return p.returncode == 0, (p.stderr or p.stdout).strip()[-800:]
