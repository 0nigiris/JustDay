"""Терминальная сессия поверх tmux.

Почему tmux, а не голый PTY: телефон теряет связь постоянно — блокировка
экрана, переключение сети, метро. Голый PTY при обрыве убивает процесс
вместе с ``claude -c``. tmux держит сессию на машине, а мы лишь
подключаемся к ней; обрыв связи рвёт подключение, но не работу.

Один объект :class:`TerminalSession` = одно подключение к tmux-сессии.
Сама tmux-сессия переживает и подключение, и перезапуск агента.
"""

from __future__ import annotations

import asyncio
import contextlib
import fcntl
import os
import pty
import signal
import struct
import termios
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass

from remo32_core.log import get_logger

log = get_logger("agent.terminal")

READ_CHUNK = 65536


@dataclass(frozen=True, slots=True)
class TerminalConfig:
    session_name: str
    workdir: str | None = None
    shell: str | None = None
    cols: int = 80
    rows: int = 24
    scrollback_lines: int = 2000
    env: dict[str, str] | None = None


def build_attach_argv(cfg: TerminalConfig) -> list[str]:
    """Команда подключения.

    ``new-session -A`` означает «создай, если нет; подключись, если есть» —
    ровно то поведение, которого ждёт пользователь, нажимая «Терминал».
    """
    argv = [
        "tmux",
        "-u",  # принудительно UTF-8: иначе русские буквы и рамки ломаются
        "new-session",
        "-A",
        "-s",
        cfg.session_name,
    ]
    if cfg.workdir:
        argv += ["-c", cfg.workdir]
    if cfg.shell:
        argv.append(cfg.shell)
    return argv


class TerminalSession:
    """Подключение к tmux-сессии через псевдотерминал."""

    def __init__(self, cfg: TerminalConfig) -> None:
        self._cfg = cfg
        self._master_fd: int | None = None
        self._proc: asyncio.subprocess.Process | None = None
        self._closed = asyncio.Event()

    @property
    def session_name(self) -> str:
        return self._cfg.session_name

    @property
    def is_running(self) -> bool:
        return self._proc is not None and self._proc.returncode is None

    async def start(self) -> None:
        if self._proc is not None:
            raise RuntimeError("сессия уже запущена")

        master_fd, slave_fd = pty.openpty()
        _set_winsize(master_fd, self._cfg.rows, self._cfg.cols)

        env = {
            **os.environ,
            "TERM": "xterm-256color",
            "LANG": os.environ.get("LANG", "C.UTF-8"),
            **(self._cfg.env or {}),
        }
        argv = build_attach_argv(self._cfg)
        log.info("открывается терминальная сессия", session=self._cfg.session_name, argv=argv)

        try:
            self._proc = await asyncio.create_subprocess_exec(
                *argv,
                stdin=slave_fd,
                stdout=slave_fd,
                stderr=slave_fd,
                env=env,
                cwd=self._cfg.workdir,
                start_new_session=True,
            )
        finally:
            os.close(slave_fd)

        self._master_fd = master_fd
        os.set_blocking(master_fd, False)

    async def read_output(self) -> AsyncIterator[bytes]:
        """Асинхронный поток вывода терминала."""
        if self._master_fd is None:
            raise RuntimeError("сессия не запущена")

        loop = asyncio.get_running_loop()
        queue: asyncio.Queue[bytes | None] = asyncio.Queue(maxsize=256)
        fd = self._master_fd

        def on_readable() -> None:
            try:
                data = os.read(fd, READ_CHUNK)
            except BlockingIOError:
                return
            except OSError:
                # PTY закрылся — обычное завершение tmux.
                data = b""
            if not data:
                loop.remove_reader(fd)
                queue.put_nowait(None)
                return
            try:
                queue.put_nowait(data)
            except asyncio.QueueFull:
                # Клиент не успевает читать: лучше потерять кусок вывода,
                # чем заблокировать цикл событий агента.
                log.warning("очередь вывода терминала переполнена", session=self.session_name)

        loop.add_reader(fd, on_readable)
        try:
            while True:
                chunk = await queue.get()
                if chunk is None:
                    break
                yield chunk
        finally:
            with contextlib.suppress(ValueError, OSError):
                loop.remove_reader(fd)
            self._closed.set()

    def write(self, data: bytes) -> None:
        if self._master_fd is None:
            raise RuntimeError("сессия не запущена")
        try:
            os.write(self._master_fd, data)
        except (BrokenPipeError, OSError) as exc:
            log.warning("не удалось записать в терминал", error=str(exc))

    def resize(self, rows: int, cols: int) -> None:
        if self._master_fd is None:
            return
        _set_winsize(self._master_fd, rows, cols)

    async def close(self) -> None:
        """Закрывает ПОДКЛЮЧЕНИЕ, но не tmux-сессию.

        Процессы внутри tmux продолжают работать — в этом весь смысл.
        """
        proc, self._proc = self._proc, None
        fd, self._master_fd = self._master_fd, None

        if proc is not None and proc.returncode is None:
            with contextlib.suppress(ProcessLookupError, OSError):
                # SIGHUP отвязывает клиента tmux; сервер tmux остаётся жив.
                os.killpg(os.getpgid(proc.pid), signal.SIGHUP)
            with contextlib.suppress(TimeoutError, ProcessLookupError):
                await asyncio.wait_for(proc.wait(), timeout=5)
            if proc.returncode is None:
                with contextlib.suppress(ProcessLookupError, OSError):
                    os.killpg(os.getpgid(proc.pid), signal.SIGKILL)

        if fd is not None:
            with contextlib.suppress(OSError):
                os.close(fd)
        log.info("терминальное подключение закрыто", session=self._cfg.session_name)


def _set_winsize(fd: int, rows: int, cols: int) -> None:
    """Сообщает PTY размер окна, иначе программы рисуют на 80x24."""
    with contextlib.suppress(OSError):
        fcntl.ioctl(fd, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))


async def list_tmux_sessions(
    runner: Callable[[list[str]], object] | None = None,
) -> list[str]:
    """Имена существующих tmux-сессий. Пустой список, если tmux не запущен."""
    proc = await asyncio.create_subprocess_exec(
        "tmux",
        "list-sessions",
        "-F",
        "#{session_name}",
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.DEVNULL,
    )
    out, _ = await proc.communicate()
    if proc.returncode != 0:
        return []
    return [line for line in out.decode().splitlines() if line]
