"""Оболочка: один терминал, в котором задачу подхватывает тот, кто сейчас может.

Чего хотел человек. Один терминал. Он пишет задачу — за неё берётся Claude Code; кончился у него
лимит, за ту же задачу берётся следующий, и так вниз по лестнице: от лучшего к тому, что осталось.
Не «открой другое окно и расскажи всё заново», а то же окно и та же задача.

Почему оболочка, а не свой агент. Claude Code и OpenCode — это уже готовые циклы с инструментами,
правами, сессиями и сжатием. Переписывать их значит получить через месяц то же самое, но хуже.
Поэтому здесь нет ни одного своего инструмента: оболочка делает то, чего не делает ни один из них
по отдельности — держит их лестницей и переносит задачу с одного на другого.

Что оболочка умеет сверху: сменить модель и усилие посреди работы (`--model`, `--effort`),
попросить сжать разговор (`/compact` сообщением в ту же сессию) и перенести задачу вниз с
заметкой-передачей. Это ровно те четыре вещи, которых в самом Claude Code нет.

Чего здесь нарочно нет. Подписка Claude не уезжает в чужие руки: на верхней ступени запускается
сама программа `claude`, её же сессия, её же права. Токен из неё мы не достаём и ни одному другому
клиенту не отдаём — с февраля 2026 Anthropic разрешает вход по подписке только своим программам,
и обходить это мы не собираемся. Ступени ниже идут через OpenCode, где у человека свои ключи.
"""
from __future__ import annotations

import asyncio
import contextlib
import json
import os
import shutil
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import config, dispatch, fallback, shell

CLAUDE, OPENCODE = "claude", "opencode"

# Обрыв связи — не повод спускаться: внизу тот же самый оборванный интернет, и мы только потеряем
# место в разговоре. Всё остальное, из-за чего ступень не сказала ни слова, — повод: мёртвый вход,
# пропавшая модель, сломанная настройка. Человеку всё равно, почему верх молчит; ему нужно, чтобы
# задачу кто-нибудь взял.
BROKEN_NET = ("connection refused", "network is unreachable", "name or service not known",
              "temporary failure in name resolution", "timed out", "socket hang up", "enotfound")


@dataclass
class Rung:
    """Ступень лестницы: кем думать и какой моделью."""

    engine: str
    model: str = ""

    @property
    def label(self) -> str:
        if self.engine == CLAUDE:
            return f"Claude Code · {self.model or 'по умолчанию'}"
        return self.model or "OpenCode"

    def __str__(self) -> str:
        return f"{self.engine}:{self.model}" if self.model else self.engine


def parse_rung(line: str) -> Rung | None:
    """«claude:opus», «opencode:ollama/qwen3.5:9b» → ступень.

    Делим по первому двоеточию: в имени местной модели двоеточие тоже есть, и делить по последнему
    значило бы потерять её версию.
    """
    raw = str(line or "").strip()
    if not raw:
        return None
    engine, _, model = raw.partition(":")
    engine = engine.strip().lower()
    if engine not in (CLAUDE, OPENCODE):
        return None
    return Rung(engine, model.strip())


def ladder(cfg: dict | None = None) -> list[Rung]:
    cfg = cfg or config.load()
    rows = (cfg.get("terminal") or {}).get("ladder") or []
    out = [r for r in (parse_rung(str(x)) for x in rows) if r]
    return out or [Rung(CLAUDE, "")]


def reachable(rung: Rung) -> bool:
    """Есть ли чем войти на эту ступень.

    Ступень, куда войти нечем, отвечает обычной ошибкой, а ошибку лестница понимает как лимит — и
    спускается. Один мёртвый верх означал бы, что каждая задача начинается с провала. Поэтому
    недоступные ступени пропускаются молча, но об этом говорится один раз при запуске.
    """
    if rung.engine == CLAUDE:
        return bool(shutil.which("claude"))
    if not (shutil.which("opencode") or (Path.home() / ".opencode" / "bin" / "opencode").exists()):
        return False
    return shell.can_enter(rung.model.split("/", 1)[0] if rung.model else "")


# Какое усилие какой задаче — одна таблица на оболочку и на голосового Джарвиса (`dispatch`):
# «который час» не становится точнее от высокого усилия, а «разберись, почему док лагает» без
# него кончается правдоподобной догадкой вместо разбора.
EFFORT = dispatch.EFFORT


@dataclass
class Said:
    """Что вышло из одного хода: сказанное, цена и беда, если была."""

    text: str = ""
    limit: bool = False
    error: str = ""
    cost: float = 0.0
    session: str = ""
    tools: list[str] = field(default_factory=list)
    # Сколько места в разговоре занято после этого хода. Не «сколько стоило» (это `cost`), а
    # сколько уже лежит в окне: по этому числу решается, пора ли просить сжатия.
    used: int = 0


# Длиннее этого — рассказ про лимиты, а не лимит.
LIMIT_SAID = 400


def _limit_in(said: Said, err: str = "") -> None:
    """Понять, что ход кончился лимитом, — даже если об этом сказали обычной строкой ответа.

    Claude Code сообщает о кончившемся лимите не ошибкой: в потоке приходит обычный текст
    «You've hit your session limit · resets 2:30am». Мы смотрели только в поток ошибок — и
    принимали это за готовый ответ. Лестница при этом стояла на месте, хотя внизу её ждали живые
    ступени, и человек получал вместо работы слово «лимит». Его слова: «если бы я реально запустил
    тебя через этот терминал, ты бы мне просто послал нахуй и сказал лимит».
    """
    if fallback.looks_like_limit(f"{said.error} {err}"):
        said.limit = True
        return
    text = (said.text or "").strip()
    if text and len(text) <= LIMIT_SAID and fallback.looks_like_limit(text):
        # Сам текст и есть сообщение о лимите: переносим его в беду, чтобы он не уехал вниз
        # «тем, что успел сказать предыдущий», и не стал ответом человеку.
        said.limit, said.error, said.text = True, text, ""


def _marks(cfg: dict) -> dict[str, str]:
    """Чем движок узнаёт, что он запущен не сам по себе.

    Без этого модель внутри оболочки ведёт себя как в разговоре с человеком: ждёт ответа на
    вопрос, которого никто не услышит, и держит важное в голове вместо диска, хотя её могут
    сменить на следующей минуте. Правила объясняют, что делать; эти переменные говорят, где она.
    """
    night = "1" if (cfg.get("terminal") or {}).get("unattended") else "0"
    return {"JUSTDAY_SHELL": "terminal", "JUSTDAY_NIGHT": night}


def _quiet_for(cfg: dict) -> float:
    return float((cfg.get("terminal") or {}).get("first_word_seconds") or 90)


def taken(usage: dict) -> int:
    """Сколько места занимает разговор по одному ответу движка.

    Складываем всё, что лежало в окне на этот запрос: присланное, прочитанное из кэша, записанное
    в кэш и сказанное. Кэш считать обязательно — в нём лежит почти весь разговор, и без него
    место выглядит пустым там, где оно кончается.

    Числа из `result` для этого не годятся: там они сложены за все ходы разом (проверено — чтение
    кэша за два хода складывается в сумму), и выходит больше окна при полупустом разговоре.
    """
    keys = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens",
            "output_tokens")
    return sum(int(usage.get(k) or 0) for k in keys)


def _opencode_cli() -> str:
    return shutil.which("opencode") or str(Path.home() / ".opencode" / "bin" / "opencode")


async def _run(cmd: list[str], env: dict[str, str], on_line, quiet_for: float = 90.0) -> tuple[list[str], str]:
    """Запустить движок и разобрать его поток событий. Возвращает (строки JSON, что в stderr).

    `quiet_for` — сколько ждать самого первого события. Ступень с просроченным входом не отвечает
    отказом: она висит молча и бесконечно (проверено — три минуты без единого слова), и работа
    висит вместе с ней. Первое событие у живого движка приходит через миг, поэтому долгое молчание
    в начале — надёжный признак, что эта ступень не работает. Дальше ждём сколько надо: думать
    десять минут над настоящей задачей — нормально, и обрывать это по таймеру нельзя.
    """
    # limit: одна строка потока — это целое событие движка, а в нём бывает прочитанный файл или
    # снимок экрана. По умолчанию asyncio рвёт чтение на 64 КиБ («Separator is found, but chunk is
    # longer than limit») — и ночная работа умирала на первом же большом ответе инструмента.
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.PIPE, env=env,
                                                limit=64 * 1024 * 1024)
    lines: list[str] = []
    mute = False

    async def read_out() -> None:
        nonlocal mute
        assert proc.stdout
        while True:
            try:
                raw = await (asyncio.wait_for(proc.stdout.readline(), timeout=quiet_for) if not lines
                             else proc.stdout.readline())
            except TimeoutError:
                mute = True
                return
            if not raw:
                return
            line = raw.decode("utf-8", "replace").strip()
            if line:
                lines.append(line)
                on_line(line)

    err = b""

    async def read_err() -> None:
        nonlocal err
        assert proc.stderr
        err = await proc.stderr.read()

    try:
        await asyncio.gather(read_out(), read_err())
    except asyncio.CancelledError:
        if proc.returncode is None:
            proc.kill()
        await proc.wait()
        raise
    finally:
        if mute and proc.returncode is None:
            proc.kill()
    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(proc.wait(), timeout=10)
    said = err.decode("utf-8", "replace")
    if mute:
        said += f"\nмолчит дольше {int(quiet_for)} секунд — похоже, сюда нечем войти"
    return lines, said


async def _sdk_turn(rung: Rung, text: str, session: str, cfg: dict, take, approve, got: Said) -> Said:
    """Ход верхней ступени через Agent SDK: днём опасное спрашивает человека в окне.

    Подпроцесс `claude -p` не умеет спросить: без человека у него есть только «разрешить всё
    разрешённое» и «отклонить». Днём человек сидит перед окном, и отклонять за него «удали ветку»
    значит заставлять переписывать задачу. SDK зовёт `can_use_tool` — туда и ставим вопрос окну.
    Поток переводим в те же события, что даёт `claude -p`, чтобы разбор был один (`take`).
    """
    from claude_agent_sdk import (
        AssistantMessage,
        ClaudeAgentOptions,
        ClaudeSDKClient,
        PermissionResultAllow,
        PermissionResultDeny,
        ResultMessage,
        SystemMessage,
        TextBlock,
        ToolUseBlock,
    )

    async def can_use_tool(name, inp, ctx):
        from .brain import describe_tool
        if name == "AskUserQuestion":  # вопросов-карточек в окне нет: пусть спросит обычной репликой
            return PermissionResultDeny(message="Здесь нет карточек с вопросами: спроси обычным текстом.")
        desc = getattr(ctx, "title", None) or describe_tool(name, inp)
        if await approve(desc, getattr(ctx, "decision_reason", None) or ""):
            return PermissionResultAllow(updated_input=inp)
        return PermissionResultDeny(message="Человек отклонил это действие. Не повторяй его; "
                                            "предложи другой путь или спроси.")

    b = cfg.get("brain") or {}
    opts = ClaudeAgentOptions(
        cli_path=shutil.which("claude") or "claude",
        model=rung.model or None,
        effort=(cfg.get("terminal") or {}).get("effort") or None,
        permission_mode=b.get("permission_mode") or None,
        setting_sources=["user", "project", "local"],  # как у `claude -p`: те же правила и разрешения
        system_prompt={"type": "preset", "preset": "claude_code", "append": dispatch.role_for(rung.model)},
        env=_marks(cfg),
        can_use_tool=can_use_tool,
        resume=session or None,
        max_buffer_size=64 * 1024 * 1024,
    )
    try:
        async with ClaudeSDKClient(opts) as client:
            await client.query(text)
            async for msg in client.receive_response():
                if isinstance(msg, AssistantMessage):
                    blocks = []
                    for bl in msg.content:
                        if isinstance(bl, TextBlock):
                            blocks.append({"type": "text", "text": bl.text})
                        elif isinstance(bl, ToolUseBlock):
                            blocks.append({"type": "tool_use", "name": bl.name})
                    take({"type": "assistant", "message": {"usage": msg.usage or {}, "content": blocks}})
                elif isinstance(msg, ResultMessage):
                    take({"type": "result", "session_id": msg.session_id, "total_cost_usd": msg.total_cost_usd,
                          "is_error": msg.is_error, "result": msg.result})
                elif isinstance(msg, SystemMessage):
                    take({"type": "system", "subtype": msg.subtype, **(msg.data or {})})
    except Exception as e:  # лимит приходит исключением — отдаём лестнице так же, как ошибку подпроцесса
        got.error = got.error or str(e)[:400]
    _limit_in(got, got.error)
    return got


async def ask_claude(rung: Rung, text: str, session: str, cfg: dict, on_text, on_tool) -> Said:
    """Ход на верхней ступени — самой программой `claude`, её же сессией и её же правами."""
    cli = shutil.which("claude") or "claude"
    b = cfg.get("brain") or {}
    cmd = [cli, "-p", text, "--output-format", "stream-json", "--verbose"]
    if rung.model:
        cmd += ["--model", rung.model]
    if (effort := (cfg.get("terminal") or {}).get("effort") or ""):
        cmd += ["--effort", str(effort)]
    if role := dispatch.role_for(rung.model):
        cmd += ["--append-system-prompt", role]
    # Режим «в обход прав» не передаётся никогда, откуда бы он ни пришёл (config.toml, чужая правка):
    # снятая защита — не удобство, а снятая защита (AGENTS.md).
    if (mode := b.get("permission_mode") or "") and "bypass" not in str(mode).lower():
        cmd += ["--permission-mode", str(mode)]
    unattended = (cfg.get("terminal") or {}).get("unattended")
    if unattended:
        # Человека рядом нет, спросить некого. «Некого» значит «нельзя», а не «можно»: всё, что
        # потребовало бы подтверждения, отклоняется и попадает в ответ словами. Разрешать опасное
        # за спящего человека мы не будем — он прочитает утром и решит сам.
        cmd += ["--permission-prompts", "none"]
    if session:
        cmd += ["--resume", session]
    got = Said(session=session)
    approve = (cfg.get("terminal") or {}).get("approve")

    def take(ev: dict) -> None:
        kind = ev.get("type")
        if kind == "system" and ev.get("subtype") == "init":
            got.session = str(ev.get("session_id") or got.session)
        elif kind == "system" and ev.get("subtype") == "compact_boundary":
            # Claude Code сжал разговор сам, посреди хода. Наш счёт места после этого — вчерашняя
            # газета: считать его дальше значит просить сжатия у того, кто только что сжался.
            got.used = 0
        elif kind == "assistant":
            got.used = max(got.used, taken((ev.get("message") or {}).get("usage") or {}))
            for block in (ev.get("message") or {}).get("content") or []:
                if block.get("type") == "text" and block.get("text"):
                    got.text += block["text"]
                    on_text(block["text"])
                elif block.get("type") == "tool_use":
                    got.tools.append(str(block.get("name") or ""))
                    on_tool(str(block.get("name") or ""))
        elif kind == "result":
            got.session = str(ev.get("session_id") or got.session)
            got.cost = float(ev.get("total_cost_usd") or 0)
            if ev.get("is_error"):
                got.error = str(ev.get("result") or "ошибка без объяснения")
            elif not got.text:
                got.text = str(ev.get("result") or "")

    def line(raw: str) -> None:
        with contextlib.suppress(ValueError):
            take(json.loads(raw))

    if approve and not unattended:
        return await _sdk_turn(rung, text, session, cfg, take, approve, got)
    _, err = await _run(cmd, {**os.environ, **_marks(cfg)}, line, _quiet_for(cfg))
    if err.strip() and not got.text:
        got.error = got.error or err.strip()[:400]
    _limit_in(got, err)
    return got


async def ask_opencode(rung: Rung, text: str, session: str, cfg: dict, on_text, on_tool) -> Said:
    """Ход на ступени ниже — через OpenCode: там живут ключи человека и местные модели."""
    cli = _opencode_cli()
    cmd = [cli, "run", "--format", "json"]
    if rung.model:
        cmd += ["-m", rung.model]
    if session:
        cmd += ["-s", session]
    cmd.append(text)
    got = Said(session=session)

    def line(raw: str) -> None:
        try:
            ev = json.loads(raw)
        except ValueError:
            return
        got.session = str(ev.get("sessionID") or got.session)
        part = ev.get("part") or {}
        if tok := (part.get("tokens") or {}):
            # У OpenCode расход лежит отдельным полем в конце шага, а кэш — вложенным: сложить
            # надо так же, как у Claude Code, иначе разговор выглядит пустым до самой стены.
            cache = tok.get("cache") or {}
            got.used = max(got.used, sum(int(tok.get(k) or 0) for k in ("input", "output"))
                           + sum(int(cache.get(k) or 0) for k in ("read", "write")))
        if ev.get("type") == "text" and part.get("text"):
            got.text += part["text"]
            on_text(part["text"])
        elif ev.get("type") in ("tool", "tool_start") and part.get("tool"):
            got.tools.append(str(part["tool"]))
            on_tool(str(part["tool"]))

    _, err = await _run(cmd, {**shell.env(), **_marks(cfg)}, line, _quiet_for(cfg))
    if err.strip():
        got.error = err.strip()[:400]
    _limit_in(got, err)
    return got


async def squeeze_claude(rung: Rung, session: str, cfg: dict) -> tuple[bool, str]:
    """Попросить Claude Code сжать разговор. Возвращает (сжалось ли, сессия после сжатия).

    Сжатие просится тем же способом, которым его просит человек, — командой `/compact` в ту же
    сессию. В режиме печати она работает: в потоке приходит `compact_result: success`, номер
    сессии остаётся тем же (проверено живьём).
    """
    cli = shutil.which("claude") or "claude"
    cmd = [cli, "-p", "/compact", "--output-format", "stream-json", "--verbose"]
    if rung.model:
        cmd += ["--model", rung.model]
    if session:
        cmd += ["--resume", session]
    done = {"ok": False, "session": session}

    def line(raw: str) -> None:
        try:
            ev = json.loads(raw)
        except ValueError:
            return
        if ev.get("session_id"):
            done["session"] = str(ev["session_id"])
        if ev.get("type") == "system" and (ev.get("subtype") == "compact_boundary"
                                           or ev.get("compact_result") == "success"):
            done["ok"] = True

    # Ждём дольше обычного: сжатие — это целый ход модели по всему разговору.
    await _run(cmd, {**os.environ, **_marks(cfg)}, line, max(_quiet_for(cfg), 120.0))
    return bool(done["ok"]), str(done["session"])


async def squeeze_opencode(rung: Rung, session: str, cfg: dict) -> tuple[bool, str]:
    """То же у OpenCode — его собственной командой `compact`."""
    if not session:
        return False, session
    cmd = [_opencode_cli(), "run", "--format", "json", "--command", "compact", "-s", session]
    lines, err = await _run(cmd, {**shell.env(), **_marks(cfg)}, lambda _l: None,
                            max(_quiet_for(cfg), 120.0))
    return bool(lines) and not err.strip(), session


def handoff_note(task: str, was: Rung, said: str) -> str:
    """Чем начинается работа у пришедшего на смену.

    «Продолжай» — это не начало: он не видел ничего из того, что здесь было. Поэтому он получает
    задачу человека целиком, то немногое, что успел сказать предыдущий, и указание на журнал,
    где лежит всё остальное.
    """
    tail = (said or "").strip()
    tail = (tail[-700:] if len(tail) > 700 else tail) or "(ничего не успел сказать)"
    return "\n".join([
        f"[Передача. У {was.label} кончился лимит, задачу продолжаешь ты.]",
        "",
        f"Задача человека: {task}",
        "",
        f"Что успел сказать предыдущий:\n{tail}",
        "",
        "Прочитай ПЕРЕДАЧА.md в корне проекта — там что делалось до тебя, чем это проверено и чего",
        "делать нельзя. Веди этот файл дальше сам.",
    ])


HAND_UP, hands_up = dispatch.HAND_UP, dispatch.hands_up


def restart_note(task: str) -> str:
    """Чем начинается разговор, начатый заново: место кончилось, а сжать его не удалось."""
    return "\n".join([
        "[Разговор начат заново: место в прежнем кончилось, а сжать его не вышло.]",
        "",
        f"Задача человека: {task}",
        "",
        "Прочитай ПЕРЕДАЧА.md в корне проекта — там что делалось до тебя и чего делать нельзя.",
    ])


class Work:
    """Лестница в работе: чья очередь думать, где чья сессия и что делать при лимите."""

    def __init__(self, cfg: dict | None = None, rungs: list[Rung] | None = None,
                 engines: dict | None = None) -> None:
        self.cfg = cfg or config.load()
        # Лестницу из настроек просеиваем: ступень, куда нечем войти, только съест ход. Лестницу,
        # переданную прямо, не трогаем — её задал тот, кто уже знает, что в ней живое (проверки).
        if rungs is None:
            self.all = ladder(self.cfg)
            self.skipped = [r for r in self.all if not reachable(r)]
        else:
            self.all, self.skipped = list(rungs), []
        self.rungs = [r for r in self.all if r not in self.skipped] or list(self.all)
        self.step = 0
        self.spent = 0.0
        self.probed_at = 0.0           # когда в последний раз спрашивали верхнего
        self.wait_until = 0.0          # до каких пор ждать, если кончились все ступени (0 — не ждать)
        self.why = ""                  # чем решили усилие на последней задаче — для строки состояния
        self.effort = ""               # и какое оно вышло
        self.approve = None            # async (что, почему) -> bool: окно, которое спросит человека днём
        self.forced = ""               # модель, которую позвала слабая: на один ход её слово верх
        # Сессия помнится по ступени лестницы, а не по модели: мелочь, взятую облегчённой моделью,
        # следующий вопрос должен продолжать, а не начинать заново.
        self.sessions: dict[str, str] = {}
        self.used: dict[str, int] = {}     # сколько места занято в разговоре каждой ступени
        # Движки берутся из таблицы, чтобы проверять лестницу без запуска нейросетей: подменить
        # движок в тесте проще и честнее, чем подменять три разные программы.
        self.engines = engines or {CLAUDE: ask_claude, OPENCODE: ask_opencode}
        self.squeezers = {CLAUDE: squeeze_claude, OPENCODE: squeeze_opencode}

    @property
    def now(self) -> Rung:
        return self.rungs[min(self.step, len(self.rungs) - 1)]

    @property
    def opts(self) -> dict:
        return self.cfg.get("terminal") or {}

    # ───────────── чем брать эту задачу ─────────────

    def shape(self, task: str) -> tuple[Rung, str, str]:
        """Какой моделью и каким усилием брать эту задачу. Возвращает (ступень, усилие, чем решили).

        Лестницу это не меняет: ступень остаётся той же, меняется только то, чем на ней работать.
        Мелочь не стоит ни высокого усилия, ни самой сильной модели — а лимит у неё один на всё,
        и потраченный на «спасибо» лимит не вернётся к вечеру, когда понадобится разбор.
        """
        rung, effort = self.now, str(self.opts.get("effort") or "")
        if self.forced and rung.engine == CLAUDE:
            # Слабая модель сама позвала сильную — её слово важнее мнения судьи: она эту задачу
            # уже видела, а судья видел только первую строку.
            back = {m: lvl for lvl, m in self.models().items()}
            return Rung(CLAUDE, self.forced), dispatch.EFFORT.get(back.get(self.forced, ""), "high"), \
                "позвала слабая модель"
        if not self.opts.get("auto", True):
            return rung, effort, "как задано"
        # Судья видит задачу целиком, но судит её одним словом и сам работает на крошечной модели:
        # промпт на шесть тысяч знаков со списком работ он спокойно называет мелочью и сажает на
        # неё хайку. Длина — признак, в котором ошибиться нельзя: столько не пишут, чтобы спросить
        # время. Поэтому у большой задачи есть пол, ниже которого судью не слушаем.
        if len(task) >= 1200 or task.count("\n") >= 12:
            level = dispatch.BIG
            return (Rung(CLAUDE, m) if rung.engine == CLAUDE and (m := self.models().get(level, "")) else rung), \
                dispatch.EFFORT.get(level, effort), "большая задача"
        level, why = dispatch.level_for(task)
        effort = dispatch.EFFORT.get(level, effort)
        if rung.engine == CLAUDE and (model := self.models().get(level, "")):
            rung = Rung(CLAUDE, model)
        return rung, effort, why

    def models(self) -> dict[str, str]:
        """Какой моделью брать какой уровень. Старое `light_model` тоже понимаем — конфиг живой."""
        got = dict(self.opts.get("models") or {})
        if not got and (light := str(self.opts.get("light_model") or "")):
            got = {dispatch.TINY: light, dispatch.LIGHT: light}
        return {k: str(v) for k, v in got.items() if v}

    # ───────────── место в разговоре ─────────────

    def free(self, seat: str = "") -> float:
        """Сколько места в разговоре ещё свободно — долей от окна. 1.0 — пусто или считать нечем."""
        window = int(self.opts.get("context_window") or 0)
        used = int(self.used.get(seat or str(self.now), 0))
        if window <= 0 or used <= 0:
            return 1.0
        return max(0.0, 1.0 - used / window)

    async def tidy(self, on_note=None) -> str:
        """Освободить место, пока мы между задачами. Возвращает «», «сжато» или «заново».

        Почему между задачами, а не когда прижало. Стена «кончился контекст» приходит всегда
        посреди хода: на середине правки, после трёх прочитанных файлов. Сжатие в этот миг —
        это потерянная середина работы. Поэтому место проверяется перед задачей: тогда сжатие
        стоит одну паузу, а не один обрыв.
        """
        on_note = on_note or (lambda _t: None)
        seat = str(self.now)
        edge = float(self.opts.get("compact_at") or 0)
        if edge <= 0 or self.free(seat) > edge or not self.sessions.get(seat):
            return ""
        left = int(self.free(seat) * 100)
        on_note(f"Места в разговоре осталось {left}% — прошу сжать, пока не начали задачу.")
        try:
            ok, session = await self.squeezers[self.now.engine](
                self.now, self.sessions[seat], self.cfg)
        except Exception:          # не вышло сжать — не повод терять задачу
            ok, session = False, ""
        self.used[seat] = 0
        if ok:
            self.sessions[seat] = session
            return "сжато"
        # Сжать не удалось: сбрасываем разговор, но задачу отдаём с передачей — иначе следующий
        # ход начнётся с «продолжай» без того, что продолжать.
        self.sessions.pop(seat, None)
        on_note("Сжать не вышло — начинаю разговор заново, задача пойдёт с передачей.")
        return "заново"

    # ───────────── обратно наверх ─────────────

    async def alive(self, rung: Rung) -> bool:
        """Отвечает ли эта ступень прямо сейчас — одно слово в новом разговоре.

        Спрашиваем отдельно, а не переключаем рабочую сессию: переключиться, чтобы выяснить, что
        лимит ещё не вернулся, значит потерять место в работе ради любопытства.
        """
        quiet = {**self.cfg, "terminal": {**self.opts, "first_word_seconds": 30}}
        try:
            said = await self.engines[rung.engine](rung, "ок", "", quiet, lambda _t: None, lambda _t: None)
        except Exception:      # мёртвая ступень не должна ронять работу на живой
            return False
        return not self.hopeless(said)

    async def climb(self, on_note=None) -> bool:
        """Спросить верхних, не вернулся ли к ним лимит, и подняться к первому, кто ответил.

        Только между задачами. Он сказал это прямо: «он спрашивает у Claude Code, очухался или
        нет, и если нет — идёт дальше по лестнице вниз». Угадывать миг возвращения лимита нечем:
        внятно о нём не говорят, поэтому мы не гадаем, а спрашиваем — одним словом.
        """
        on_note = on_note or (lambda _t: None)
        if self.step == 0:
            return False
        every = max(1.0, float(self.opts.get("probe_minutes") or 15)) * 60
        if self.probed_at and time.monotonic() - self.probed_at < every:
            return False
        self.probed_at = time.monotonic()
        for i in range(self.step):
            rung = self.rungs[i]
            if await self.alive(rung):
                was = self.now
                self.step = i
                on_note(f"{rung.label} снова отвечает — вернулся к нему с {was.label}.")
                return True
        return False

    def down(self) -> bool:
        if self.step >= len(self.rungs) - 1:
            return False
        self.step += 1
        return True

    async def send(self, task: str, on_text=None, on_tool=None, on_note=None, on_pick=None) -> Said:
        """Отдать задачу тому, чья очередь, и спускаться, пока кто-нибудь её не возьмёт.

        `on_pick` зовётся, когда выбрано, чем брать этот ход: говорить «думает Opus», а потом
        думать Sonnet — хуже, чем не говорить ничего.
        """
        on_text = on_text or (lambda _t: None)
        on_tool = on_tool or (lambda _t: None)
        on_note = on_note or (lambda _t: None)
        on_pick = on_pick or (lambda _r, _e, _w: None)
        text = task
        self.forced = ""
        await self.climb(on_note)
        if await self.tidy(on_note) == "заново":
            text = restart_note(task)
        while True:
            seat = str(self.now)                 # сессия принадлежит ступени, а не модели
            rung, self.effort, self.why = self.shape(task)
            on_pick(rung, self.effort, self.why)
            turn = {**self.cfg, "terminal": {**self.opts, "effort": self.effort, "approve": self.approve}}
            engine = self.engines[rung.engine]
            ask = text
            if not self.forced and self.opts.get("hand_up", True) and rung.engine == CLAUDE \
                    and rung.model and rung.model == self.models().get(dispatch.LIGHT, ""):
                ask += HAND_UP
            said = await engine(rung, ask, self.sessions.get(seat, ""), turn, on_text, on_tool)
            self.spent += said.cost
            if said.session:
                self.sessions[seat] = said.session
            if said.used:
                self.used[seat] = said.used
            if not self.hopeless(said):
                if not self.forced and (want := hands_up(said.text)) and want != rung.model:
                    self.forced = want
                    on_note(f"{rung.label}: это серьёзнее — беру {want}.")
                    continue
                return said
            was, why = rung, "кончился лимит" if said.limit else f"не ответила: {said.error[:120]}"
            if not self.down():
                # Кончились все. Днём это конец хода: человек рядом и сам решит, что делать.
                # Ночью — наоборот: лимит возвращается через часы, а человек спит, и бросить
                # задачу значит, что утром он найдёт её там же, где оставил.
                every = max(1.0, float(self.opts.get("probe_minutes") or 15)) * 60
                if time.monotonic() + every < self.wait_until:
                    on_note(f"{was.label} — {why}. Кончились все; жду {int(every / 60)} мин "
                            "и начинаю сверху заново.")
                    await asyncio.sleep(every)
                    self.step, self.probed_at = 0, 0.0
                    continue
                on_note(f"{was.label} — {why}. Спускаться больше некуда, жду.")
                return said
            on_note(f"{was.label} — {why}. Задачу продолжает {self.now.label}.")
            text = handoff_note(task, was, said.text)

    @staticmethod
    def hopeless(said: Said) -> bool:
        """Надо ли спускаться: взял ли ход кто-нибудь всерьёз."""
        if said.limit:
            return True
        if said.text or not said.error:
            return False
        low = said.error.lower()
        return not any(word in low for word in BROKEN_NET)


async def plain(task: str, cfg: dict | None = None) -> int:
    """Та же лестница без окна: одна задача, ответ в терминал. Этим же удобно проверять."""
    work = Work(cfg)
    if work.skipped:
        print("Пропускаю ступени без входа: " + ", ".join(r.label for r in work.skipped))

    def picked(rung: Rung, effort: str, why: str) -> None:
        tail = f" · усилие {effort} ({why})" if effort else ""
        print(f"Думает {rung.label}{tail}…\n", flush=True)

    said = await work.send(task, on_text=lambda t: print(t, end="", flush=True),
                           on_note=lambda t: print(f"\n— {t}\n"), on_pick=picked)
    print()
    if said.error and not said.text:
        print("Беда: " + said.error)
        return 1
    if work.spent:
        print(f"\n(потрачено ${work.spent:.4f})")
    return 0


NIGHT_DIR = config.STATE_DIR / "ночь"


def asks_back(text: str) -> bool:
    """Кончился ли ход вопросом к человеку.

    Смотрим последнюю непустую строку: вопрос, заданный посреди рассказа, — это рассуждение, а
    вопрос в конце — это ожидание ответа. Ночью ответа не будет.
    """
    lines = [ln.strip() for ln in str(text or "").splitlines() if ln.strip()]
    return bool(lines) and lines[-1].endswith("?")


async def night(task: str, hours: float = 8.0, tell: bool = False, cfg: dict | None = None,
                dark: bool = False) -> int:
    """Оставить задачу на ночь: работать, пока не сделается, и записать всё на диск.

    Чем ночь отличается от дня. Днём кончившийся лимит — конец хода: человек рядом и решит сам.
    Ночью бросать задачу нельзя — лимит возвращается через часы, и к утру она сделалась бы сама,
    если бы кто-то дождался. Поэтому: машине не давать заснуть, кончились все ступени — ждать и
    начинать сверху заново, всё сказанное писать в файл, потому что окно до утра не доживёт.

    Чего ночь **не** меняет: прав. Спросить человека некого, и «некого» значит «нельзя»: всё, что
    потребовало бы подтверждения, отклоняется и попадает в журнал словами. Разрешать опасное за
    спящего человека — не наша забота о его удобстве, а снятая с него защита.
    """
    from . import server

    cfg = cfg or config.load()
    opts = dict(cfg.get("terminal") or {})
    opts["unattended"] = True
    cfg = {**cfg, "terminal": opts}
    work = Work(cfg)
    work.wait_until = time.monotonic() + max(0.5, hours) * 3600

    NIGHT_DIR.mkdir(parents=True, exist_ok=True)
    log = NIGHT_DIR / (time.strftime("%Y-%m-%d_%H-%M") + ".md")
    started = time.strftime("%H:%M")
    lines = [f"# Ночная работа, начато в {started}", "", f"**Задача.** {task}", ""]

    def write(text: str, end: str = "") -> None:
        print(text, end=end, flush=True)
        lines.append(text)

    def note(text: str) -> None:
        write(f"\n— {text}\n", "\n")

    def picked(rung: Rung, effort: str, why: str) -> None:
        note(f"{rung.label}" + (f", усилие {effort} ({why})" if effort else ""))

    why = f"ночная работа: {task[:60]}"
    # `dark` — человек лёг спать: гасим экраны, ставим музыку на паузу, глушим звук и не даём
    # машине заснуть. Без него — только запрет на засыпание: он мог оставить работу и остаться
    # рядом, и гасить ему экран незачем. Сторожу даём час сверх срока работы: он должен вернуть
    # машину человеку, если её не вернул никто, но не отнимать её у работы, которая ещё идёт.
    guard, mode = 0, False
    if dark:
        got = server.on(why, hours=hours + 1)
        mode = bool(got.get("ok"))
        lines.append("Режим сервера: экраны погашу, когда человек отойдёт." if got.get("waiting")
                     else "Машина в режиме сервера: экраны погашены, звук заглушён." if mode
                     else "Режим сервера включить не удалось — работаю при свете.")
    if not mode:
        guard = server.awake(why)
    try:
        said = await work.send(task, on_text=lambda t: write(t), on_note=note, on_pick=picked,
                               on_tool=lambda name: write(f"\n· {name}\n", "\n"))
        # Ход может кончиться вопросом к человеку — а человек спит. Подтолкнуть пару раз стоит:
        # половина таких вопросов это «какой из двух путей», и выбрать можно самому. Бесконечно
        # толкать нельзя: если без человека правда нельзя, он должен найти это утром словами, а
        # не сто кругов одного и того же.
        for _ in range(int(opts.get("night_nudges", 2) or 0)):
            if not asks_back(said.text):
                break
            note("Это вопрос ко мне, а человек спит — говорю решать самому.")
            said = await work.send(
                "Человек спит, спросить его некого. Если выбор можно сделать самому — сделай его "
                "и доделай задачу, объяснив в конце, что выбрал и почему. Если без его решения "
                "правда нельзя — напиши одной строкой, что именно от него нужно, и остановись.",
                on_text=lambda t: write(t), on_note=note, on_pick=picked,
                on_tool=lambda name: write(f"\n· {name}\n", "\n"))
    finally:
        # Режим сервера нарочно не выключается по концу работы: она может кончиться в три часа
        # ночи, и зажигать человеку экраны с музыкой посреди сна — худшее, что можно сделать с
        # «включил и лёг спать». Машину вернёт либо он сам (`justday server off`), либо сторож.
        if guard:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.kill(guard, 15)
        lines += ["", f"**Кончено в {time.strftime('%H:%M')}.**"]
        if work.spent:
            lines.append(f"Потрачено ${work.spent:.4f}.")
        log.write_text("\n".join(lines) + "\n", encoding="utf-8")

    done = bool(said.text) and not said.error
    short = "Задача сделана." if done else "Задача не доделана: " + (said.error or "никто не ответил")
    back = "\nМашина осталась в режиме сервера; вернуть её: justday server off" if mode else ""
    print(f"\n{short}\nЖурнал: {log}{back}")
    if tell:
        # Письмо, а не звонок: человек спит, и будить его сделанной работой незачем.
        from . import phone
        with contextlib.suppress(Exception):
            phone.reach(f"{short}\n\nЗадача: {task}\n\nЖурнал: {log}", subject="Ночная работа")
    return 0 if done else 1


# Работа, которая должна дожить до утра, не может висеть на открытом окне терминала: он закроется
# вместе с сеансом, по случайному Ctrl-C или потому, что человек просто захлопнул окно, — и работа
# умрёт на полуслове. Поэтому ночная работа уезжает в отдельную службу systemd: у неё своя жизнь.
NIGHT_UNIT = "justday-night"


def nightly(task: str, hours: float = 8.0, tell: bool = True, dark: bool = True) -> int:
    """Отправить ночную работу в отдельную службу и вернуть человеку строку приглашения.

    Что он увидит: одну команду, после которой можно закрыть окно и лечь спать. Работа идёт в
    службе `justday-night`, журнал пишется на диск по ходу дела, утром приходит письмо.
    """
    cli = shutil.which("justday")
    if not shutil.which("systemd-run") or not cli:
        # Нет systemd — работаем прямо здесь. Хуже (закрытое окно убьёт работу), но лучше, чем
        # отказаться: сказать человеку «не могу» в ответ на «я спать» — не ответ.
        print("systemd-run недоступен — работаю прямо в этом окне, не закрывай его.")
        return asyncio.run(night(task, hours=hours, tell=tell, dark=dark))
    if nightly_status().get("running"):
        print("Ночная работа уже идёт. Посмотреть: justday night --status; "
              "остановить: justday night --stop")
        return 1
    cmd = ["systemd-run", "--user", "--collect", f"--unit={NIGHT_UNIT}",
           "--description=JustDay: ночная работа",
           # Работать надо там, откуда позвали: служба иначе начинает в домашней папке, и движок
           # ищет проект, стоя рядом с ним.
           f"--working-directory={Path.cwd()}",
           # Службе systemd достаётся окружение его менеджера, а не наше: без этих переменных
           # движок не найдёт ни программ в ~/.local/bin, ни экрана, ни связки ключей.
           *[f"--setenv={k}={os.environ[k]}" for k in
             ("PATH", "WAYLAND_DISPLAY", "DISPLAY", "DBUS_SESSION_BUS_ADDRESS", "XDG_CURRENT_DESKTOP",
              "LANG", "HOME", "SHELL") if os.environ.get(k)],
           cli, "terminal", "--night", "--hours", str(hours)]
    if tell:
        cmd.append("--tell")
    cmd.append(task)
    try:
        done = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
    except (OSError, subprocess.SubprocessError) as e:
        print(f"Не вышло отправить работу в службу: {e}")
        return 1
    if done.returncode != 0:
        print((done.stderr or done.stdout or "systemd-run отказался").strip()[:400])
        return 1
    from . import server
    mode = server.on(f"ночная работа: {task[:60]}", hours=hours + 1) if dark else {}
    print("Работа ушла в службу justday-night — окно можно закрывать.")
    if mode.get("waiting"):
        print("Режим сервера: засыпать не даю, экраны погашу и звук заглушу, когда отойдёшь.")
    elif mode.get("ok"):
        print("Машина в режиме сервера: экраны погашены, звук заглушён, засыпать не даю.")
    print(f"Журнал: {NIGHT_DIR}\nПосмотреть: justday night --status · остановить: justday night --stop")
    return 0


def nightly_status() -> dict:
    """Идёт ли ночная работа и где её журнал."""
    try:
        done = subprocess.run(["systemctl", "--user", "is-active", f"{NIGHT_UNIT}.service"],
                              capture_output=True, text=True, timeout=10)
        running = done.stdout.strip() == "active"
    except (OSError, subprocess.SubprocessError):
        running = False
    logs = sorted(NIGHT_DIR.glob("*.md")) if NIGHT_DIR.exists() else []
    from . import server
    return {"ok": True, "running": running, "log": str(logs[-1]) if logs else "",
            "server_mode": server.status()}


def nightly_stop() -> dict:
    """Остановить ночную работу и вернуть человеку машину.

    Служба гаснет от сигнала, а сигнал не даёт ей ничего вернуть за собой, — поэтому режим
    сервера выключаем здесь сами. Иначе «останови» оставляло бы тёмный экран и глухой звук.
    """
    from . import server
    try:
        subprocess.run(["systemctl", "--user", "stop", f"{NIGHT_UNIT}.service"],
                       capture_output=True, timeout=20)
    except (OSError, subprocess.SubprocessError):
        pass
    return {"ok": True, "stopped": True, "server": server.off()}


def run(args: list[str] | None = None, *, over_night: bool = False, hours: float = 8.0,
        tell: bool = False, dark: bool = False) -> int:
    """`justday terminal`: окно, если есть куда рисовать, иначе одна задача строкой.

    Большую задачу в одну строку командной строки не напишешь: переводы строк съедает оболочка,
    кавычки внутри ломают слово целиком. Поэтому задачу можно подать файлом (`@путь`) или через
    трубу (`cat задача.md | justday terminal --night`) — это единственный способ отдать
    на ночь промпт на сто строк, не надеясь на вставку в чужом терминале.
    """
    import sys as _sys

    task = " ".join(args or []).strip()
    if task.startswith("@"):
        path = Path(task[1:]).expanduser()
        if not path.is_file():
            print(f"Нет такого файла с задачей: {path}")
            return 1
        task = path.read_text(encoding="utf-8").strip()
    elif not task and not _sys.stdin.isatty():
        task = _sys.stdin.read().strip()
    if over_night:
        if not task:
            print("Ночью нужна задача: justday terminal --night \"что сделать\"")
            return 1
        return asyncio.run(night(task, hours=hours, tell=tell, dark=dark))
    if task:
        return asyncio.run(plain(task))
    # Окно тянет за собой textual; ради одной задачи строкой тянуть его незачем.
    from .terminal_ui import main
    return main()
