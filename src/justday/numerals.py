"""Numbers, times and dates written the way they are said, so a voice never has to guess.

Speech models read digits by themselves, and they read them badly: «в 7:05» comes out as seven
zero five in English, «3,5 ГБ» as three comma five, «20.09.2026» as a phone number. Everything
here turns figures into Russian words before the text reaches the voice.
"""
from __future__ import annotations

import re

ONES_M = ["ноль", "один", "два", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять"]
ONES_F = ["ноль", "одна", "две", "три", "четыре", "пять", "шесть", "семь", "восемь", "девять"]
TEENS = ["десять", "одиннадцать", "двенадцать", "тринадцать", "четырнадцать", "пятнадцать", "шестнадцать",
         "семнадцать", "восемнадцать", "девятнадцать"]
TENS = ["", "", "двадцать", "тридцать", "сорок", "пятьдесят", "шестьдесят", "семьдесят", "восемьдесят", "девяносто"]
HUNDREDS = ["", "сто", "двести", "триста", "четыреста", "пятьсот", "шестьсот", "семьсот", "восемьсот", "девятьсот"]
SCALES = [("", "", "", "m"), ("тысяча", "тысячи", "тысяч", "f"), ("миллион", "миллиона", "миллионов", "m"),
          ("миллиард", "миллиарда", "миллиардов", "m"), ("триллион", "триллиона", "триллионов", "m")]

MONTHS = ["января", "февраля", "марта", "апреля", "мая", "июня",
          "июля", "августа", "сентября", "октября", "ноября", "декабря"]

# nominative ordinals up to twenty, then by tens/hundreds — enough for dates, floors and «5-й раз»
ORD_ONES = ["нулевой", "первый", "второй", "третий", "четвёртый", "пятый", "шестой", "седьмой", "восьмой", "девятый"]
ORD_TEENS = ["десятый", "одиннадцатый", "двенадцатый", "тринадцатый", "четырнадцатый", "пятнадцатый",
             "шестнадцатый", "семнадцатый", "восемнадцатый", "девятнадцатый"]
ORD_TENS = ["", "", "двадцатый", "тридцатый", "сороковой", "пятидесятый", "шестидесятый", "семидесятый",
            "восьмидесятый", "девяностый"]
ORD_HUNDREDS = ["", "сотый", "двухсотый", "трёхсотый", "четырёхсотый", "пятисотый", "шестисотый", "семисотый",
                "восьмисотый", "девятисотый"]

UNITS = {  # what follows a number, in its three Russian forms
    "%": ("процент", "процента", "процентов"), "°": ("градус", "градуса", "градусов"),
    "₽": ("рубль", "рубля", "рублей"), "руб": ("рубль", "рубля", "рублей"),
    "$": ("доллар", "доллара", "долларов"), "€": ("евро", "евро", "евро"),
    "гб": ("гигабайт", "гигабайта", "гигабайт"), "мб": ("мегабайт", "мегабайта", "мегабайт"),
    "кб": ("килобайт", "килобайта", "килобайт"), "тб": ("терабайт", "терабайта", "терабайт"),
    "кг": ("килограмм", "килограмма", "килограммов"), "км": ("километр", "километра", "километров"),
    "гц": ("герц", "герца", "герц"), "кгц": ("килогерц", "килогерца", "килогерц"),
    "мгц": ("мегагерц", "мегагерца", "мегагерц"), "вт": ("ватт", "ватта", "ватт"),
    "мс": ("миллисекунда", "миллисекунды", "миллисекунд"), "млн": ("миллион", "миллиона", "миллионов"),
    "млрд": ("миллиард", "миллиарда", "миллиардов"), "рублей": ("рубль", "рубля", "рублей"),
    "рубля": ("рубль", "рубля", "рублей"),
    "мин": ("минута", "минуты", "минут"), "сек": ("секунда", "секунды", "секунд"),
    "час": ("час", "часа", "часов"), "ч": ("час", "часа", "часов"),
}
FEMININE_UNITS = {"мин", "сек", "мс", "минута", "секунда", "тысяча", "тонна"}

HOURS = ("час", "часа", "часов")
MINUTES = ("минута", "минуты", "минут")
SECONDS = ("секунда", "секунды", "секунд")


def plural(n: int, forms: tuple[str, str, str]) -> str:
    """one / two / five: «1 минута», «2 минуты», «5 минут»."""
    n = abs(n) % 100
    if 11 <= n <= 14:
        return forms[2]
    n %= 10
    if n == 1:
        return forms[0]
    if 2 <= n <= 4:
        return forms[1]
    return forms[2]


def _below_thousand(n: int, gender: str) -> list[str]:
    ones = ONES_F if gender == "f" else ONES_M
    out: list[str] = []
    if n >= 100:
        out.append(HUNDREDS[n // 100])
        n %= 100
    if 10 <= n <= 19:
        out.append(TEENS[n - 10])
    else:
        if n >= 20:
            out.append(TENS[n // 10])
            n %= 10
        if n:
            out.append(ones[n])
    return out


# a number in the genitive, for «от десяти до пятнадцати»
GENITIVE = {"один": "одного", "одна": "одной", "два": "двух", "две": "двух", "три": "трёх", "четыре": "четырёх",
            "пять": "пяти", "шесть": "шести", "семь": "семи", "восемь": "восьми", "девять": "девяти",
            "десять": "десяти", "одиннадцать": "одиннадцати", "двенадцать": "двенадцати", "тринадцать": "тринадцати",
            "четырнадцать": "четырнадцати", "пятнадцать": "пятнадцати", "шестнадцать": "шестнадцати",
            "семнадцать": "семнадцати", "восемнадцать": "восемнадцати", "девятнадцать": "девятнадцати",
            "двадцать": "двадцати", "тридцать": "тридцати", "сорок": "сорока", "пятьдесят": "пятидесяти",
            "шестьдесят": "шестидесяти", "семьдесят": "семидесяти", "восемьдесят": "восьмидесяти",
            "девяносто": "девяноста", "сто": "ста", "двести": "двухсот", "триста": "трёхсот",
            "четыреста": "четырёхсот", "пятьсот": "пятисот", "шестьсот": "шестисот", "семьсот": "семисот",
            "восемьсот": "восьмисот", "девятьсот": "девятисот", "тысяча": "тысячи", "тысячи": "тысяч",
            "миллион": "миллиона", "миллиона": "миллионов"}

# words that make a number feminine: «две минуты», «одна тысяча»
FEM_NEXT = re.compile(r"^(минут|секунд|тысяч|сотн|десятк|копе|недел|тонн|стран|строк|верси|песн|книг|задач|попытк|"
                      r"штук|карт|ссылк|вкладк|папк|програм|систем|модел|нот|глав|серий|игр)", re.I)


def genitive(said: str) -> str:
    return " ".join(GENITIVE.get(w, w) for w in said.split())


def cardinal(n: int, gender: str = "m") -> str:
    """4 → «четыре», 2026 → «две тысячи двадцать шесть», −5 → «минус пять»."""
    if n < 0:
        return "минус " + cardinal(-n, gender)
    if n == 0:
        return "ноль"
    groups: list[int] = []
    while n:
        groups.append(n % 1000)
        n //= 1000
    words: list[str] = []
    for i in range(len(groups) - 1, -1, -1):
        g = groups[i]
        if not g:
            continue
        one, two, many, scale_gender = SCALES[i] if i < len(SCALES) else SCALES[-1]
        words += _below_thousand(g, scale_gender if i else gender)
        if i:
            words.append(plural(g, (one, two, many)))
    said = " ".join(w for w in words if w)
    return said[5:] if said.startswith("одна тысяча") else said  # «тысяча двести», not «одна тысяча двести»


def ordinal(n: int, ending: str = "") -> str:
    """20 → «двадцатый»; `ending` replaces the masculine one: ordinal(20, "ое") → «двадцатое»."""
    if n <= 0:
        return cardinal(n)
    head: list[str] = []
    if n >= 1000:
        head.append(cardinal(n // 1000 * 1000).removesuffix(cardinal(n % 1000)).strip() if n % 1000 else "")
    rest = n % 1000 if n >= 1000 else n
    prefix = cardinal(n - rest) if n >= 1000 and rest else ""
    if not rest:  # round thousand: «две тысячи» → «двухтысячный» is rare; say the cardinal plus «-й»
        word = cardinal(n) + "й"
    elif rest >= 100 and rest % 100 == 0:
        word = ORD_HUNDREDS[rest // 100]
    elif rest >= 100:
        word = (HUNDREDS[rest // 100] + " " + ordinal(rest % 100)).strip()
    elif 10 <= rest <= 19:
        word = ORD_TEENS[rest - 10]
    elif rest >= 20 and rest % 10 == 0:
        word = ORD_TENS[rest // 10]
    elif rest >= 20:
        word = TENS[rest // 10] + " " + ORD_ONES[rest % 10]
    else:
        word = ORD_ONES[rest]
    out = (prefix + " " + word).strip() if prefix else word
    if ending:  # «5-го» → «пятого»: the suffix in the text names the case, not the letters to append
        if ending in ("й", "ый", "ой"):  # already masculine: «шестой» must not become «шестый»
            return out
        full = {"ый": "ый", "ой": "ый", "го": "ого", "ого": "ого", "му": "ому", "ому": "ому",
                "м": "ом", "ом": "ом", "е": "ое", "ое": "ое", "я": "ая", "ая": "ая", "ю": "ую", "ую": "ую",
                "х": "ые", "ые": "ые", "ми": "ыми", "ыми": "ыми"}.get(ending, ending)
        stem = re.sub(r"(ый|ой|ий)$", "", out)
        if out.endswith("ий"):  # третий → третьего
            stem = out[:-2] + "ь"
            full = {"ый": "ий", "ого": "его", "ому": "ему", "ом": "ем", "ое": "ье", "ая": "ья", "ую": "ью"}.get(full, full)
        out = stem + full
    return out


def decimal(whole: int, frac: str) -> str:
    """3,5 → «три с половиной»; 0,25 → «ноль целых двадцать пять сотых»."""
    frac = frac.rstrip("0") or "0"
    if frac == "5":
        return cardinal(whole) + " с половиной"
    if frac == "0":
        return cardinal(whole)
    scale = {1: ("десятая", "десятых"), 2: ("сотая", "сотых"), 3: ("тысячная", "тысячных")}.get(len(frac))
    if not scale:
        return cardinal(whole) + " точка " + " ".join(cardinal(int(d)) for d in frac)
    n = int(frac)
    unit = scale[0] if plural(n, ("a", "b", "c")) == "a" else scale[1]
    return f"{cardinal(whole, 'f')} {plural(whole, ('целая', 'целых', 'целых'))} {cardinal(n, 'f')} {unit}"


def clock(h: int, m: int) -> str:
    """15:30 → «пятнадцать тридцать»; 7:00 → «семь часов»; 7:05 → «семь ноль пять»."""
    if m == 0:
        return f"{cardinal(h)} {plural(h, HOURS)}"
    if m < 10:
        return f"{cardinal(h)} ноль {cardinal(m)}"
    return f"{cardinal(h)} {cardinal(m)}"


def duration(seconds: int) -> str:
    """Seconds → «полторы минуты», «два часа тридцать минут» — for timers and track lengths."""
    seconds = max(0, int(seconds))
    h, m, s = seconds // 3600, seconds % 3600 // 60, seconds % 60
    parts = []
    if h:
        parts.append(f"{cardinal(h)} {plural(h, HOURS)}")
    if m:
        parts.append(f"{cardinal(m, 'f')} {plural(m, MINUTES)}")
    if s and not h:
        parts.append(f"{cardinal(s, 'f')} {plural(s, SECONDS)}")
    return " ".join(parts) or "ноль секунд"


_TIME = re.compile(r"\b([01]?\d|2[0-3]):([0-5]\d)(?::([0-5]\d))?\b")
_DATE = re.compile(r"(?<![\d.])(\d{1,2})[./](\d{1,2})(?:[./](\d{4}|\d{2}))?\b(?!\.?\d)")
_VERSION = re.compile(r"\b\d+(?:\.\d+){2,}\b")
_DECIMAL = re.compile(r"\b(\d+)[.,](\d+)\b")
_ORDINAL = re.compile(r"\b(\d+)-(й|го|му|м|е|ое|ый|ая|ой|я|ю|х|ми)\b", re.I)
_RANGE = re.compile(r"\b(\d+)\s*[–—-]\s*(\d+)\b")
_UNIT = re.compile(r"(?<![\w])([+-]?\d+(?:[.,]\d+)?)\s*(%|°[CС]?|₽|\$|€|ГБ|МБ|КБ|ТБ|кг|км|Гц|кГц|МГц|Вт|"
                   r"мин|сек|мс|час(?:ов|а)?|ч|руб(?:лей|ля)?|млн|млрд)(?!\w)", re.I)
_INT = re.compile(r"(?<![\w.])([+-]?\d+)(?![\w.])")


def _unit_form(value: str, unit: str) -> str:
    key = unit.lower().rstrip("cс") if unit.startswith("°") else unit.lower()
    key = re.sub(r"(ов|а)$", "", key) if key.startswith("час") else key
    forms = UNITS.get(key)
    whole, _, frac = value.replace(",", ".").partition(".")
    sign = ""
    if whole.startswith(("+", "-")):
        sign, whole = ("плюс " if whole[0] == "+" else "минус "), whole[1:]
    n = int(whole or 0)
    gender = "f" if key in FEMININE_UNITS else "m"
    said = decimal(n, frac) if frac else cardinal(n, gender)
    if not forms:
        return f"{sign}{said}"
    return f"{sign}{said} {plural(n if not frac else 2, forms)}"


_YEAR = re.compile(r"\b(1[6-9]\d{2}|20\d{2})\s+(году|года|год|г\.)", re.I)


def spell(text: str) -> str:
    """Every figure in the text, said out loud. Safe to run on any sentence."""
    text = _YEAR.sub(lambda m: ordinal(int(m[1]), {"году": "ом", "года": "ого"}.get(m[2].lower(), "й")) + " " + m[2], text)
    text = _TIME.sub(lambda m: clock(int(m[1]), int(m[2])) + (f" {cardinal(int(m[3]), 'f')} {plural(int(m[3]), SECONDS)}" if m[3] else ""), text)

    def date(m: re.Match) -> str:
        day, month = int(m[1]), int(m[2])
        if not (1 <= day <= 31 and 1 <= month <= 12):
            return m.group(0)
        out = f"{ordinal(day, 'ое')} {MONTHS[month - 1]}"
        if m[3]:
            year = int(m[3]) if len(m[3]) == 4 else 2000 + int(m[3])
            out += f" {ordinal(year, 'ого')} года"
        return out

    text = _DATE.sub(date, text)
    text = _VERSION.sub(lambda m: " точка ".join(cardinal(int(p)) for p in m.group(0).split(".")), text)
    text = _ORDINAL.sub(lambda m: ordinal(int(m[1]), m[2].lower()), text)
    text = _UNIT.sub(lambda m: _unit_form(m[1], m[2]), text)
    text = _RANGE.sub(lambda m: f"от {genitive(cardinal(int(m[1])))} до {genitive(cardinal(int(m[2])))}", text)
    text = re.sub(r"\b(от|с)\s+от\s+", r"\1 ", text)  # «от 10-15» already carries its own preposition
    text = _DECIMAL.sub(lambda m: decimal(int(m[1]), m[2]), text)
    def integer(m: re.Match) -> str:
        raw = m[1]
        gender = "f" if FEM_NEXT.match(text[m.end():].lstrip()) else "m"
        if raw.startswith("+"):
            return "плюс " + cardinal(int(raw[1:]), gender)
        return cardinal(int(raw), gender)

    text = _INT.sub(integer, text)
    return text
