"""Английский — язык по умолчанию, а в английском островке половина настроек и виджетов была
по-русски: «Молчит», «Процессор», «Шрифт», «Где висит остров» — 390 строк без перевода."""
import json
import re
from pathlib import Path

ISLAND = Path("island")


def test_every_island_string_has_english() -> None:
    en = json.loads((ISLAND / "i18n" / "en.json").read_text(encoding="utf-8"))
    want = set()
    for f in ISLAND.rglob("*.qml"):
        want |= set(re.findall(r'JD\.tr\("((?:[^"\\]|\\.)*)"\)', f.read_text(encoding="utf-8")))
    jd = (ISLAND / "JD.qml").read_text(encoding="utf-8")
    catalog = jd[jd.index("widgetCatalog: ["):jd.index("readonly property string animStyle")]
    want |= set(re.findall(r'(?:name|hint): "([^"]*)"', catalog))
    missing = sorted(s for s in want if re.search("[а-яА-Яё]", s) and s not in en)
    assert not missing, missing[:20]
