"""Исполнение внешних команд.

Весь агент запускает процессы ТОЛЬКО через этот модуль, и всегда списком
аргументов — ``shell=True`` в проекте не встречается ни разу.

Исполнитель спрятан за протоколом :class:`CommandRunner` по двум причинам:

1. тесты подставляют :class:`RecordingRunner` и проверяют, какая команда
   была бы запущена, ничего не запуская — именно так тестируются выключение
   и перезагрузка;
2. режим ``dry_run`` в конфигурации становится тривиальным.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from dataclasses import dataclass, field
from typing import Protocol

from remo32_core.log import get_logger

log = get_logger("agent.execution")

# Сколько вывода команды сохраняем. Больше в интерфейсе телефона всё равно
# не прочитать, а память агента беречь надо.
MAX_OUTPUT_CHARS = 8_000


@dataclass(slots=True)
class CommandResult:
    argv: list[str]
    exit_code: int | None
    stdout: str
    stderr: str
    timed_out: bool = False
    detached: bool = False
    truncated: bool = False

    @property
    def success(self) -> bool:
        # Отсоединённый процесс считается успешно запущенным: кода выхода
        # у него ещё нет и не будет, пока пользователь не закроет программу.
        if self.detached:
            return True
        return self.exit_code == 0 and not self.timed_out


class CommandRunner(Protocol):
    """Контракт исполнителя команд."""

    async def run(
        self,
        argv: list[str],
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout: float = 30.0,
        detach: bool = False,
    ) -> CommandResult: ...


def _truncate(text: str) -> tuple[str, bool]:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text, False
    return text[:MAX_OUTPUT_CHARS] + "\n… вывод обрезан …", True


class SubprocessRunner:
    """Настоящий исполнитель поверх ``asyncio.create_subprocess_exec``."""

    def __init__(self, *, inherit_env: bool = True) -> None:
        self._inherit_env = inherit_env

    def _build_env(self, extra: dict[str, str] | None) -> dict[str, str] | None:
        if not extra:
            return None if self._inherit_env else {}
        base = dict(os.environ) if self._inherit_env else {}
        base.update(extra)
        return base

    async def run(
        self,
        argv: list[str],
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout: float = 30.0,
        detach: bool = False,
    ) -> CommandResult:
        if not argv:
            raise ValueError("argv пуст")

        log.debug("запуск команды", argv=argv, cwd=cwd, detach=detach)
        try:
            proc = await asyncio.create_subprocess_exec(
                *argv,
                cwd=cwd,
                env=self._build_env(env),
                stdout=asyncio.subprocess.DEVNULL if detach else asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL if detach else asyncio.subprocess.PIPE,
                stdin=asyncio.subprocess.DEVNULL,
                # Своя группа процессов: убивая по таймауту, мы не заденем агента,
                # а отсоединённый GUI переживёт перезапуск службы.
                start_new_session=True,
            )
        except FileNotFoundError:
            return CommandResult(argv, None, "", f"программа не найдена: {argv[0]}")
        except PermissionError:
            return CommandResult(argv, None, "", f"нет прав на запуск: {argv[0]}")
        except OSError as exc:
            return CommandResult(argv, None, "", f"не удалось запустить: {exc}")

        if detach:
            # Намеренно не ждём: процесс живёт своей жизнью.
            return CommandResult(argv, None, "", "", detached=True)

        try:
            raw_out, raw_err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            _kill_process_group(proc)
            with contextlib.suppress(ProcessLookupError, TimeoutError):
                await asyncio.wait_for(proc.wait(), timeout=5)
            return CommandResult(argv, None, "", f"превышен таймаут {timeout} с", timed_out=True)

        stdout, t1 = _truncate((raw_out or b"").decode("utf-8", errors="replace"))
        stderr, t2 = _truncate((raw_err or b"").decode("utf-8", errors="replace"))
        return CommandResult(
            argv=argv,
            exit_code=proc.returncode,
            stdout=stdout,
            stderr=stderr,
            truncated=t1 or t2,
        )


def _kill_process_group(proc: asyncio.subprocess.Process) -> None:
    """Убивает всю группу: иначе дочерние процессы переживут таймаут."""
    if proc.returncode is not None:
        return
    try:
        os.killpg(os.getpgid(proc.pid), 9)
    except (ProcessLookupError, PermissionError, OSError):
        with contextlib.suppress(ProcessLookupError):
            proc.kill()


@dataclass(slots=True)
class RecordingRunner:
    """Исполнитель для тестов и режима ``dry_run``.

    Ничего не запускает. Записывает вызовы и отдаёт заранее заданные ответы —
    благодаря ему тест выключения ПК не выключает ПК.
    """

    default_exit_code: int = 0
    default_stdout: str = ""
    default_stderr: str = ""
    responses: dict[str, CommandResult] = field(default_factory=dict)
    calls: list[dict[str, object]] = field(default_factory=list)

    async def run(
        self,
        argv: list[str],
        *,
        cwd: str | None = None,
        env: dict[str, str] | None = None,
        timeout: float = 30.0,
        detach: bool = False,
    ) -> CommandResult:
        self.calls.append(
            {"argv": list(argv), "cwd": cwd, "env": env, "timeout": timeout, "detach": detach}
        )
        log.info("dry-run: команда НЕ запущена", argv=argv)
        canned = self.responses.get(argv[0]) if argv else None
        if canned is not None:
            return canned
        return CommandResult(
            argv=list(argv),
            exit_code=self.default_exit_code,
            stdout=self.default_stdout,
            stderr=self.default_stderr,
            detached=detach,
        )

    @property
    def last_argv(self) -> list[str] | None:
        return self.calls[-1]["argv"] if self.calls else None  # type: ignore[return-value]
