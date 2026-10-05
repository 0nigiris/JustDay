"""Все QML-файлы острова компилируются настоящим Quickshell: опечатка в типе, не тот импорт или сломанный синтаксис
ловятся здесь, а не «островок не запустился» после выкладки. `qmllint` на наших файлах шумит предупреждениями про JD
и ничего не гарантирует; а проверка живым движком — это ровно та загрузка, что делает человек (Р-69 ревизии)."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

ISLAND = Path(__file__).resolve().parent.parent / "island"

CHECK = """import QtQuick
import Quickshell

ShellRoot {
    Timer {
        interval: 200; running: true
        onTriggered: {
            for (const f of %s) {
                const c = Qt.createComponent(Qt.resolvedUrl(f + ".qml"))
                console.warn("CHECK " + f + " " + (c.status === Component.Ready ? "ok" : "FAIL " + c.errorString().replace(/\\n/g, " | ")))
            }
            Qt.exit(0)
        }
    }
}
"""


def check(work: Path, names: list[str], platform: str) -> list[str]:
    """Строки «имя ok|FAIL …» по каждому файлу."""
    (work / "check_all.qml").write_text(CHECK % json.dumps(names), encoding="utf-8")
    run = subprocess.run(["quickshell", "-p", str(work / "check_all.qml")], capture_output=True, text=True, timeout=90,
                         env={**os.environ, "QT_QPA_PLATFORM": platform})
    return [line.split("CHECK ", 1)[1] for line in (run.stdout + run.stderr).splitlines() if "CHECK " in line]


@pytest.mark.skipif(not shutil.which("quickshell"), reason="Quickshell не установлен")
def test_every_island_file_compiles_in_the_real_engine(tmp_path) -> None:
    work = tmp_path / "island"
    shutil.copytree(ISLAND, work, ignore=shutil.ignore_patterns("__pycache__", "kwin-effects", "icons", "i18n"))
    for sub in ("icons", "i18n"):       # значки и переводы нужны загрузке, но копировать их целиком незачем
        (work / sub).symlink_to(ISLAND / sub)
    names = sorted(p.stem for p in work.glob("*.qml"))
    rows = check(work, names, "offscreen")
    # Окна-панели без слоя Wayland не собираются вовсе — это не ошибка файла. Если сеанс Wayland есть, эти файлы
    # проверяются в нём (окна при этом не создаются: компилируется только описание); нет — пропускаем.
    nowin = [r.split()[0] for r in rows if "No PanelWindow backend" in r]
    if nowin and os.environ.get("WAYLAND_DISPLAY"):
        rows = [r for r in rows if r.split()[0] not in nowin] + check(work, nowin, "wayland")
        nowin = []
    bad = [r for r in rows if " FAIL " in r and r.split()[0] not in nowin]
    seen = {r.split()[0] for r in rows}
    assert not bad, "не компилируются:\n" + "\n".join(bad)
    assert seen >= {"JD", "QrView", "SettingsView", "ToolsView"}, f"проверка не дошла до конца: {sorted(seen)[:5]}…"
