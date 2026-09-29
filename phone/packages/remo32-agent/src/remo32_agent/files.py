"""Файлы компьютера — на телефоне.

Зачем: фотография, документ, сохранённая картинка лежат на диске дома, а
нужны в руках — посмотреть самому или отправить другу. Без этого «доступ к
компьютеру с телефона» упирается в то, что посмотреть на нём можно всё,
кроме собственных файлов.

Что здесь есть и чего нет. Есть чтение: список папки, файл целиком,
миниатюра для картинок и видео. Записи нет вовсе — ни удаления, ни
переименования, ни загрузки. Телефон теряют, и пока это только чтение,
потерянный телефон означает «посмотрели фотографии», а не «стёрли архив».

Главное свойство — телефон не знает настоящих путей и не может их назвать.
Адрес выглядит как ``pictures/2026/лето.jpg``: первое слово — имя папки,
которую владелец открыл в конфигурации, остальное — путь внутри неё. Любой
адрес приводится к настоящему пути и проверяется на принадлежность корню
уже после разбора ссылок, поэтому ссылка, ведущая наружу, отказывает так же,
как ``../..``.
"""

from __future__ import annotations

import asyncio
import contextlib
import mimetypes
import os
import re
import shutil
import tempfile
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from remo32_core.errors import (
    ActionInvalidError,
    CapabilityUnavailableError,
    NotFoundError,
)
from remo32_core.log import get_logger
from remo32_core.models import FileEntry, FileListing, FileRoot

log = get_logger("agent.files")

# Расширения решают, чем показывать файл. Содержимое для этого не читаем:
# список папки должен рисоваться мгновенно, а угадывание по первым байтам —
# это чтение каждого файла в каталоге.
IMAGE = {".jpg", ".jpeg", ".png", ".gif", ".webp", ".avif", ".heic", ".heif",
         ".bmp", ".tif", ".tiff", ".svg", ".ico"}
VIDEO = {".mp4", ".mkv", ".webm", ".mov", ".avi", ".m4v", ".mpg", ".mpeg", ".wmv"}
AUDIO = {".mp3", ".flac", ".ogg", ".opus", ".m4a", ".wav", ".aac", ".wma"}
TEXT = {".txt", ".md", ".log", ".json", ".toml", ".yml", ".yaml", ".csv", ".ini",
        ".conf", ".py", ".sh", ".js", ".css", ".html", ".xml", ".qml", ".rs", ".c", ".h"}

SAFE_ID = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")

# Миниатюру делаем тем, что есть, и выбираем по результату: ImageMagick
# собран без heic чаще, чем хотелось бы, и тогда он запускается и падает.
THUMB_SIZE = 480
THUMB_TIMEOUT = 25.0
THUMB_LIMIT = 4 * 1024 * 1024


class RootSpec(BaseModel):
    """Папка в конфигурации: ``[[files.roots]]``.

    Имя в адресе можно не задавать — тогда оно выводится из имени папки.
    Задавать стоит, когда папку однажды переименуют: адрес, положенный на
    рабочий стол телефона, от переименования не должен разваливаться.
    """

    model_config = ConfigDict(extra="forbid")

    path: Path
    id: str | None = Field(None, description="Короткое имя в адресе: ``photos``")
    name: str | None = Field(None, max_length=60, description="Как назвать на экране")


@dataclass(frozen=True)
class Root:
    """Папка, открытая телефону. ``path`` уже приведён к настоящему пути."""

    id: str
    name: str
    path: Path


# Стандартные папки пользователя. Путь спрашиваем у XDG: человек мог увести
# «Изображения» на отдельный диск, и тогда угаданный ~/Pictures — пустая папка
# рядом с настоящей. Третье поле — куда смотреть, если XDG молчит; четвёртое —
# название на экране: сами папки называются по-английски, а читает их человек.
XDG_DEFAULTS: tuple[tuple[str, str, str, str], ...] = (
    ("pictures", "XDG_PICTURES_DIR", "Pictures", "Изображения"),
    ("downloads", "XDG_DOWNLOAD_DIR", "Downloads", "Загрузки"),
    ("documents", "XDG_DOCUMENTS_DIR", "Documents", "Документы"),
    ("videos", "XDG_VIDEOS_DIR", "Videos", "Видео"),
    ("music", "XDG_MUSIC_DIR", "Music", "Музыка"),
    ("desktop", "XDG_DESKTOP_DIR", "Desktop", "Рабочий стол"),
)


def _xdg_dirs() -> dict[str, Path]:
    """Что написано в ``~/.config/user-dirs.dirs``. Файла нет — пустой ответ."""
    config = Path(os.environ.get("XDG_CONFIG_HOME", "~/.config")).expanduser() / "user-dirs.dirs"
    found: dict[str, Path] = {}
    try:
        lines = config.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return found
    for line in lines:
        line = line.strip()
        if line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip().strip('"')
        if not value:
            continue
        found[key.strip()] = Path(value.replace("$HOME", str(Path.home()))).expanduser()
    return found


def default_roots() -> list[Root]:
    """Папки по умолчанию: те стандартные, которые на этой машине существуют."""
    xdg = _xdg_dirs()
    roots: list[Root] = []
    for rid, key, fallback, title in XDG_DEFAULTS:
        path = xdg.get(key) or Path.home() / fallback
        if not path.is_dir():
            continue
        with contextlib.suppress(OSError):
            roots.append(Root(rid, title, path.resolve()))
    return roots


def roots_from_config(items: Iterable[RootSpec]) -> list[Root]:
    """Папки из ``[[files.roots]]``. Несуществующие пропускаем с записью в журнал:
    из-за съёмного диска, которого сейчас нет, агент подниматься не перестанет."""
    roots: list[Root] = []
    seen: set[str] = set()
    for item in items:
        path = Path(str(item.path)).expanduser()
        rid = (item.id or _slug(path.name)).strip().lower()
        if not SAFE_ID.match(rid):
            raise ActionInvalidError(f"недопустимое имя папки: {rid!r}")
        if rid in seen:
            raise ActionInvalidError(f"папка {rid!r} описана дважды")
        seen.add(rid)
        if not path.is_dir():
            log.warning("папка из конфигурации не найдена", root=rid, path=str(path))
            continue
        roots.append(Root(rid, item.name or path.name, path.resolve()))
    return roots


def _slug(name: str) -> str:
    slug = re.sub(r"[^a-z0-9_-]+", "-", name.lower()).strip("-")
    return slug[:32] or "folder"


def kind_of(path: Path, *, is_dir: bool = False) -> str:
    if is_dir:
        return "dir"
    suffix = path.suffix.lower()
    if suffix in IMAGE:
        return "image"
    if suffix in VIDEO:
        return "video"
    if suffix in AUDIO:
        return "audio"
    if suffix == ".pdf":
        return "pdf"
    if suffix in TEXT:
        return "text"
    return "other"


def media_type(path: Path) -> str:
    guess, _ = mimetypes.guess_type(path.name)
    return guess or "application/octet-stream"


def _thumbable(kind: str) -> bool:
    if kind == "image":
        return bool(shutil.which("magick") or shutil.which("convert"))
    if kind == "video":
        return bool(shutil.which("ffmpegthumbnailer") or shutil.which("ffmpeg"))
    return False


class Browser:
    """Чтение разрешённых папок. Один экземпляр на агент."""

    def __init__(
        self,
        roots: list[Root],
        *,
        show_hidden: bool = False,
        max_entries: int = 2000,
        max_bytes: int = 2 * 1024 * 1024 * 1024,
    ) -> None:
        self.roots = roots
        self.show_hidden = show_hidden
        self.max_entries = max_entries
        self.max_bytes = max_bytes

    # ---------------------------------------------------------------- адреса

    def _root(self, rid: str) -> Root:
        for root in self.roots:
            if root.id == rid:
                return root
        raise NotFoundError(f"папка {rid!r} телефону не открыта")

    def resolve(self, address: str) -> tuple[Root, Path]:
        """Адрес с телефона — в настоящий путь. Отказ, если он ведёт наружу."""
        address = (address or "").strip().strip("/")
        if not address:
            raise ActionInvalidError("пустой адрес")
        if "\x00" in address:
            raise ActionInvalidError("недопустимый адрес")
        head, _, tail = address.partition("/")
        root = self._root(head)
        parts = [p for p in tail.split("/") if p]
        if any(p in (".", "..") for p in parts):
            raise ActionInvalidError("адрес не должен выходить за папку")
        target = root.path.joinpath(*parts)
        try:
            real = target.resolve(strict=True)
        except OSError as exc:
            raise NotFoundError(f"не найдено: {address}") from exc
        # Проверяем после разбора ссылок: ссылка наружу — это выход наружу,
        # чем бы она ни притворялась в имени.
        if real != root.path and not real.is_relative_to(root.path):
            log.warning("попытка выйти за папку", address=address, real=str(real))
            raise NotFoundError(f"не найдено: {address}")
        if not (real.is_dir() or real.is_file()):
            raise ActionInvalidError("это не файл и не папка")
        return root, real

    def address_of(self, root: Root, real: Path) -> str:
        rel = real.relative_to(root.path)
        return root.id if str(rel) == "." else f"{root.id}/{rel.as_posix()}"

    # ---------------------------------------------------------------- чтение

    def top(self) -> FileListing:
        """Самый верх: список открытых папок, без единого настоящего пути."""
        return FileListing(
            path="",
            name="Файлы",
            parent=None,
            roots=[FileRoot(id=r.id, name=r.name) for r in self.roots],
            entries=[
                FileEntry(path=r.id, name=r.name, dir=True, kind="dir") for r in self.roots
            ],
        )

    def listing(self, address: str) -> FileListing:
        if not (address or "").strip().strip("/"):
            return self.top()
        root, real = self.resolve(address)
        if real.is_file():
            raise ActionInvalidError("это файл, а не папка")
        here = self.address_of(root, real)
        entries: list[FileEntry] = []
        truncated = False
        try:
            with os.scandir(real) as it:
                for item in it:
                    if len(entries) >= self.max_entries:
                        truncated = True
                        break
                    if not self.show_hidden and item.name.startswith("."):
                        continue
                    entry = self._entry(root, here, item)
                    if entry is not None:
                        entries.append(entry)
        except PermissionError as exc:
            raise CapabilityUnavailableError(f"нет доступа к папке: {address}") from exc
        except OSError as exc:
            raise CapabilityUnavailableError(f"папку не прочитать: {exc}") from exc
        # Папки сверху, дальше по имени без учёта регистра: так же, как их
        # показывает любой файловый менеджер, и искать глазами привычно.
        entries.sort(key=lambda e: (not e.dir, e.name.lower()))
        parent = real.parent
        above = "" if real == root.path else self.address_of(root, parent)
        return FileListing(
            path=here,
            name=real.name or root.name,
            parent=above,
            entries=entries,
            truncated=truncated,
        )

    def _entry(self, root: Root, here: str, item: os.DirEntry[str]) -> FileEntry | None:
        try:
            is_dir = item.is_dir()
            # Битую ссылку и всё, что не файл и не папка (сокеты, устройства),
            # в списке не показываем: открыть это всё равно нельзя.
            if not is_dir and not item.is_file():
                return None
            # Ссылку наружу не показываем вовсе, хотя открыть её и так не дадут:
            # строка, которая есть в списке и не открывается, выглядит поломкой.
            # Проверяем только ссылки — их единицы, лишних обращений к диску нет.
            if item.is_symlink() and not Path(item.path).resolve().is_relative_to(root.path):
                return None
            stat = item.stat()
        except OSError:
            return None
        kind = kind_of(Path(item.name), is_dir=is_dir)
        return FileEntry(
            path=f"{here}/{item.name}",
            name=item.name,
            dir=is_dir,
            size=0 if is_dir else stat.st_size,
            modified=datetime.fromtimestamp(stat.st_mtime, tz=UTC),
            kind=kind,
            preview=not is_dir and _thumbable(kind),
        )

    def file(self, address: str) -> tuple[Path, str]:
        """Путь файла и его тип — дальше его отдаёт уже FastAPI, потоком."""
        _, real = self.resolve(address)
        if not real.is_file():
            raise ActionInvalidError("это папка, а не файл")
        size = real.stat().st_size
        if size > self.max_bytes:
            raise ActionInvalidError(
                f"файл больше предела: {size // 1024 // 1024} МБ, "
                f"разрешено {self.max_bytes // 1024 // 1024} МБ"
            )
        return real, media_type(real)


async def thumbnail(path: Path, kind: str, size: int = THUMB_SIZE) -> bytes:
    """Миниатюра в JPEG. Пробуем инструменты по очереди до непустого файла."""
    if kind == "video":
        tools: tuple[tuple[str, list[str]], ...] = (
            ("ffmpegthumbnailer", ["ffmpegthumbnailer", "-s", str(size), "-i", str(path), "-o"]),
            ("ffmpeg", ["ffmpeg", "-y", "-loglevel", "error", "-i", str(path),
                        "-frames:v", "1", "-vf", f"scale={size}:-2", "-f", "image2"]),
        )
    else:
        # Только первый кадр: [0] отсекает страницы многослойного tiff и gif,
        # иначе ImageMagick склеит из них полотно на сотни мегабайт.
        tools = (
            ("magick", ["magick", f"{path}[0]", "-auto-orient",
                        "-thumbnail", f"{size}x{size}>", "-quality", "82"]),
            ("convert", ["convert", f"{path}[0]", "-auto-orient",
                         "-thumbnail", f"{size}x{size}>", "-quality", "82"]),
        )
    fd, out = tempfile.mkstemp(prefix="remo32-thumb-", suffix=".jpg")
    os.close(fd)
    try:
        for name, argv in tools:
            if not shutil.which(name):
                continue
            try:
                proc = await asyncio.create_subprocess_exec(
                    *argv,
                    out,
                    stdout=asyncio.subprocess.DEVNULL,
                    stderr=asyncio.subprocess.PIPE,
                )
                _, err = await asyncio.wait_for(proc.communicate(), timeout=THUMB_TIMEOUT)
            except (TimeoutError, OSError) as exc:
                log.info("миниатюра не вышла", tool=name, error=str(exc))
                continue
            data = await asyncio.to_thread(_read_thumb, out)
            if proc.returncode == 0 and data:
                return data
            log.info(
                "миниатюра не вышла",
                tool=name,
                code=proc.returncode,
                error=err.decode(errors="replace")[:200],
            )
        raise CapabilityUnavailableError("миниатюру сделать нечем")
    finally:
        with contextlib.suppress(OSError):
            os.unlink(out)


def _read_thumb(path: str) -> bytes:
    if not os.path.exists(path) or not (size := os.path.getsize(path)):
        return b""
    if size > THUMB_LIMIT:
        return b""
    with open(path, "rb") as fh:
        return fh.read()
