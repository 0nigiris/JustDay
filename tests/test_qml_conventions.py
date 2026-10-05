"""Настройка «без анимаций» гасила не всё: из 59 Behavior в shell.qml 35 не смотрели на JD.animOn, и карточки
продолжали ездить у человека, который анимации выключил. Здесь разбираются настоящие блоки Behavior (с учётом
вложенных скобок), а не подстроки: каждый обязан зависеть от JD.animOn."""
import re
from pathlib import Path

ISLAND = Path(__file__).resolve().parent.parent / "island"


def behaviors(text: str):
    """Блоки `Behavior on … { … }` целиком, с учётом вложенных фигурных скобок."""
    # Только настоящие объявления: «Behavior on x {» в начале строки или после `{`, а не слова в комментарии.
    for m in re.finditer(r"(?m)^(?!\s*//).*?(Behavior on [\w.]+ \{)", text):
        start, depth = m.start(1), 0
        for j in range(m.end(1) - 1, len(text)):
            depth += (text[j] == "{") - (text[j] == "}")
            if depth == 0:
                break
        yield text[start:j + 1]


def test_every_behavior_follows_the_no_animations_setting() -> None:
    bad = []
    for f in sorted(ISLAND.glob("*.qml")):
        for block in behaviors(f.read_text(encoding="utf-8")):
            if "JD.animOn" not in block:
                bad.append(f"{f.name}: {block.splitlines()[0][:90]}")
    assert not bad, "Behavior не гасится настройкой «без анимаций»:\n" + "\n".join(bad)
