"""Launchpad (пункт 28) — необязательный вид меню. Беда, которой нельзя допустить: после обновления у человека
меню само стало бы полноэкранным. Поэтому по умолчанию — прежняя карточка, а значения выбора в настройках
совпадают с теми, что понимает JD.qml."""
import re
from pathlib import Path

from justday import config

ISLAND = Path(__file__).resolve().parent.parent / "island"


def test_menu_stays_a_card_unless_the_person_chooses_launchpad() -> None:
    assert config.DEFAULTS["island"]["menu_style"] == "card"


def test_settings_offer_only_styles_the_island_understands() -> None:
    settings = (ISLAND / "SettingsView.qml").read_text(encoding="utf-8")
    block = settings[settings.index('key: "island.menu_style"'):][:300]
    offered = set(re.findall(r'value: "(\w+)"', block))
    assert offered == {"card", "launchpad"}
    jd = (ISLAND / "JD.qml").read_text(encoding="utf-8")
    assert '(island.menu_style || "card") === "launchpad"' in jd
