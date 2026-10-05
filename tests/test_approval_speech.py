"""Подтверждение опасного (Р-4): раньше вслух звучало «Нужно подтверждение. Разрешить?» без слова о том,
что именно, а согласием считалось «да» где угодно во фразе — телевизор мог разрешить `rm -rf`."""
from __future__ import annotations

import asyncio

import pytest

from justday.daemon import Daemon


def демон(choices=None, free=False) -> Daemon:
    d = Daemon.__new__(Daemon)
    d._ask_choices, d._ask_free, d._preapproved_until = choices or [], free, 0.0
    return d


@pytest.mark.parametrize("фраза", ["да", "Да!", "да, разрешаю", "конечно", "давай, делай", "yes", "go ahead"])
def test_короткое_согласие_разрешает(фраза) -> None:
    assert демон()._match_answer(фраза) == "allow"


@pytest.mark.parametrize("фраза", [
    "да, и вообще я считаю, что нужно поменять погоду",
    "ну да, он сказал что завтра будет дождь",
    "ты думаешь, это можно сделать",
])
def test_да_среди_чужой_речи_ничего_не_разрешает(фраза) -> None:
    assert демон()._match_answer(фраза) is None


@pytest.mark.parametrize("фраза", ["нет", "не надо", "отмена", "нет, не разрешаю"])
def test_отказ_понимается_всегда(фраза) -> None:
    assert демон()._match_answer(фраза) == "deny"


def test_опасное_называется_вслух() -> None:
    d = демон()
    сказано: list[str] = []

    async def спросить(speech, **kw):
        сказано.append(speech)
        return "deny"

    d._ask = спросить
    asyncio.run(d._approve("команда: sudo rm -rf /var/lib/important", "", True))
    assert "sudo rm -rf /var/lib/important" in сказано[0]
