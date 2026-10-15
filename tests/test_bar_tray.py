"""Трей на сплошной полосе мигал и терял значки: список строили фильтром заново на каждое событие, и все значки
заново плыли из прозрачности. Теперь полоса держит весь список, а что остаётся на ней и что уходит под шеврон,
решает `island/barTray.js` — его и проверяем настоящим Node."""
import json
import shutil
import subprocess
from pathlib import Path

import pytest

JS = Path(__file__).resolve().parent.parent / "island" / "barTray.js"

pytestmark = pytest.mark.skipif(not shutil.which("node"), reason="нужен node")


def run(items: list[dict], max_: int) -> dict:
    """Те же вызовы, что делает полоса: inBar для каждого значка и overflow."""
    script = """
const src = require('fs').readFileSync(process.argv[1], 'utf8').replace('.pragma library', '')
const m = new Function(src + '; return {inBar, overflow}')()
const items = JSON.parse(process.argv[2]).map(o => ({...o}))
const shown = o => o.show && o.status !== 0
const max = Number(process.argv[3])
console.log(JSON.stringify({
  bar: items.filter(o => m.inBar(items, o, shown, max)).map(o => o.id),
  over: m.overflow(items, shown, max),
}))
"""
    out = subprocess.run(["node", "-e", script, str(JS), json.dumps(items), str(max_)],
                         capture_output=True, text=True, check=True)
    return json.loads(out.stdout)


def tray(n: int) -> list[dict]:
    return [{"id": f"app{i}", "show": True, "status": 1} for i in range(n)]


def test_all_fit_nothing_goes_under_the_chevron() -> None:
    got = run(tray(4), 8)
    assert got == {"bar": ["app0", "app1", "app2", "app3"], "over": 0}


def test_extra_icons_leave_in_tray_order_and_the_first_ones_stay() -> None:
    got = run(tray(10), 8)
    assert got["bar"] == [f"app{i}" for i in range(8)]
    assert got["over"] == 2


def test_hidden_and_passive_go_under_the_chevron_and_do_not_eat_the_places() -> None:
    items = tray(5)
    items[0]["show"] = False       # человек скрыл в настройках
    items[1]["status"] = 0         # программа сама сказала «пассивен»
    got = run(items, 2)
    # два места достались показываемым, а не занялись скрытым впереди
    assert got["bar"] == ["app2", "app3"]
    assert got["over"] == 3

