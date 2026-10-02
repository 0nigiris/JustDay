"""Один терминал, в котором задачу подхватывает тот, кто сейчас может.

Проверяется лестница, а не нейросети: движки здесь подменены. Беда, из-за которой всё это
написано, — «кончился лимит, и работа встала до вечера, потому что человек был в школе».
"""
from __future__ import annotations

import asyncio

import pytest

from justday import terminal


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
            app.query_one("#ask").value = "почини док"
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
    work = terminal.Work({"terminal": {"auto": True, "light_model": "sonnet"}, "brain": {}},
                         rungs=rungs("claude:opus"), engines={})

    monkeypatch.setattr(terminal.dispatch, "level_for",
                        lambda text, **kw: (terminal.dispatch.LIGHT, "местная модель"))
    rung, effort, _ = work.shape("который час")
    assert (rung.model, effort) == ("sonnet", "low")

    monkeypatch.setattr(terminal.dispatch, "level_for",
                        lambda text, **kw: (terminal.dispatch.STRONG, "местная модель"))
    rung, effort, _ = work.shape("разберись, почему док лагает")
    assert (rung.model, effort) == ("opus", "high")
    assert work.rungs[0].model == "opus", "выбор модели на один ход переписал саму лестницу"


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
