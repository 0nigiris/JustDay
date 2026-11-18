"""Хозяин островка без Quickshell: PySide6 + тот же QML.

Quickshell есть только на Linux/Wayland, а островок хотят и на Windows. Переписывать 77 файлов
QML под другой хозяин — месяц работы и два расходящихся островка. Вместо этого здесь
регистрируются типы с теми же именами и модулями (`Quickshell`, `Quickshell.Io`,
`Quickshell.Wayland`, `Quickshell.Services.*`): что требует системы (процессы, сокет, файлы,
экраны) — на Python, остальное — заглушки на QML в `qs/`. QML островка при этом не меняется.

Запуск: `python island/host.py` (на Linux — для проверки; там островок по-прежнему держит qs).
"""
from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

from PySide6.QtCore import Property, QFileSystemWatcher, QObject, QProcess, QProcessEnvironment, QRect, QSaveFile, QUrl, Signal, Slot
from PySide6.QtGui import QGuiApplication, QIcon, QPixmap, QRegion
from PySide6.QtNetwork import QLocalSocket, QTcpSocket
from PySide6.QtQml import QJSValue, QmlAttached, QmlElement, QmlSingleton, QQmlApplicationEngine, qmlRegisterSingletonType, qmlRegisterType
from PySide6.QtQuick import QQuickImageProvider

HERE = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
if getattr(sys, "_MEIPASS", None):
    HERE = HERE / "island"
QS = HERE / "qs"
ROOT = HERE  # папка, из которой грузится QML (см. _stage)


def _list(v) -> list:
    if isinstance(v, QJSValue):
        v = v.toVariant()
    return [str(x) for x in (v or [])]


# ───────────── Quickshell ─────────────
QML_IMPORT_NAME = "Quickshell"
QML_IMPORT_MAJOR_VERSION = 1


class Screen(QObject):
    """Экран в виде Quickshell: x/y/width/height, а настоящий QScreen — для окна."""

    def __init__(self, s, parent=None):
        super().__init__(parent)
        self._s = s

    changed = Signal()
    name = Property(str, lambda self: self._s.name(), notify=changed)
    x = Property(int, lambda self: self._s.geometry().x(), notify=changed)
    y = Property(int, lambda self: self._s.geometry().y(), notify=changed)
    width = Property(int, lambda self: self._s.geometry().width(), notify=changed)
    height = Property(int, lambda self: self._s.geometry().height(), notify=changed)
    qscreen = Property(QObject, lambda self: self._s, constant=True)


@QmlElement
@QmlSingleton
class Quickshell(QObject):
    screensChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._screens: list[Screen] = []
        app = QGuiApplication.instance()
        app.screenAdded.connect(self._rescan)
        app.screenRemoved.connect(self._rescan)
        self._rescan()

    def _rescan(self, *_):
        self._screens = [Screen(s, self) for s in QGuiApplication.screens()]
        self.screensChanged.emit()

    screens = Property("QVariantList", lambda self: list(self._screens), notify=screensChanged)
    # На Windows путь «C:/…» QML принял бы за адрес со схемой «c:», поэтому там отдаётся file:///.
    shellDir = Property(str, lambda self: ROOT.as_uri() if sys.platform == "win32" else str(ROOT), constant=True)

    @Slot(str, result=str)
    def env(self, name: str) -> str:
        return os.environ.get(name, "")

    @Slot("QVariant")
    def execDetached(self, cmd) -> None:
        if isinstance(cmd, QJSValue):
            cmd = cmd.toVariant()
        if isinstance(cmd, dict):
            cmd = cmd.get("command", [])
        cmd = [str(x) for x in cmd]
        if cmd and _which(cmd[0]):
            QProcess.startDetached(_which(cmd[0]), cmd[1:])

    @Slot(str, result=str)
    @Slot(str, bool, result=str)
    def iconPath(self, name: str, check: bool = False) -> str:
        return f"image://icon/{name}" if name else ""

    @Slot(QObject, list)
    def setMask(self, win, rects) -> None:
        """Щелчки мимо островка проходят к окнам под ним: окно отвечает только в этих прямоугольниках."""
        r = QRegion()
        for x, y, w, h in rects:
            r = r.united(QRect(int(x), int(y), max(1, int(w)), max(1, int(h))))
        win.setMask(r if not r.isEmpty() else QRegion(0, 0, 1, 1))


# ───────────── Quickshell.Io ─────────────
QML_IMPORT_NAME = "Quickshell.Io"


@QmlElement
class StdioCollector(QObject):
    streamFinished = Signal()
    textChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._text = ""

    text = Property(str, lambda self: self._text, notify=textChanged)

    def feed(self, data: str) -> None:
        self._text += data

    def reset(self) -> None:
        self._text = ""

    def finish(self) -> None:
        self.textChanged.emit()
        self.streamFinished.emit()


@QmlElement
class SplitParser(QObject):
    read = Signal(str, arguments=["data"])

    def __init__(self, parent=None):
        super().__init__(parent)
        self._buf = ""
        self._marker = "\n"

    splitMarker = Property(str, lambda self: self._marker, lambda self, v: setattr(self, "_marker", v or "\n"))

    def feed(self, data: str) -> None:
        self._buf += data
        *parts, self._buf = self._buf.split(self._marker)
        for p in parts:
            self.read.emit(p)

    def reset(self) -> None:
        self._buf = ""

    def finish(self) -> None:
        if self._buf:
            self.read.emit(self._buf)
            self._buf = ""


@QmlElement
class Process(QObject):
    runningChanged = Signal()
    commandChanged = Signal()
    started = Signal()
    exited = Signal(int, int, arguments=["exitCode", "exitStatus"])

    def __init__(self, parent=None):
        super().__init__(parent)
        self._cmd: list[str] = []
        self._cwd = ""
        self._env: dict = {}
        self._out = self._err = None
        self._p: QProcess | None = None
        self._want = False

    def _get_cmd(self):
        return self._cmd

    def _set_cmd(self, v):
        self._cmd = _list(v)
        self.commandChanged.emit()

    command = Property(list, _get_cmd, _set_cmd, notify=commandChanged)
    workingDirectory = Property(str, lambda self: self._cwd, lambda self, v: setattr(self, "_cwd", v))
    environment = Property("QVariant", lambda self: self._env,
                           lambda self, v: setattr(self, "_env", v.toVariant() if isinstance(v, QJSValue) else (v or {})))
    stdout = Property(QObject, lambda self: self._out, lambda self, v: setattr(self, "_out", v))
    stderr = Property(QObject, lambda self: self._err, lambda self, v: setattr(self, "_err", v))

    def _is_running(self) -> bool:
        return self._p is not None

    def _set_running(self, on: bool) -> None:
        if on and self._p is None:
            self._start()
        elif not on and self._p is not None:
            self._p.kill()

    running = Property(bool, _is_running, _set_running, notify=runningChanged)

    @Slot("QVariant")
    def exec(self, cmd) -> None:
        if self._p is not None:
            self._p.kill()
            self._p.waitForFinished(1000)
        self._set_cmd(cmd)
        self._start()

    @Slot(str)
    def write(self, data: str) -> None:
        if self._p:
            self._p.write(data.encode())

    @Slot()
    @Slot(int)
    def signal(self, _sig: int = 15) -> None:
        if self._p:
            self._p.terminate()

    def _start(self) -> None:
        if not self._cmd or not _which(self._cmd[0]):
            # Команды из Linux (nmcli, pactl…) на Windows нет: тихо «завершилась с ошибкой».
            self.exited.emit(127, 0)
            return
        p = QProcess(self)
        if self._cwd:
            p.setWorkingDirectory(self._cwd)
        if self._env:
            e = QProcessEnvironment.systemEnvironment()
            for k, v in self._env.items():
                e.insert(str(k), str(v)) if v is not None else e.remove(str(k))
            p.setProcessEnvironment(e)
        for s in (self._out, self._err):
            if s is not None:
                s.reset()
        p.readyReadStandardOutput.connect(lambda: self._out and self._out.feed(bytes(p.readAllStandardOutput()).decode(errors="replace")))
        p.readyReadStandardError.connect(lambda: self._err and self._err.feed(bytes(p.readAllStandardError()).decode(errors="replace")))
        p.finished.connect(self._done)
        self._p = p
        p.start(_which(self._cmd[0]), self._cmd[1:])
        self.runningChanged.emit()
        self.started.emit()

    def _done(self, code: int, status) -> None:
        p, self._p = self._p, None
        if p:
            if self._out is not None:
                self._out.feed(bytes(p.readAllStandardOutput()).decode(errors="replace"))
            p.deleteLater()
        for s in (self._out, self._err):
            if s is not None:
                s.finish()
        self.runningChanged.emit()
        self.exited.emit(code, int(status.value) if hasattr(status, "value") else int(status))


@QmlElement
class FileView(QObject):
    pathChanged = Signal()
    loaded = Signal()
    loadFailed = Signal(int, arguments=["error"])
    fileChanged = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._path = ""
        self._text: str | None = None
        self._watch = False
        self._w: QFileSystemWatcher | None = None

    def _set_path(self, v: str) -> None:
        v = QUrl(v).toLocalFile() if v.startswith("file:") else v
        if v == self._path:
            return
        self._path, self._text = v, None
        self._rewatch()
        self.pathChanged.emit()
        if v:
            self.reload()

    path = Property(str, lambda self: self._path, _set_path, notify=pathChanged)
    blockLoading = Property(bool, lambda self: True, lambda self, v: None)
    blockWrites = Property(bool, lambda self: True, lambda self, v: None)
    atomicWrites = Property(bool, lambda self: True, lambda self, v: None)
    printErrors = Property(bool, lambda self: False, lambda self, v: None)
    preload = Property(bool, lambda self: True, lambda self, v: None)

    def _set_watch(self, on: bool) -> None:
        self._watch = bool(on)
        self._rewatch()

    watchChanges = Property(bool, lambda self: self._watch, _set_watch)

    def _rewatch(self) -> None:
        if self._w:
            self._w.deleteLater()
            self._w = None
        if self._watch and self._path and os.path.exists(self._path):
            self._w = QFileSystemWatcher([self._path], self)
            self._w.fileChanged.connect(lambda _p: (self._rewatch(), self.fileChanged.emit()))

    @Slot(result=str)
    def text(self) -> str:
        if self._text is None:
            self.reload()
        return self._text or ""

    @Slot()
    def reload(self) -> None:
        try:
            self._text = Path(self._path).read_text(encoding="utf-8")
            self.loaded.emit()
        except OSError:
            self._text = ""
            self.loadFailed.emit(1)

    @Slot(str)
    def setText(self, s: str) -> None:
        f = QSaveFile(self._path)
        if f.open(QSaveFile.WriteOnly):
            f.write(s.encode())
            f.commit()
            self._text = s


def _token() -> str:
    """Токен демона; лежит там же, где его кладёт config.TOKEN_FILE."""
    path = os.environ.get("JUSTDAY_TOKEN_FILE") or str(
        Path(os.environ.get("APPDATA", Path.home() / "AppData/Roaming")) / "JustDay" / "control.token")
    try:
        return Path(path).read_text().strip()
    except OSError:
        return ""


@QmlElement
class Socket(QObject):
    """Связь с демоном. Путь `tcp:ПОРТ` — TCP на 127.0.0.1 (Windows), иначе локальный сокет."""

    connectedChanged = Signal()
    pathChanged = Signal()
    error = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._path = ""
        self._parser = None
        self._s = None
        self._up = False

    path = Property(str, lambda self: self._path, lambda self, v: (setattr(self, "_path", v), self.pathChanged.emit()),
                    notify=pathChanged)
    parser = Property(QObject, lambda self: self._parser, lambda self, v: setattr(self, "_parser", v))

    def _is_conn(self) -> bool:
        return self._up

    def _set_conn(self, on: bool) -> None:
        if on and self._s is None:
            self._open()
        elif not on and self._s is not None:
            self._s.abort()

    connected = Property(bool, _is_conn, _set_conn, notify=connectedChanged)

    def _open(self) -> None:
        tcp = self._path.startswith("tcp:")
        s = QTcpSocket(self) if tcp else QLocalSocket(self)
        self._s = s
        s.connected.connect(self._on_up)
        s.disconnected.connect(self._gone)
        s.errorOccurred.connect(lambda *_: (self.error.emit(), self._gone()))
        s.readyRead.connect(lambda: self._parser and self._parser.feed(bytes(s.readAll()).decode(errors="replace")))
        # Подключаться после подписки на сигналы: локальный сокет соединяется прямо внутри вызова,
        # и сигнал «соединён» иначе пролетает мимо.
        if tcp:
            s.connectToHost("127.0.0.1", int(self._path[4:]))
        else:
            s.connectToServer(self._path)

    def _on_up(self) -> None:
        if isinstance(self._s, QTcpSocket):
            # Демон на TCP пускает только с токеном первой строкой (daemon._serve_tcp): порт на
            # 127.0.0.1 видят все процессы машины, а файл с токеном — только этот человек.
            self._s.write((_token() + "\n").encode())
        self._up = True
        self.connectedChanged.emit()

    def _gone(self) -> None:
        self._up = False
        if self._s is not None:
            self._s.deleteLater()
            self._s = None
            self.connectedChanged.emit()

    @Slot(str)
    def write(self, data: str) -> None:
        if self._s:
            self._s.write(data.encode())

    @Slot()
    def flush(self) -> None:
        if self._s:
            self._s.flush()


# ───────────── Quickshell.Wayland и BackgroundEffect ─────────────
_changed = Signal()


def _attached_prop(name, typ):
    return Property(typ, lambda self: self._v[name],
                    lambda self, v: (self._v.__setitem__(name, v), self.changed.emit()), notify=_changed)


class LayerAttached(QObject):
    changed = _changed

    def __init__(self, parent=None):
        super().__init__(parent)
        self._v = {"layer": 3, "namespace": "", "keyboardFocus": 0, "blurRegion": None}

    layer = _attached_prop("layer", int)
    namespace = _attached_prop("namespace", str)
    keyboardFocus = _attached_prop("keyboardFocus", int)
    blurRegion = _attached_prop("blurRegion", QObject)


QML_IMPORT_NAME = "Quickshell.Wayland"


@QmlElement
@QmlAttached(LayerAttached)
class WlrLayershell(QObject):
    @staticmethod
    def qmlAttachedProperties(cls, obj):
        return LayerAttached(obj)


QML_IMPORT_NAME = "Quickshell"


@QmlElement
@QmlAttached(LayerAttached)
class BackgroundEffect(QObject):
    @staticmethod
    def qmlAttachedProperties(cls, obj):
        return LayerAttached(obj)


def _register_qml() -> None:
    def t(uri, name, file=None):
        qmlRegisterType(QUrl.fromLocalFile(str(QS / f"{file or name}.qml")), uri, 1, 0, name)

    def single(uri, name):
        qmlRegisterSingletonType(QUrl.fromLocalFile(str(QS / f"{name}.qml")), uri, 1, 0, name)

    for n in ("ShellRoot", "Scope", "Singleton", "Variants", "Intersection", "PanelWindow", "FloatingWindow", "Region", "SystemClock", "QsMenuOpener"):
        t("Quickshell", n)
    t("Quickshell.Io", "IpcHandler")
    for n in ("WlrLayer", "WlrKeyboardFocus", "ExclusionMode", "IdleMonitor"):
        t("Quickshell.Wayland", n)
    t("Quickshell", "ExclusionMode")
    single("Quickshell.Wayland", "ToplevelManager")
    t("Quickshell.Widgets", "ClippingRectangle")
    t("Quickshell.Widgets", "IconImage")
    single("Quickshell.Services.Pipewire", "Pipewire")
    t("Quickshell.Services.Pipewire", "PwObjectTracker")
    single("Quickshell.Services.Mpris", "Mpris")
    single("Quickshell.Services.SystemTray", "SystemTray")
    t("Quickshell.Services.Notifications", "NotificationServer")


class ThemeIcons(QQuickImageProvider):
    """`image://icon/имя` — значок из темы системы, как у Quickshell. На Windows темы нет: пусто,
    и островок рисует свой значок из `icons/`."""

    def __init__(self):
        super().__init__(QQuickImageProvider.Pixmap)

    def requestPixmap(self, ident, size, requested):
        n = max(requested.width(), requested.height(), 64)
        pm = QIcon.fromTheme(ident.split("?")[0]).pixmap(n, n)
        return pm if not pm.isNull() else QPixmap(1, 1)


def _which(name: str) -> str | None:
    """Путь к программе, но никогда не к нам самим.

    Windows ищет программу сначала в текущей папке и не различает регистр: кнопки островка зовут
    `justday …`, а рядом лежит JustDay.exe — и каждая кнопка открывала ещё один островок (issue #6).
    """
    path = shutil.which(name)
    # Только в собранном .exe: из репозитория sys.executable — это python, и python3 запускать можно.
    if path and getattr(sys, "frozen", False) and Path(path).resolve() == Path(sys.executable).resolve():
        return None
    return path


def _stage() -> Path:
    """Папка островка с qmldir.

    Quickshell сам находит `pragma Singleton` (JD.qml) в папке, чистому Qt для этого нужен qmldir.
    Класть его в живую папку островка нельзя: её на Linux держит Quickshell, и чужой qmldir может его
    сбить. В сборке для Windows qmldir кладётся при сборке; при запуске из репозитория — копия папки.
    """
    if (HERE / "qmldir").exists():
        return HERE
    dst = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "justday" / "island-stage"
    shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(HERE, dst, ignore=shutil.ignore_patterns("__pycache__"))
    (dst / "qmldir").write_text("singleton JD 1.0 JD.qml\n")
    return dst


def main() -> int:
    if sys.platform == "win32":
        # На Windows нет unix-сокета: демон слушает TCP на 127.0.0.1 (docs/WINDOWS.md).
        os.environ.setdefault("JUSTDAY_SOCKET", "tcp:47615")
        os.environ.setdefault("JUSTDAY_ISLAND_ONLY", "1")
    app = QGuiApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    _register_qml()
    eng = QQmlApplicationEngine()
    global ROOT
    root = ROOT = _stage()
    eng.addImageProvider("icon", ThemeIcons())
    eng.load(QUrl.fromLocalFile(str(root / os.environ.get("JUSTDAY_ROOT_QML", "shell.qml"))))
    if not eng.rootObjects():
        return 1
    if shot := os.environ.get("JUSTDAY_SHOT"):
        _shoot(app, eng, shot)
    return app.exec()


def _shoot(app, eng, path: str) -> None:
    """Проверка сборки: открыть пульт, снять самое большое окно и выйти.

    Так сборка на машине без человека показывает, как островок выглядит на самом деле, а не только
    что он не упал.
    """
    from PySide6.QtCore import QTimer
    from PySide6.QtQml import QQmlEngine, QQmlExpression

    r = eng.rootObjects()[0]
    QTimer.singleShot(1500, lambda: QQmlExpression(QQmlEngine.contextForObject(r), r, "JD.expanded = true").evaluate())

    def grab():
        wins = [w for w in app.topLevelWindows() if w.isVisible() and hasattr(w, "grabWindow")]
        if wins:
            max(wins, key=lambda w: w.width() * w.height()).grabWindow().save(path)
        app.exit(0 if wins else 2)

    QTimer.singleShot(5000, grab)


if __name__ == "__main__":
    sys.exit(main())
