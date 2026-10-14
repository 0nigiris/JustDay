"""Настройка «без анимаций» гасила не всё: из 59 Behavior в shell.qml 35 не смотрели на JD.animOn, и карточки
продолжали ездить у человека, который анимации выключил. Здесь разбираются настоящие блоки Behavior (с учётом
вложенных скобок), а не подстроки: каждый обязан зависеть от JD.animOn."""
import re
from pathlib import Path

ISLAND = Path(__file__).resolve().parent.parent / "src" / "justday" / "island"


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


# Характер зверька (Mascot, Buddy) и кольцо — своя хореография, не интерфейсное движение.
FREE_TIMING = {"Mascot.qml", "Buddy.qml", "Ring.qml", "ActivityProgress.qml"}


def test_behavior_durations_come_from_the_motion_tokens() -> None:
    """Движение — три длительности на весь проект (Р2-9): числа в Behavior разъезжались от 55 до 450 мс, и
    у соседних кнопок отклик был разным. Блок с `duration: 170` ловится здесь; нужная длительность — один из
    JD.durFast / durBase / durSlow."""
    bad = []
    for f in sorted(ISLAND.glob("*.qml")):
        if f.name in FREE_TIMING:
            continue
        for block in behaviors(f.read_text(encoding="utf-8")):
            if re.search(r"duration:\s*\d", block):
                bad.append(f"{f.name}: {block.splitlines()[0][:90]}")
    assert not bad, "Behavior с числом вместо токена движения:\n" + "\n".join(bad)


def test_text_metrics_are_not_written_from_inside_a_binding() -> None:
    """Меню лотка мерило имена через `probe.text = …; probe.width` внутри readonly-свойства: запись в
    TextMetrics из биндинга, который сам от него зависит, — 900 Binding loop в журнале за сутки на каждое
    открытие меню. Мерить строку в цикле — `FontMetrics.advanceWidth(text)`, чистая функция."""
    bad = []
    for f in sorted(ISLAND.glob("*.qml")):
        text = f.read_text(encoding="utf-8")
        ids = re.findall(r"TextMetrics\s*\{[^}]*?\bid:\s*(\w+)", text)
        for name in ids:
            for ln, line in enumerate(text.splitlines(), 1):
                if re.search(rf"\b{name}\.text\s*=(?!=)", line):
                    bad.append(f"{f.name}:{ln}: {line.strip()[:90]}")
    assert not bad, "TextMetrics пишут изнутри кода — будет Binding loop:\n" + "\n".join(bad)
