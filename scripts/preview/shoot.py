"""Снимки островка вне экрана на Linux через хозяина Windows-сборки (island/host.py).

    python3 scripts/preview/shoot.py 'set=JD.openSettings("general");wel=JD.openTools("welcome")' ПАПКА

Экран вне экрана — 800×600: так видно, как островок живёт на маленьком мониторе. Системный
Quickshell перехватывает имя модуля у подмены из host.py, поэтому путь QML собирается заново без
него. Снимки берут данные живого демона (имя и прочее) — наружу их не выкладывать.
"""
import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ["JUSTDAY_ISLAND_ONLY"] = os.environ.get("ONLY", "1")
QMLDIR = tempfile.mkdtemp()
for d in Path("/usr/lib64/qt6/qml").iterdir():
    if d.name != "Quickshell":
        os.symlink(d, Path(QMLDIR, d.name))

SHOTS, OUT = sys.argv[1], sys.argv[2]
sys.argv = ["host"]
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "island"))
import host  # noqa: E402 — путь к island задаётся выше
from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtGui import QGuiApplication  # noqa: E402
from PySide6.QtQml import QQmlApplicationEngine, QQmlEngine, QQmlExpression  # noqa: E402

app = QGuiApplication([])
host._register_qml()
eng = QQmlApplicationEngine()
eng.setImportPathList([QMLDIR] + [p for p in eng.importPathList() if not p.startswith("/usr/lib")])
host.ROOT = root_dir = host._stage()
eng.addImageProvider("icon", host.ThemeIcons())
eng.load(str(root_dir / "shell.qml"))
if not eng.rootObjects():
    sys.exit("shell.qml не загрузился")
root = eng.rootObjects()[0]
shots = [a.split("=", 1) for a in SHOTS.split(";")]


def step(i=0):
    if i == len(shots):
        os._exit(0)  # обычный выход Qt здесь иногда падает, и KDE показывает окно отчёта
    name, expr = shots[i]
    e = QQmlExpression(QQmlEngine.contextForObject(root), root, expr)
    got = e.evaluate()
    if name.startswith("?"):  # «?имя=выражение» — не снимок, а значение: посмотреть, что знает островок
        print(name, got, file=sys.stderr)
    if e.hasError():  # молча пустой снимок — хуже ошибки: не видно, что выражение не выполнилось
        print(name, e.error().toString(), file=sys.stderr)

    def grab():
        wins = sorted((w for w in app.topLevelWindows() if w.isVisible()), key=lambda w: -w.width() * w.height())
        for k, win in enumerate(wins):  # док и лоток — свои окна; главный снимок — самое большое
            win.grabWindow().save(f"{OUT}/{name}.png" if k == 0 else f"{OUT}/{name}-{k}.png")
        step(i + 1)

    QTimer.singleShot(2500, grab)


QTimer.singleShot(1500, step)
app.exec()
