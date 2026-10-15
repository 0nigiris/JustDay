"""Звук, названный в JD.qml, но не собранный в island/sounds, просто молчал — ни ошибки, ни тоста."""
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_каждый_звук_из_qml_есть_файлом():
    qml = (ROOT / "island" / "JD.qml").read_text()
    names = re.search(r'id: sfxBank\s+model: \[(.*?)\]', qml, re.S).group(1)
    for name in re.findall(r'"(\w+)"', names):
        assert (ROOT / "island" / "sounds" / f"{name}.wav").stat().st_size > 1000, name
