#!/usr/bin/env python3
"""Собирает файлы знака в brand/ из геометрии монограммы JD (он выбрал её 24 нояб.).

Знак считается, а не рисуется мышью: другая толщина или другой цвет меняются одной цифрой,
и все размеры остаются согласованными. Надпись переводится в кривые (нужен fontTools и Inter),
чтобы знак не зависел от шрифтов чужой машины. Запуск: python3 scripts/brand.py
"""
import subprocess
from pathlib import Path

from fontTools.pens.svgPathPen import SVGPathPen
from fontTools.pens.transformPen import TransformPen
from fontTools.ttLib import TTFont

OUT = Path(__file__).resolve().parent.parent / "brand"
INTER = "/usr/share/fonts/rsms-inter-fonts/Inter-SemiBold.ttf"
INK, PAPER, ACCENT, BG2 = "#F5F5F7", "#0A0A0D", "#0060DF", "#16161A"
# Монограмма в своей сетке: J и D одной толщиной, точка над J — единственное яркое пятно.
# Рамка знака: x −7…115, y −23…95 (с учётом половины толщины линии).
STROKE = 14
LINES = ['M38 14 V62 a18 18 0 0 1 -36 0', 'M58 12 V88', 'M58 12 H70 a38 38 0 0 1 0 76 H58']
DOT = (38, -14, 9)
BOX = (-7, -23, 122, 118)  # x, y, w, h


def mark(ink, accent, tx=0.0, ty=0.0, s=1.0):
    paths = "".join(f'<path d="{d}"/>' for d in LINES)
    x, y, r = DOT
    return (f'<g transform="translate({tx:g} {ty:g}) scale({s:g})">'
            f'<g fill="none" stroke="{ink}" stroke-width="{STROKE}" stroke-linecap="round">{paths}</g>'
            f'<circle cx="{x}" cy="{y}" r="{r}" fill="{accent}"/></g>')


def word(text, size, x, baseline, fill, tracking=-0.015):
    """Слово в кривые: глифы Inter по одному, межбуквенное как в макете (−1,5 %)."""
    f = TTFont(INTER)
    gs, cmap, hmtx = f.getGlyphSet(), f.getBestCmap(), f["hmtx"]
    k = size / f["head"].unitsPerEm
    out, pen_x = [], x
    for ch in text:
        g = cmap[ord(ch)]
        pen = SVGPathPen(gs)
        gs[g].draw(TransformPen(pen, (k, 0, 0, -k, pen_x, baseline)))
        out.append(pen.getCommands())
        pen_x += hmtx[g][0] * k + tracking * size
    return f'<path fill="{fill}" d="{" ".join(out)}"/>', pen_x - tracking * size - x


def svg(w, h, body, label="JustDay"):
    return (f'<?xml version="1.0" encoding="UTF-8"?>\n'
            f'<!-- JustDay. Собрано scripts/brand.py — править там, а не здесь. -->\n'
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:g} {h:g}" width="{w:g}" height="{h:g}" '
            f'role="img" aria-label="{label}"><title>{label}</title>{body}</svg>\n')


def lockup(text, ink, bg, name, label):
    # Тело букв знака (y 5…95) стоит вровень с прописными слова, точка выходит над ними.
    size, h = 104, 192
    cap = 0.727 * size                       # высота прописных Inter
    s = (cap + 16) / 90
    base = h / 2 + (cap + 28 * s) / 2       # середина между верхом точки и низом букв — в середине поля
    mx = 32 - BOX[0] * s
    my = base + 8 - 95 * s
    path, ww = word(text, size, 32 + BOX[2] * s + 36, base, ink)
    w = 32 + BOX[2] * s + 36 + ww + 32
    back = f'<rect width="{w:g}" height="{h}" rx="28" fill="{bg}"/>' if bg else ""
    (OUT / name).write_text(svg(round(w, 2), h, back + mark(ink, ACCENT, mx, my, s) + path, label))


def square(size, rx, name, pad):
    s = (size - 2 * pad) / max(BOX[2], BOX[3])
    tx = (size - BOX[2] * s) / 2 - BOX[0] * s
    ty = (size - BOX[3] * s) / 2 - BOX[1] * s
    bg = (f'<defs><linearGradient id="bg" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="{BG2}"/>'
          f'<stop offset="1" stop-color="{PAPER}"/></linearGradient></defs>'
          f'<rect width="{size}" height="{size}" rx="{rx:g}" fill="url(#bg)"/>')
    (OUT / name).write_text(svg(size, size, bg + mark(INK, ACCENT, tx, ty, s)))


def main():
    w, h = BOX[2], BOX[3]
    plain = mark(INK, ACCENT, -BOX[0], -BOX[1])
    (OUT / "justday-mark.svg").write_text(svg(w, h, plain))
    (OUT / "justday-mark-flat.svg").write_text(svg(w, h, mark(PAPER, ACCENT, -BOX[0], -BOX[1])))
    (OUT / "justday-mono.svg").write_text(svg(w, h, mark("currentColor", "currentColor", -BOX[0], -BOX[1])))
    lockup("JustDay", INK, PAPER, "justday-lockup-dark.svg", "JustDay")
    lockup("JustDay", PAPER, None, "justday-lockup-light.svg", "JustDay")
    lockup("Джарвис", INK, PAPER, "justday-lockup-ru.svg", "JustDay — Джарвис")
    square(1024, 229.069, "justday-icon.svg", 220)
    square(64, 14, "justday-favicon.svg", 8)   # на 16 px знак крупнее: поля съели бы буквы
    pngs = []
    for px in (16, 32, 48, 256):
        p = OUT / f".ico-{px}.png"
        src = "justday-favicon.svg" if px <= 32 else "justday-icon.svg"
        subprocess.run(["magick", "-background", "none", "-density", "600", str(OUT / src),
                        "-resize", f"{px}x{px}", str(p)], check=True)
        pngs.append(str(p))
    subprocess.run(["magick", *pngs, str(OUT / "justday.ico")], check=True)
    for p in pngs:
        Path(p).unlink()


if __name__ == "__main__":
    main()
