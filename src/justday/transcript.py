"""Видео → текст → выжимка: он скидывает ролики с полезным, а смотреть их целиком некогда (п.24 плана 13 октября).

Всё местное и бесплатное: звук качает yt-dlp, текст пишет тот же faster-whisper, что слушает его голос,
выжимку — местная модель через Ollama. Нет Ollama — текст всё равно ложится на диск, выжимку можно
попросить потом у любой модели.
"""
from __future__ import annotations

import datetime as dt
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

from . import config

OUT = Path(__file__).resolve().parents[2] / "docs" / "видео"

# Инстаграм и прочие отдают ролик только после входа. Обходить вход мы не будем (ни чужих куки, ни
# «скачивалок»), поэтому эту беду надо узнать и сказать словами, а не вывалить трассировку yt-dlp.
LOGIN = re.compile(r"login required|log in|sign in|cookies|rate-limit reached|private", re.I)

SUMMARY_PROMPT = (
    "Ты читаешь расшифровку видео для владельца проекта JustDay — личного ассистента для Linux "
    "(голос, островок на экране, лестница нейросетей, Telegram-бот). Напиши по-русски коротко: "
    "1) о чём видео в трёх строках; 2) что из этого можно применить в JustDay — списком, только "
    "конкретное. Если применить нечего, так и скажи. Не выдумывай того, чего нет в тексте."
)


class NeedsLogin(RuntimeError):
    pass


def slug(title: str) -> str:
    """Имя файла из заголовка: буквы любого алфавита остаются, остальное — дефисы, не длиннее 60."""
    s = re.sub(r"[^\w]+", "-", title.lower()).strip("-_")
    return s[:60].rstrip("-_") or "видео"


def fetch_audio(source: str, workdir: Path) -> tuple[Path, str]:
    """Локальный файл отдаётся как есть; ссылка скачивается одной дорожкой звука. → (файл, заголовок)."""
    p = Path(source).expanduser()
    if p.exists():
        return p, p.stem
    if not shutil.which("yt-dlp"):
        raise RuntimeError("yt-dlp не установлен")
    r = subprocess.run(["yt-dlp", "--no-warnings", "--ignore-config", "--no-playlist", "-f", "bestaudio/best",
                        "-o", str(workdir / "%(title).80s.%(ext)s"), "--print", "after_move:filepath",
                        "--print", "title", source],
                       capture_output=True, text=True, timeout=900)
    if r.returncode != 0:
        if LOGIN.search(r.stderr):
            raise NeedsLogin("сайт отдаёт это видео только после входа — скачай файл сам и дай путь к нему")
        raise RuntimeError((r.stderr.strip().splitlines() or ["yt-dlp не скачал видео"])[-1])
    lines = [ln for ln in r.stdout.splitlines() if ln.strip()]
    return Path(lines[-1]), (lines[0] if len(lines) > 1 else Path(lines[-1]).stem)


def transcribe(audio: Path) -> str:
    """Весь файл целиком. Язык угадывает сам Whisper: полезные ролики бывают и по-английски."""
    from .stt import STT

    cfg = config.load()["stt"]
    segments = STT(cfg)._run(str(audio), language=None, beam_size=int(cfg.get("beam_size") or 5),
                             vad_filter=True, condition_on_previous_text=True)
    return "\n".join(s.text.strip() for s in segments if s.text.strip())


def summarize(text: str) -> str:
    from . import localllm

    if not localllm.available():
        return "_Местной модели нет — выжимку можно попросить у ассистента по этому файлу._"
    try:
        return localllm.chat(SUMMARY_PROMPT, text[:24000], max_tokens=700, timeout=300, keep_alive="1m")
    except Exception as e:
        return f"_Выжимка не получилась: {e}_"


def page(title: str, source: str, text: str, summary: str, day: dt.date) -> str:
    return (f"# {title}\n\nИсточник: {source}\nРасшифровано: {day.isoformat()}\n\n"
            f"## Выжимка\n\n{summary}\n\n## Текст\n\n{text or '_речи не нашлось_'}\n")


def run(source: str, *, out: Path = OUT, with_summary: bool = True) -> Path:
    with tempfile.TemporaryDirectory(prefix="justday-video-") as tmp:
        audio, title = fetch_audio(source, Path(tmp))
        text = transcribe(audio)
    summary = summarize(text) if with_summary and text else "_нет_"
    day = dt.date.today()
    out.mkdir(parents=True, exist_ok=True)
    path = out / f"{day.isoformat()}-{slug(title)}.md"
    path.write_text(page(title, source, text, summary, day), encoding="utf-8")
    return path
