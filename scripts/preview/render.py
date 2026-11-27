"""Рендер превью: python3 scripts/preview/render.py СЦЕНА.qml ВЫХОД.mp4 СЕКУНДЫ

Кадр за кадром, t = кадр/60: окно вне экрана, каждый снимок идёт прямо в ffmpeg, поэтому ролик
ровный при любой скорости рендера. CROP=crop=W:H:X:Y — кадрировать (островок мелкий в полном кадре),
FROM=СЕК — начать не с нуля (искать падение). Нужен системный python3 с PySide6.

Программный рендер Qt падает (segfault), если в свойство сцены попадёт NaN: так было с parent.k,
указывавшим не на тот предмет. Падение без сообщения — сначала искать NaN.
"""
import faulthandler
import os
import subprocess
import sys

faulthandler.enable()
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtCore import QUrl  # noqa: E402 — платформа Qt задаётся до импорта
from PySide6.QtGui import QGuiApplication, QImage  # noqa: E402
from PySide6.QtQuick import QQuickView  # noqa: E402

scene, out, secs = sys.argv[1], sys.argv[2], float(sys.argv[3])
app = QGuiApplication([])
v = QQuickView()
v.setSource(QUrl.fromLocalFile(os.path.abspath(scene)))
if v.status() != QQuickView.Status.Ready:
    sys.exit("\n".join(e.toString() for e in v.errors()))
v.show()
W, H = 1920, 1080
crop = ["-vf", os.environ["CROP"]] if os.environ.get("CROP") else []
ff = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24", "-s", f"{W}x{H}",
                       "-r", "60", "-i", "-", *crop, "-c:v", "libx264", "-crf", "16", "-pix_fmt", "yuv420p",
                       "-movflags", "+faststart", out], stdin=subprocess.PIPE)
root = v.rootObject()
for f in range(int(float(os.environ.get("FROM", 0)) * 60), int(secs * 60)):
    root.setProperty("t", f / 60)
    app.processEvents()
    img = v.grabWindow().convertToFormat(QImage.Format.Format_RGB888)
    ff.stdin.write(bytes(img.constBits())[: W * H * 3] if img.bytesPerLine() == W * 3 else
                   b"".join(bytes(img.constScanLine(y))[: W * 3] for y in range(H)))
ff.stdin.close()
ff.wait()
print(out, int(secs * 60), "кадров")
os._exit(0)  # обычный выход Qt здесь иногда падает и KDE показывает окно отчёта
