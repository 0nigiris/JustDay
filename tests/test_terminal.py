"""Один терминал, в котором задачу подхватывает тот, кто сейчас может.

Проверяется лестница, а не нейросети: движки здесь подменены. Беда, из-за которой всё это
написано, — «кончился лимит, и работа встала до вечера, потому что человек был в школе».
"""
from __future__ import annotations

import asyncio
import os
from pathlib import Path

import pytest

from justday import terminal

ROOT = Path(__file__).resolve().parent.parent


def rungs(*names):
    return [terminal.parse_rung(n) for n in names]


def engine(answers):
    """Движок-подделка: отдаёт заранее заготовленные ответы и запоминает, что ему сказали."""
    heard = []

    async def ask(rung, text, session, cfg, on_text, on_tool):
        heard.append((str(rung), text))
        said = answers.pop(0) if answers else terminal.Said(text="всё")
        on_text(said.text)
        return said

    ask.heard = heard
    return ask


def test_the_model_of_the_ladder_splits_on_the_first_colon() -> None:
    """В имени местной модели двоеточие тоже есть: `ollama/qwen3.5:9b` — это не движок «ollama»."""
    r = terminal.parse_rung("opencode:ollama/qwen3.5:9b")
    assert (r.engine, r.model) == ("opencode", "ollama/qwen3.5:9b")
    assert terminal.parse_rung("claude:opus").engine == "claude"
    assert terminal.parse_rung("мусор:модель") is None


def test_a_limit_moved_the_task_down_instead_of_stopping_the_work() -> None:
    """Кончился лимит — задача уходит вниз вместе с тем, что успели сказать, а не умирает.

    Раньше это значило «работа встала до вечера»: человек в школе, сказать оболочке «перейди на
    другую модель» некому.
    """
    top = engine([terminal.Said(text="начал, но ", limit=True)])
    low = engine([terminal.Said(text="доделал")])
    work = terminal.Work({"terminal": {}, "brain": {}},
                         rungs=rungs("claude:opus", "opencode:ollama/своя"),
                         engines={"claude": top, "opencode": low})
    notes = []

    said = asyncio.run(work.send("почини док", on_note=notes.append))

    assert said.text == "доделал"
    assert work.step == 1, "лестница не спустилась"
    assert notes and "кончился лимит" in notes[0]
    # Пришедшему на смену отдали задачу целиком, а не слово «продолжай».
    handed = low.heard[0][1]
    assert "почини док" in handed
    assert "начал, но" in handed
    assert "ПЕРЕДАЧА.md" in handed


def test_a_dead_rung_was_blocking_the_task_because_it_was_not_a_limit() -> None:
    """Ступень с просроченным входом отвечает не «лимит», а «401» — и задача упиралась в неё.

    Человеку всё равно, почему верх молчит: ему нужно, чтобы задачу кто-нибудь взял. Поэтому вниз
    спускает любое молчание со ссылкой на беду, а не только лимит.
    """
    dead = engine([terminal.Said(error="Token refresh failed: 401")])
    alive = engine([terminal.Said(text="сделал")])
    pick = lambda r, t, s, c, ot, otool: (dead if "openai" in r.model else alive)(r, t, s, c, ot, otool)  # noqa: E731
    work = terminal.Work({"terminal": {}, "brain": {}},
                         rungs=rungs("opencode:openai/gpt-6-sol", "opencode:ollama/своя"),
                         engines={"opencode": pick})
    notes = []

    said = asyncio.run(work.send("собери проект", on_note=notes.append))

    assert said.text == "сделал"
    assert notes and "не ответила" in notes[0]


def test_a_broken_connection_does_not_walk_down_the_ladder() -> None:
    """Обрыв связи внизу тот же самый: спускаться — значит зря потерять место в разговоре."""
    assert terminal.Work.hopeless(terminal.Said(error="connection refused"))  is False
    assert terminal.Work.hopeless(terminal.Said(error="Error 429: usage limit reached", limit=True)) is True
    assert terminal.Work.hopeless(terminal.Said(text="ответил", error="шумело в stderr")) is False


def test_the_bottom_rung_says_it_has_nowhere_left_to_go() -> None:
    """Молчать, когда кончились все, нельзя: человек будет ждать ответа, которого не будет."""
    out = engine([terminal.Said(text="", limit=True)])
    work = terminal.Work({"terminal": {}, "brain": {}}, rungs=rungs("claude:opus"),
                         engines={"claude": out})
    notes = []
    asyncio.run(work.send("задача", on_note=notes.append))
    assert notes and "некуда" in notes[0]


@pytest.mark.parametrize("line,yes", [("claude:opus", True), ("opencode:ollama/своя", True)])
def test_a_local_rung_needs_no_login(line, yes, monkeypatch) -> None:
    """Местной модели вход не нужен — нужен запущенный ollama. Требовать от неё ключ значило бы
    выбросить единственную ступень, которая работает без интернета вовсе."""
    monkeypatch.setattr(terminal.shutil, "which", lambda name: "/usr/bin/" + name)
    assert terminal.reachable(terminal.parse_rung(line)) is yes


def test_the_window_opens_and_its_commands_do_what_they_say() -> None:
    """Окно должно открываться и слушаться с первого раза: в него человек будет писать задачи.

    Беда, которую этот тест ловит, — опечатка в разметке или в имени свойства: окно собирается,
    падает на первом же `/help`, и человек видит красный след вместо оболочки.
    """
    textual = pytest.importorskip("textual", reason="нет textual — окно не ставилось")
    assert textual
    from justday import terminal_ui

    async def go() -> tuple[int, str, str]:
        app = terminal_ui.Shell()
        async with app.run_test() as pilot:
            await pilot.pause()
            for cmd in ("/ladder", "/help", "/model sonnet", "/effort high", "/up", "/new", "/мусор"):
                app.command(cmd)
            await pilot.pause()
            return len(app.query_one("#log").lines), app.work.now.model, app.cfg["terminal"]["effort"]

    lines, model, effort = asyncio.run(go())
    assert lines > 5, "окно открылось пустым"
    assert model == "sonnet", "/model не сменил модель на этой ступени"
    assert effort == "high", "/effort не дошёл до движка"


def test_a_task_typed_into_the_window_reaches_the_ladder() -> None:
    """Задача из строки ввода должна дойти до движка и вернуться в окно ответом.

    Это самый частый путь во всей оболочке, и ломается он молча: ответ уходит в никуда, а человек
    смотрит на «думает» и ждёт.
    """
    pytest.importorskip("textual", reason="нет textual — окно не ставилось")
    from justday import terminal_ui

    async def go() -> str:
        app = terminal_ui.Shell()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.work.rungs = app.work.all = rungs("claude:opus")
            app.work.engines = {"claude": engine([terminal.Said(text="сделал")])}
            app.query_one("#ask").text = "почини док"
            await pilot.press("enter")
            for _ in range(40):                 # ход идёт своей задачей: ждём, пока он закончится
                await pilot.pause()
                if not app.busy:
                    break
            return "\n".join(str(line) for line in app.query_one("#log").lines)

    said = asyncio.run(go())
    assert "почини док" in said, "задача не попала в журнал окна"
    assert "сделал" in said, "ответ движка не дошёл до окна"


def test_a_trifle_was_taking_the_strongest_model_and_the_highest_effort(monkeypatch) -> None:
    """«Который час» уносил столько же лимита, сколько разбор беды, — и к вечеру его не оставалось.

    Лимит один на всё. Потраченный на «спасибо» к вечеру не вернётся, а именно вечером человек
    садится за настоящую работу. Поэтому усилие и модель выбираются по самой задаче, а лестница
    при этом не трогается: ступень остаётся той же.
    """
    models = {"tiny": "haiku", "light": "haiku", "strong": "sonnet", "big": "opus"}
    work = terminal.Work({"terminal": {"auto": True, "models": models}, "brain": {}},
                         rungs=rungs("claude:opus"), engines={})

    # Его правило словами: мелочь — хайку; надо программировать — сонет; большой проект — опус.
    for level, want in (("light", ("haiku", "low")), ("strong", ("sonnet", "medium")),
                        ("big", ("opus", "high"))):
        monkeypatch.setattr(terminal.dispatch, "level_for",
                            lambda text, lvl=level, **kw: (lvl, "местная модель"))
        rung, effort, _ = work.shape("задача")
        assert (rung.model, effort) == want, f"уровень {level} взят не тем"
    assert work.rungs[0].model == "opus", "выбор модели на один ход переписал саму лестницу"


def test_the_judge_guessing_light_used_to_mean_an_hour_of_work_by_the_wrong_model() -> None:
    """Судья видит одну строку и ошибается: «почини док» для него одно дело, а это разбор на час.

    Поэтому лёгкая модель может позвать сильную сама — одной строкой, одним дешёвым ходом.
    """
    models = {"light": "haiku", "strong": "sonnet", "big": "opus"}
    ask = engine([terminal.Said(text="НУЖНА: opus"), terminal.Said(text="разобрался и починил")])
    work = terminal.Work({"terminal": {"auto": False, "models": models, "hand_up": True},
                          "brain": {}}, rungs=rungs("claude:haiku"), engines={"claude": ask})

    notes = []
    said = asyncio.run(work.send("почини док", on_note=notes.append))

    assert said.text == "разобрался и починил", "задачу так и доделала слабая модель"
    assert terminal.HAND_UP.strip()[:10] in ask.heard[0][1], \
        "слабой не сказали, что она может передать задачу выше"
    assert ask.heard[1][0] == "claude:opus", "позвала opus, а задачу взял кто-то другой"
    assert terminal.HAND_UP.strip()[:10] not in ask.heard[1][1], \
        "сильной тоже предложили передать задачу выше — так можно ходить по кругу"
    assert any("серьёзнее" in n for n in notes), "передача выше прошла молча"
    assert not terminal.hands_up("Готово. Там, где НУЖНА: opus, я уже сделал сам."), \
        "рассказ про передачу принят за просьбу о передаче"


def test_nobody_was_asking_the_top_rung_whether_the_limit_came_back() -> None:
    """Спустившись, оболочка оставалась внизу до перезапуска — хотя лимит возвращается через часы.

    Он просил именно это: «он спрашивает у Claude Code, очухался или нет, и если нет — идёт
    дальше вниз». Угадывать миг возвращения нечем, поэтому не гадаем, а спрашиваем одним словом —
    и только между задачами, чтобы не забрать работу у того, кто её делает.
    """
    answers = {"claude:opus": terminal.Said(text="снова я"), "opencode:ollama/своя": terminal.Said(text="сделал")}

    async def ask(rung, text, session, cfg, on_text, on_tool):
        return answers[str(rung)]

    work = terminal.Work({"terminal": {"auto": False, "probe_minutes": 15}, "brain": {}},
                         rungs=rungs("claude:opus", "opencode:ollama/своя"),
                         engines={"claude": ask, "opencode": ask})
    work.step = 1                      # как будто уже спустились
    notes = []

    asyncio.run(work.send("продолжай", on_note=notes.append))

    assert work.step == 0, "верхний снова отвечает, а работа осталась внизу"
    assert notes and "снова отвечает" in notes[0]


def test_the_top_rung_was_asked_on_every_single_task(monkeypatch) -> None:
    """Спрашивать верхнего на каждой задаче — значит платить лимитом за один и тот же вопрос.

    Поэтому между вопросами проходит `probe_minutes`; сразу после спуска не спрашиваем вовсе.
    """
    asked = []

    async def ask(rung, text, session, cfg, on_text, on_tool):
        asked.append(str(rung))
        return terminal.Said(text="ответил")

    work = terminal.Work({"terminal": {"auto": False, "probe_minutes": 15}, "brain": {}},
                         rungs=rungs("claude:opus", "opencode:ollama/своя"),
                         engines={"claude": ask, "opencode": ask})
    work.step = 1
    asyncio.run(work.send("раз", on_note=lambda _n: None))   # первый раз спросить можно
    before = len(asked)
    work.step = 1
    asyncio.run(work.send("два", on_note=lambda _n: None))   # второй — ещё рано
    assert len(asked) == before + 1, "верхнего спросили второй раз подряд, не выждав срока"


def test_a_task_left_for_the_night_was_abandoned_when_every_rung_ran_out() -> None:
    """Кончились все ступени — задача умирала там же, где стояла, хотя лимит вернулся бы к утру.

    Днём это правильно: человек рядом и решит сам. Ночью — нет: он спит, лимит возвращается через
    часы, и утром он нашёл бы задачу нетронутой. Поэтому ночью ждём и начинаем сверху заново.
    """
    tries = []

    async def ask(rung, text, session, cfg, on_text, on_tool):
        tries.append(str(rung))
        # Первый обход — у всех лимит; на втором верхний уже отвечает.
        if len(tries) <= 2:
            return terminal.Said(limit=True)
        return terminal.Said(text="доделал к утру")

    sleeps = []

    async def no_sleep(seconds):
        sleeps.append(seconds)

    work = terminal.Work({"terminal": {"auto": False, "probe_minutes": 1}, "brain": {}},
                         rungs=rungs("claude:opus", "opencode:ollama/своя"),
                         engines={"claude": ask, "opencode": ask})
    work.wait_until = 10_000_000          # как будто впереди целая ночь
    notes = []

    async def go():
        import asyncio as aio
        real, aio.sleep = aio.sleep, no_sleep
        try:
            return await work.send("собери проект", on_note=notes.append)
        finally:
            aio.sleep = real

    said = asyncio.run(go())

    assert said.text == "доделал к утру", "задача не дождалась возвращения лимита"
    assert sleeps, "ждать и не подумали — значит снова упёрлись в тот же лимит"
    assert any("начинаю сверху заново" in n for n in notes)


def test_nobody_may_approve_the_dangerous_thing_for_a_sleeping_person() -> None:
    """Ночью опасное отклоняется, а не разрешается молча.

    Соблазн понятен: человек спит, подтвердить некому, а задача упирается. Но «спросить некого»
    значит «нельзя»: снятая со спящего защита — это не забота об удобстве. Claude Code получает
    `--permission-prompts none`, то есть всё, что спросило бы, отклоняется и попадает в журнал
    словами, а человек читает утром и решает сам.
    """
    src = (ROOT / "src" / "justday" / "terminal.py").read_text(encoding="utf-8")
    body = src.split("async def ask_claude", 1)[1].split("async def ask_opencode", 1)[0]
    assert '"--permission-prompts", "none"' in body
    assert "bypassPermissions" not in src, "ночью нельзя обходить права, их можно только отклонять"
    assert "dangerously" not in src.lower()


def test_the_window_can_be_left_for_the_night_and_gives_the_machine_back_after(monkeypatch) -> None:
    """«Включил и лёг спать» — из окна, одной командой, и машина возвращается человеку наутро.

    Две беды сразу. Первая: `/night` только запрещал машине спать — экраны горели всю ночь, а в
    пустой комнате играл фильм. Вторая: забыть отпустить сторожа значит оставить человеку машину,
    которая не засыпает никогда, и он будет искать причину неделю.
    """
    pytest.importorskip("textual", reason="нет textual — окно не ставилось")
    from justday import server, terminal_ui

    # Живую машину тест не трогает: гасить экраны на прогоне тестов — само по себе беда.
    done = []
    monkeypatch.setattr(server, "on", lambda why, hours=0.0: done.append(("on", hours)) or {"ok": True})
    monkeypatch.setattr(server, "off", lambda resume=True: done.append(("off", resume)) or {"ok": True})
    monkeypatch.setattr(server, "awake", lambda why="": 0)

    async def go() -> tuple[bool, bool, bool]:
        app = terminal_ui.Shell()
        async with app.run_test() as pilot:
            await pilot.pause()
            app.command("/night 8")
            await pilot.pause()
            dark, waits = app.dark, app.work.wait_until > 0
            app.command("/day")
            await pilot.pause()
            return dark, waits, app.dark

    dark, waits, after = asyncio.run(go())
    assert dark, "ушли спать, а экраны так и горят: это не «режим сервера»"
    assert waits, "ночью не ждём возвращения лимитов — значит это не ночь"
    assert not after, "утром машина осталась тёмной и глухой"
    assert ("off", True) in done, "машину никто не вернул человеку, да ещё и с музыкой на паузе"
    assert done[0][1] > 8, "сторож должен пережить саму работу, иначе он отнимет машину у неё же"


def test_the_night_work_used_to_die_with_the_closed_terminal_window(monkeypatch) -> None:
    """Работа на ночь висела на открытом окне: закрыл окно — и к утру ничего не сделано.

    Поэтому она уезжает в отдельную службу systemd: своя жизнь, свой журнал, своё «останови».
    """
    import subprocess

    seen = {}

    def fake_run(cmd, **kw):
        seen["cmd"] = list(cmd)
        return subprocess.CompletedProcess(cmd, 0, "", "")

    monkeypatch.setattr(terminal.shutil, "which", lambda name: f"/usr/bin/{name}")
    monkeypatch.setattr(terminal.subprocess, "run", fake_run)
    monkeypatch.setattr(terminal, "nightly_status", lambda: {"running": False})
    from justday import server
    monkeypatch.setattr(server, "on", lambda why, hours=0.0: {"ok": True})

    assert terminal.nightly("сделай всё из плана", hours=8.0) == 0
    cmd = seen["cmd"]
    assert cmd[0] == "systemd-run" and "--user" in cmd, "работа опять живёт в окне терминала"
    assert f"--unit={terminal.NIGHT_UNIT}" in cmd, "службу не найти, значит её не остановить"
    assert "--night" in cmd and cmd[-1] == "сделай всё из плана", "задача до службы не доехала"
    assert any(c.startswith("--setenv=PATH=") for c in cmd), \
        "без PATH служба не найдёт ни claude, ни opencode"


def test_the_morning_must_not_start_with_music_at_three_in_the_night(monkeypatch) -> None:
    """Работа кончилась в три ночи — и зажигала экраны с музыкой, пока человек спал.

    Поэтому режим сервера по концу работы не выключается сам: машину возвращает либо человек,
    либо сторож по сроку, и сторож музыку не включает.
    """
    from justday import server

    done = []
    monkeypatch.setattr(server, "on", lambda why, hours=0.0: {"ok": True})
    monkeypatch.setattr(server, "off", lambda resume=True: done.append(resume) or {"ok": True})
    monkeypatch.setattr(server, "awake", lambda why="": 0)
    cfg = {"terminal": {"ladder": ["claude:opus"], "night_nudges": 0}, "brain": {}}
    work = terminal.Work(cfg, rungs=rungs("claude:opus"),
                         engines={"claude": engine([terminal.Said(text="сделал")])})
    monkeypatch.setattr(terminal, "Work", lambda *a, **kw: work)
    monkeypatch.setattr(terminal, "NIGHT_DIR", Path("/tmp") / "justday-тест-ночь")

    asyncio.run(terminal.night("почини док", hours=0.5, cfg=cfg, dark=True))

    assert not done, "работа кончилась — и разбудила человека светом и музыкой"


def test_a_question_asked_at_night_used_to_stop_the_work_till_morning() -> None:
    """Ход кончился вопросом — а человек спит, и задача стояла до утра из-за «какой из двух путей».

    Вопрос в конце ответа — это ожидание; вопрос посреди рассуждения — нет. Поэтому смотрим
    последнюю непустую строку, и ночью пару раз говорим решать самому.
    """
    assert terminal.asks_back("Сделал. Ставить вторую кнопку?")
    assert terminal.asks_back("первая строка\nА это точно нужно?")
    assert not terminal.asks_back("Почему он лагал? Потому что док перерисовывался. Починил.")
    assert not terminal.asks_back("")


def test_the_long_work_used_to_hit_the_wall_of_a_full_conversation_mid_task() -> None:
    """«Кончился контекст» приходило всегда посреди дела — на середине правки, после трёх файлов.

    Место в разговоре теперь считается по тем же числам, что показывает сам движок, и сжатие
    просится **перед** задачей, а не когда прижало.
    """
    # Числа из `assistant`: присланное + кэш + сказанное. Кэш считать обязательно — в нём лежит
    # почти весь разговор, и без него окно выглядит пустым там, где оно кончается.
    assert terminal.taken({"input_tokens": 8, "cache_creation_input_tokens": 506,
                           "cache_read_input_tokens": 25271, "output_tokens": 1}) == 25786

    cfg = {"terminal": {"context_window": 1000, "compact_at": 0.2}, "brain": {}}
    work = terminal.Work(cfg, rungs=rungs("claude:opus"),
                         engines={"claude": engine([terminal.Said(text="сделал", used=850)])})
    squeezed = []

    async def squeeze(rung, session, cfg):
        squeezed.append(session)
        return True, "новая-сессия"

    work.squeezers = {"claude": squeeze}
    work.sessions["claude:opus"] = "старая-сессия"

    notes = []
    asyncio.run(work.send("почини док", on_note=notes.append))
    assert not squeezed, "сжались посреди хода, а не между задачами — потеряли середину работы"
    assert work.free() < 0.2, "место в разговоре считается не от окна модели"

    asyncio.run(work.send("а теперь трей", on_note=notes.append))
    assert squeezed == ["старая-сессия"], "места не осталось, а сжатия никто не попросил"
    assert work.sessions["claude:opus"] == "новая-сессия", "после сжатия разговор потерялся"
    assert any("сжать" in n for n in notes), "сжали молча: человек не поймёт, почему пауза"


def test_a_conversation_that_cannot_be_squeezed_must_not_lose_the_task() -> None:
    """Сжать не удалось — разговор начинается заново, но задача уходит с передачей, а не «продолжай»."""
    cfg = {"terminal": {"context_window": 1000, "compact_at": 0.2}, "brain": {}}
    ask = engine([terminal.Said(text="сделал", used=990), terminal.Said(text="и это")])
    work = terminal.Work(cfg, rungs=rungs("claude:opus"), engines={"claude": ask})

    async def squeeze(rung, session, cfg):
        return False, session

    work.squeezers = {"claude": squeeze}
    work.sessions["claude:opus"] = "разговор"
    asyncio.run(work.send("первая задача"))
    asyncio.run(work.send("вторая задача"))

    assert "claude:opus" not in work.sessions or not work.sessions["claude:opus"], \
        "сжать не вышло, а разговор остался тем же — следующий ход упрётся в ту же стену"
    assert "ПЕРЕДАЧА.md" in ask.heard[-1][1], "задачу отдали без передачи: продолжать нечего"


def test_the_counting_of_room_must_not_come_from_the_result_event() -> None:
    """В `result` числа сложены за все ходы разом: по ним разговор «кончался» на третьем вопросе.

    Проверено живьём: чтение кэша за два хода там складывается в сумму и переваливает окно, когда
    в разговоре ещё половина места.
    """
    said = asyncio.run(_claude_events([
        {"type": "assistant", "message": {"usage": {"input_tokens": 10,
                                                    "cache_read_input_tokens": 12413,
                                                    "cache_creation_input_tokens": 12858,
                                                    "output_tokens": 4},
                                          "content": [{"type": "text", "text": "ок"}]}},
        {"type": "result", "session_id": "с1", "usage": {"input_tokens": 18,
                                                         "cache_read_input_tokens": 37684,
                                                         "cache_creation_input_tokens": 13364,
                                                         "output_tokens": 440}},
    ]))
    assert said.used == 25285, "место считается по сумме всех ходов, а не по последнему запросу"


def test_claude_code_compacting_itself_mid_turn_must_reset_our_count() -> None:
    """Claude Code сжимается и сам: считать место по старому числу после этого — просить сжатия у сжатого."""
    said = asyncio.run(_claude_events([
        {"type": "assistant", "message": {"usage": {"input_tokens": 190000}, "content": []}},
        {"type": "system", "subtype": "compact_boundary", "session_id": "с1"},
        {"type": "assistant", "message": {"usage": {"input_tokens": 12000},
                                          "content": [{"type": "text", "text": "дальше"}]}},
    ]))
    assert said.used == 12000, "после своего сжатия движок считается полным"


async def _claude_events(events):
    """Прогнать поток событий `claude` через разбор, не запуская саму программу."""
    import json

    async def fake_run(cmd, env, on_line, quiet_for=90.0):
        for ev in events:
            on_line(json.dumps(ev))
        return [], ""

    was, terminal._run = terminal._run, fake_run
    try:
        return await terminal.ask_claude(terminal.Rung("claude", "opus"), "задача", "", {},
                                         lambda _t: None, lambda _t: None)
    finally:
        terminal._run = was


def test_a_limit_announced_as_plain_text_used_to_pass_for_a_finished_answer() -> None:
    """«Зашёл в терминал, попросил — лимит. Говорю: перейди на другую модель — лимит».

    Claude Code сообщает о кончившемся лимите не ошибкой, а обычной строкой ответа: «You've hit
    your session limit · resets 2:30am». Мы смотрели только в поток ошибок, поэтому лестница
    считала это готовым ответом и не спускалась — хотя внизу её ждали живые ступени.
    """
    said = terminal.Said(text="You've hit your session limit · resets 2:30am (Europe/Madrid)")
    terminal._limit_in(said)
    assert said.limit, "лимит в тексте опять принят за ответ"
    assert not said.text, "сообщение о лимите уехало бы вниз как «что успел сказать предыдущий»"
    assert terminal.Work.hopeless(said), "с таким ответом лестница так и стоит на месте"

    # А рассказ про лимиты — это рассказ: спускаться из-за него нельзя.
    story = terminal.Said(text="Лимит у подписки один на всё: " + "и его легко потратить. " * 20)
    terminal._limit_in(story)
    assert not story.limit, "ответ про лимиты принят за кончившийся лимит"


def test_the_whole_ladder_must_be_walked_when_the_subscription_is_spent() -> None:
    """Лимит подписки гасит сразу обе ступени Claude — задача должна дойти до того, кто живой."""
    opus_and_sonnet = engine([terminal.Said(text="You've hit your session limit · resets 2:30am"),
                              terminal.Said(text="You've hit your session limit · resets 2:30am")])

    async def claude(rung, text, session, cfg, on_text, on_tool):
        said = await opus_and_sonnet(rung, text, session, cfg, on_text, on_tool)
        terminal._limit_in(said)
        return said

    low = engine([terminal.Said(text="сделал сам")])
    work = terminal.Work({"terminal": {}, "brain": {}},
                         rungs=rungs("claude:opus", "claude:sonnet", "opencode:ollama/своя"),
                         engines={"claude": claude, "opencode": low})
    notes = []

    said = asyncio.run(work.send("сделай всё из плана", on_note=notes.append))

    assert said.text == "сделал сам", "работа встала на лимите вместо того, чтобы уйти вниз"
    assert work.step == 2, "спустились не до живой ступени"
    assert "ПЕРЕДАЧА.md" in low.heard[0][1], "задача ушла вниз без передачи"


async def test_by_day_a_dangerous_ask_goes_to_the_window_but_at_night_it_never_does() -> None:
    """Днём «удали ветку» упиралась в отказ подпроцесса: человек сидит рядом, а спросить его не могли.

    Ночью наоборот: спросить некого, и даже переданный вопрос окну не должен включать SDK —
    иначе ночью опасное решал бы тот, кого нет.
    """
    calls = []

    async def fake_sdk(*a):
        calls.append(a)
        return terminal.Said(text="ок")

    async def fake_run(cmd, env, on_line, quiet_for=90.0):
        return [], ""

    async def approve(desc, reason):
        return True

    was = terminal._sdk_turn, terminal._run
    terminal._sdk_turn, terminal._run = fake_sdk, fake_run
    try:
        rung = terminal.Rung("claude", "opus")
        await terminal.ask_claude(rung, "x", "", {"terminal": {"approve": approve}}, print, print)
        assert len(calls) == 1
        await terminal.ask_claude(rung, "x", "", {"terminal": {"approve": approve, "unattended": True}},
                                  print, print)
        assert len(calls) == 1
    finally:
        terminal._sdk_turn, terminal._run = was


def test_three_tasks_in_a_row_used_to_answer_wait_and_drop_two_of_them() -> None:
    """Написал три задачи подряд и ушёл — вернулся к одной: остальные получали «подожди» и пропадали."""
    pytest.importorskip("textual", reason="нет textual — окно не ставилось")
    from justday import terminal_ui

    async def go() -> tuple[list, list]:
        app = terminal_ui.Shell()
        heard: list = []

        async def slow(rung, text, session, cfg, on_text, on_tool):
            heard.append((str(rung), text))
            await asyncio.sleep(0.6)         # ход идёт, пока набираются остальные
            return terminal.Said(text="ок")

        eng = slow
        eng.heard = heard
        async with app.run_test() as pilot:
            await pilot.pause()
            app.work.rungs = app.work.all = rungs("claude:opus")
            app.work.engines = {"claude": eng}
            for t in ("раз", "два", "три"):
                app.query_one("#ask").text = t
                await pilot.press("enter")
            app.query_one("#ask").text = "/drop 2"   # убрать «три»
            await pilot.press("enter")
            queued = list(app.queue)
            for _ in range(200):
                await pilot.pause(0.05)
                if not app.busy and not app.queue:
                    break
        return queued, [h[1] for h in eng.heard]

    queued, heard = asyncio.run(go())
    assert queued == ["два"]
    # К задаче легкого хода дописана приписка (`HAND_UP`), поэтому сверяем по началу.
    got = [w for h in heard for w in ("раз", "два", "три") if h.startswith(w)]
    assert got == ["раз", "два"], heard


def test_a_big_tool_answer_used_to_kill_the_whole_night_work() -> None:
    """Ночная работа умирала на первом же большом ответе инструмента.

    Одна строка потока — это целое событие движка, и в нём бывает прочитанный файл. asyncio по
    умолчанию рвёт чтение на 64 КиБ («Separator is found, but chunk is longer than limit»), и
    работа валилась через четырнадцать секунд после запуска, не сделав ничего.
    """
    import inspect

    got = inspect.getsource(terminal._run)
    assert "limit=" in got, "предел строки не задан — длинный ответ снова уронит работу"

    async def go() -> list[str]:
        seen: list[str] = []
        lines, _ = await terminal._run(
            ["python3", "-c", "print('x' * (300 * 1024))"], dict(os.environ), seen.append, 30.0)
        return lines

    lines = asyncio.run(go())
    assert lines and len(lines[0]) > 200 * 1024, "длинная строка так и не прошла целиком"


def test_a_big_prompt_could_not_be_written_into_the_shell(monkeypatch) -> None:
    """Большую задачу в окно оболочки было не написать и не вставить.

    Поле ввода было однострочным (`Input`): всё после первого перевода строки отбрасывалось,
    а длинный текст уезжал за край. Человек вставлял промпт на двадцать строк, а уходила первая.
    Проверяем ровно это: многострочный текст доходит целиком и Enter его отправляет.
    """
    pytest.importorskip("textual", reason="нет textual — окно не ставилось")
    from justday import terminal_ui

    sent: list[str] = []
    monkeypatch.setattr(terminal_ui.Shell, "start", lambda self, text: sent.append(text))
    big = "Работай по плану.\n\nПРАВИЛА:\n- всё по-русски\n- тесты зелёные\n" + "- строка\n" * 20

    async def go() -> None:
        app = terminal_ui.Shell()
        async with app.run_test() as pilot:
            await pilot.pause()
            field = app.query_one("#ask", terminal_ui.Ask)
            field.text = big
            await pilot.press("enter")
            await pilot.pause()
            assert field.text == "", "после отправки поле не очистилось"

    asyncio.run(go())
    assert sent == [big.strip()], "многострочная задача дошла не целиком"


def test_alt_enter_breaks_the_line_instead_of_sending(monkeypatch) -> None:
    """Перенос строки руками: Enter отправляет, а абзац внутри задачи писать всё равно надо."""
    pytest.importorskip("textual", reason="нет textual — окно не ставилось")
    from justday import terminal_ui

    sent: list[str] = []
    monkeypatch.setattr(terminal_ui.Shell, "start", lambda self, text: sent.append(text))

    async def go() -> str:
        app = terminal_ui.Shell()
        async with app.run_test() as pilot:
            await pilot.pause()
            field = app.query_one("#ask", terminal_ui.Ask)
            field.text = "первая"
            await pilot.press("alt+enter")
            await pilot.pause()
            return field.text

    text = asyncio.run(go())
    assert "\n" in text, "Alt+Enter больше не переносит строку — абзац в задаче не написать"
    assert not sent, "Alt+Enter отправил задачу вместо переноса строки"


def test_a_pasted_prompt_was_torn_into_pieces_by_its_own_newlines(monkeypatch) -> None:
    """Вставленный промпт уходил кусками: каждый перевод строки внутри него нажимал «отправить».

    Так ведёт себя терминал без скобочной вставки — текст приходит обычными нажатиями.
    Человек не печатает быстрее десяти миллисекунд на знак, поэтому Enter впритык к предыдущей
    клавише — это вставка, а не отправка.
    """
    pytest.importorskip("textual", reason="нет textual — окно не ставилось")
    from justday import terminal_ui

    sent: list[str] = []
    monkeypatch.setattr(terminal_ui.Shell, "start", lambda self, text: sent.append(text))

    async def go() -> str:
        app = terminal_ui.Shell()
        async with app.run_test() as pilot:
            await pilot.pause()
            field = app.query_one("#ask", terminal_ui.Ask)
            from textual.events import Key
            # Вставка — это поток событий без пауз между ними. pilot.press ждёт после каждой
            # клавиши и человеческую скорость как раз и изображает, поэтому здесь события
            # кладутся в очередь подряд.
            for ch in "раз\nдва\n":
                field.post_message(Key("enter", None) if ch == "\n" else Key(ch, ch))
            await pilot.pause()
            await pilot.pause()
            return field.text

    text = asyncio.run(go())
    assert not sent, "вставка разорвалась: половина промпта ушла в работу как целая задача"
    assert text.count("\n") == 2, "переводы строк внутри вставки пропали"


def test_a_long_task_can_be_handed_over_as_a_file() -> None:
    """Промпт на сто строк в командную строку не влезает: переводы строк съедает оболочка.

    Единственный надёжный способ отдать такую задачу на ночь — файлом или трубой.
    """
    import inspect

    src = inspect.getsource(terminal.run)
    assert 'task.startswith("@")' in src, "задача файлом (@путь) пропала"
    assert "isatty" in src, "задача из трубы пропала"


def test_a_whole_page_of_work_was_handed_to_the_weakest_model() -> None:
    """Промпт на шесть тысяч знаков со списком работ судья назвал мелочью и посадил на хайку.

    Судья работает на крошечной модели и отвечает одним словом: для него «почини экран, док,
    диск и дальше по плану» — одна строка. Длина задачи — признак, в котором ошибиться нельзя:
    столько не пишут, чтобы спросить, который час.
    """
    models = {"light": "haiku", "strong": "sonnet", "big": "opus"}
    work = terminal.Work({"terminal": {"auto": True, "models": models}, "brain": {}},
                         rungs=rungs("claude:opus"), engines={})
    rung, effort, why = work.shape("Работай по плану.\n" + "- пункт работы\n" * 40)
    assert rung.model == "opus", "большую работу снова взяла самая слабая модель"
    assert effort == "high", "на большую работу осталось низкое усилие"
    assert why == "большая задача"
