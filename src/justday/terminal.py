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
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import config, dispatch, fallback, providers, shell

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
    provider = rung.model.split("/", 1)[0] if rung.model else ""
    if not provider or provider in shell.LOCAL:
        return True
    if provider in shell.logged_in():
        return True
    name = shell.KEYS.get(provider)
    if not name:
        return False
    # Ключ может лежать и в окружении, и в связке ключей: в окружение его кладёт `justday shell`,
    # а в связке он живёт всегда. Проверять только окружение значило бы объявить мёртвой ступень,
    # ключ к которой у человека есть.
    return bool(os.environ.get(name) or providers.secret_get(provider))


# Какое усилие какой задаче. «Который час» не стоит высокого: оно стоит времени и лимита, а
# ответ от него не меняется. А «разберись, почему док лагает» без высокого усилия кончается
# правдоподобной догадкой вместо разбора.
EFFORT = {dispatch.TINY: "low", dispatch.LIGHT: "low", dispatch.STRONG: "high"}


@dataclass
class Said:
    """Что вышло из одного хода: сказанное, цена и беда, если была."""

    text: str = ""
    limit: bool = False
    error: str = ""
    cost: float = 0.0
    session: str = ""
    tools: list[str] = field(default_factory=list)


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
    proc = await asyncio.create_subprocess_exec(*cmd, stdout=asyncio.subprocess.PIPE,
                                                stderr=asyncio.subprocess.PIPE, env=env)
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
    finally:
        if mute and proc.returncode is None:
            proc.kill()
    with contextlib.suppress(asyncio.TimeoutError):
        await asyncio.wait_for(proc.wait(), timeout=10)
    said = err.decode("utf-8", "replace")
    if mute:
        said += f"\nмолчит дольше {int(quiet_for)} секунд — похоже, сюда нечем войти"
    return lines, said


async def ask_claude(rung: Rung, text: str, session: str, cfg: dict, on_text, on_tool) -> Said:
    """Ход на верхней ступени — самой программой `claude`, её же сессией и её же правами."""
    cli = shutil.which("claude") or "claude"
    b = cfg.get("brain") or {}
    cmd = [cli, "-p", text, "--output-format", "stream-json", "--verbose"]
    if rung.model:
        cmd += ["--model", rung.model]
    if (effort := (cfg.get("terminal") or {}).get("effort") or ""):
        cmd += ["--effort", str(effort)]
    if (mode := b.get("permission_mode") or ""):
        cmd += ["--permission-mode", str(mode)]
    if (cfg.get("terminal") or {}).get("unattended"):
        # Человека рядом нет, спросить некого. «Некого» значит «нельзя», а не «можно»: всё, что
        # потребовало бы подтверждения, отклоняется и попадает в ответ словами. Разрешать опасное
        # за спящего человека мы не будем — он прочитает утром и решит сам.
        cmd += ["--permission-prompts", "none"]
    if session:
        cmd += ["--resume", session]
    got = Said(session=session)

    def line(raw: str) -> None:
        try:
            ev = json.loads(raw)
        except ValueError:
            return
        kind = ev.get("type")
        if kind == "system" and ev.get("subtype") == "init":
            got.session = str(ev.get("session_id") or got.session)
        elif kind == "assistant":
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

    _, err = await _run(cmd, {**os.environ, **_marks(cfg)}, line, _quiet_for(cfg))
    if err.strip() and not got.text:
        got.error = got.error or err.strip()[:400]
    got.limit = fallback.looks_like_limit(got.error + " " + err)
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
        if ev.get("type") == "text" and part.get("text"):
            got.text += part["text"]
            on_text(part["text"])
        elif ev.get("type") in ("tool", "tool_start") and part.get("tool"):
            got.tools.append(str(part["tool"]))
            on_tool(str(part["tool"]))

    _, err = await _run(cmd, {**shell.env(), **_marks(cfg)}, line, _quiet_for(cfg))
    if err.strip():
        got.error = err.strip()[:400]
    got.limit = fallback.looks_like_limit(got.error)
    return got


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
        # Сессия помнится по ступени лестницы, а не по модели: мелочь, взятую облегчённой моделью,
        # следующий вопрос должен продолжать, а не начинать заново.
        self.sessions: dict[str, str] = {}
        # Движки берутся из таблицы, чтобы проверять лестницу без запуска нейросетей: подменить
        # движок в тесте проще и честнее, чем подменять три разные программы.
        self.engines = engines or {CLAUDE: ask_claude, OPENCODE: ask_opencode}

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
        if not self.opts.get("auto", True):
            return rung, effort, "как задано"
        level, why = dispatch.level_for(task)
        effort = EFFORT.get(level, effort)
        light = str(self.opts.get("light_model") or "")
        if level != dispatch.STRONG and rung.engine == CLAUDE and light and rung.model != light:
            rung = Rung(CLAUDE, light)
        return rung, effort, why

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
        await self.climb(on_note)
        while True:
            seat = str(self.now)                 # сессия принадлежит ступени, а не модели
            rung, self.effort, self.why = self.shape(task)
            on_pick(rung, self.effort, self.why)
            turn = {**self.cfg, "terminal": {**self.opts, "effort": self.effort}}
            engine = self.engines[rung.engine]
            said = await engine(rung, text, self.sessions.get(seat, ""), turn, on_text, on_tool)
            self.spent += said.cost
            if said.session:
                self.sessions[seat] = said.session
            if not self.hopeless(said):
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


async def night(task: str, hours: float = 8.0, tell: bool = False, cfg: dict | None = None) -> int:
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

    guard = server.awake(f"ночная работа: {task[:60]}")
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
        if guard:
            with contextlib.suppress(ProcessLookupError, PermissionError):
                os.kill(guard, 15)
        lines += ["", f"**Кончено в {time.strftime('%H:%M')}.**"]
        if work.spent:
            lines.append(f"Потрачено ${work.spent:.4f}.")
        log.write_text("\n".join(lines) + "\n", encoding="utf-8")

    done = bool(said.text) and not said.error
    short = "Задача сделана." if done else "Задача не доделана: " + (said.error or "никто не ответил")
    print(f"\n{short}\nЖурнал: {log}")
    if tell:
        # Письмо, а не звонок: человек спит, и будить его сделанной работой незачем.
        from . import phone
        with contextlib.suppress(Exception):
            phone.reach(f"{short}\n\nЗадача: {task}\n\nЖурнал: {log}", subject="Ночная работа")
    return 0 if done else 1


def run(args: list[str] | None = None, *, over_night: bool = False, hours: float = 8.0,
        tell: bool = False) -> int:
    """`justday terminal`: окно, если есть куда рисовать, иначе одна задача строкой."""
    task = " ".join(args or []).strip()
    if over_night:
        if not task:
            print("Ночью нужна задача: justday terminal --night \"что сделать\"")
            return 1
        return asyncio.run(night(task, hours=hours, tell=tell))
    if task:
        return asyncio.run(plain(task))
    # Окно тянет за собой textual; ради одной задачи строкой тянуть его незачем.
    from .terminal_ui import main
    return main()
