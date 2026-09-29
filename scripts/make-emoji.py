#!/usr/bin/env python3
"""Собрать набор эмодзи для выбиралки: data/emoji.json.

Запускается руками, когда выходит новая версия Unicode, а результат лежит в репозитории. Так
выбиралка работает на любой машине: ни CLDR, ни интернета в момент установки не нужно.

Откуда что берётся:

* порядок, группы и состав — из ``emoji-test.txt`` Unicode (только строки fully-qualified: варианты
  с оттенками кожи и служебные «компоненты» в сетке не нужны, они раздувают её в пять раз);
* названия и слова для поиска — из аннотаций CLDR, русских и английских. Их ставит пакет
  ``cldr-emoji-annotation``; чего в нём нет, добирается из имени самого символа в Unicode.

    ./scripts/make-emoji.py                       # оба файла из системных путей
    ./scripts/make-emoji.py --test ~/emoji-test.txt --cldr ~/cldr/common/annotations
"""
from __future__ import annotations

import argparse
import json
import re
import unicodedata
import xml.etree.ElementTree as ET
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
OUT = REPO / "data" / "emoji.json"
TEST = Path("/usr/share/unicode/ucd/emoji/emoji-test.txt")
CLDR = Path("/usr/share/unicode/cldr/common/annotations")

# Названия групп по-русски. Служебные «компоненты» (оттенки кожи, цвета волос) в сетку не идут:
# сами по себе они не вставляются, а только меняют другой символ.
GROUPS: dict[str, str] = {
    "Smileys & Emotion": "Лица",
    "People & Body": "Люди",
    "Animals & Nature": "Природа",
    "Food & Drink": "Еда",
    "Travel & Places": "Места",
    "Activities": "Досуг",
    "Objects": "Предметы",
    "Symbols": "Символы",
    "Flags": "Флаги",
}

KEYWORDS = 8          # сколько слов для поиска держим на символ: дальше идёт вода
LINE = re.compile(r"^([0-9A-F ]+?)\s*;\s*fully-qualified\s*#\s*(\S+)\s+E[\d.]+\s+(.*)$")

# Оттенки кожи в набор не берём. В emoji-test.txt каждый жест и каждая профессия есть в шести
# вариантах, и это 2400 строк из 3900 — сетка, в которой один и тот же врач идёт шесть раз подряд,
# хуже, чем сетка без оттенков. Символ-основа остаётся; оттенок — это отдельная настройка, и её
# место в выбиралке, а не в наборе.
TONES = tuple(chr(c) for c in range(0x1F3FB, 0x1F400))


def emoji_test(path: Path) -> list[dict]:
    """Состав и порядок: [{ch, group, en_name}] — ровно как на клавиатуре эмодзи."""
    out: list[dict] = []
    group = ""
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.startswith("# group:"):
            group = line.split(":", 1)[1].strip()
            continue
        if not line or line.startswith("#"):
            continue
        if group not in GROUPS:
            continue
        m = LINE.match(line)
        if m and not any(t in m.group(2) for t in TONES):
            out.append({"ch": m.group(2), "group": GROUPS[group], "en": m.group(3)})
    return out


def annotations(path: Path) -> tuple[dict[str, str], dict[str, list[str]]]:
    """Из одного файла CLDR: имя символа (type="tts") и слова для поиска."""
    names: dict[str, str] = {}
    words: dict[str, list[str]] = {}
    if not path.is_file():
        return names, words
    for node in ET.parse(path).getroot().iter("annotation"):
        cp = node.get("cp") or ""
        text = (node.text or "").strip()
        if not cp or not text:
            continue
        if node.get("type") == "tts":
            names[cp] = text
        else:
            words[cp] = [w.strip() for w in text.split("|") if w.strip()]
    return names, words


# Флаги стран в аннотациях CLDR не описаны вовсе: там они названы «flag: Russia» по-английски, и
# поиск по слову «Россия» ничего не находил. Названия стран по-русски лежат в другом месте — в
# переводах iso-codes, — и флаг с ними связывает свой же код: пара «региональных индикаторов»
# 🇷🇺 это буквы RU, сдвинутые в отдельный блок Unicode.
FLAG_A = 0x1F1E6      # 🇦


def territories() -> dict[str, str]:
    """Код страны → название по-русски. Нет iso-codes — пустой ответ, флаги останутся английскими."""
    try:
        import gettext

        names = json.loads(Path("/usr/share/iso-codes/json/iso_3166-1.json").read_text(encoding="utf-8"))
        ru = gettext.translation("iso_3166-1", "/usr/share/locale", languages=["ru"])
    except (OSError, ValueError, ImportError):
        return {}
    out = {}
    for country in names.get("3166-1", []):
        code, name = country.get("alpha_2"), country.get("name")
        if code and name:
            # common_name — то, как страну зовут в жизни («Южная Корея», не «Республика Корея»).
            out[code] = ru.gettext(country.get("common_name") or name)
    return out


def flag_code(ch: str) -> str:
    """«🇷🇺» → «RU». Не флаг — пустая строка."""
    points = [ord(c) for c in ch]
    if len(points) == 2 and all(FLAG_A <= p <= FLAG_A + 25 for p in points):
        return "".join(chr(ord("A") + p - FLAG_A) for p in points)
    return ""


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--test", type=Path, default=TEST, help="emoji-test.txt из Unicode")
    ap.add_argument("--cldr", type=Path, default=CLDR, help="каталог annotations из CLDR")
    a = ap.parse_args()
    if not a.test.is_file():
        print(f"нет {a.test}: поставьте unicode-emoji или укажите --test "
              "(https://unicode.org/Public/emoji/latest/emoji-test.txt)")
        return 1

    ru_names, ru_words = annotations(a.cldr / "ru.xml")
    en_names, en_words = annotations(a.cldr / "en.xml")
    if not ru_names:
        print(f"нет русских аннотаций в {a.cldr} — имена будут английские (dnf install cldr-emoji-annotation)")

    # CLDR хранит символы без U+FE0F: «выбиратель варианта» из ключа убран, а в emoji-test.txt он есть.
    def look(table: dict, ch: str):
        return table.get(ch) or table.get(ch.replace("️", ""))

    countries = territories()
    items = []
    for item in emoji_test(a.test):
        ch = item["ch"]
        ru = look(ru_names, ch) or ""
        en = look(en_names, ch) or item["en"]
        words = (look(ru_words, ch) or []) + (look(en_words, ch) or [])
        if (code := flag_code(ch)) and code in countries:
            # Названием оставляем саму страну: «флаг Российская Федерация» не по-русски, а
            # «Российская Федерация» под флагом читается как надо. Слово «флаг» уходит в поиск,
            # чтобы «флаг» находил их все.
            ru = countries[code]
            words = ["флаг", code, *words]
        if not ru:
            # Ни CLDR, ни его английской половины: остаётся имя самого символа в Unicode.
            with_name = " ".join(unicodedata.name(c, "") for c in ch if unicodedata.name(c, ""))
            en = en or with_name.lower()
        items.append({
            "c": ch,
            "n": ru or en,
            "g": item["group"],
            # Слова для поиска: без тех, что уже есть в названии, и без повторов.
            "k": [w for w in dict.fromkeys(words) if w.lower() not in (ru or en).lower()][:KEYWORDS],
            **({"e": en} if en and en != (ru or en) else {}),
        })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"groups": list(GROUPS.values()), "items": items},
                              ensure_ascii=False, separators=(",", ":")) + "\n", encoding="utf-8")
    by_group: dict[str, int] = {}
    for item in items:
        by_group[item["g"]] = by_group.get(item["g"], 0) + 1
    print(f"{OUT.relative_to(REPO)}: {len(items)} символов, {OUT.stat().st_size // 1024} КБ")
    print("  " + ", ".join(f"{g} {n}" for g, n in by_group.items()))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
