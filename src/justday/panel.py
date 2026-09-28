"""Запасная панель — то, что видно вместо Dynamic Island там, где остров не запускается.

Остров рисуется через wlr-layer-shell и живёт только на Wayland. На X11, в Plasma 5, в GNOME и
вообще где угодно его место занимает эта полоска: она на Tk, который есть в любой установке Python,
и не требует ни Quickshell, ни прав администратора.

Что она показывает: слушает ли ассистент (с полоской громкости), думает ли, что он ответил, что
делает Клод. Щелчок — начать или прервать разговор, правая кнопка — меню: написать текстом,
остановить, новый разговор, пауза и следующий трек.

    justday panel            # обычно её запускает justday-panel.service
"""
from __future__ import annotations

import json
import logging
import queue
import re
import socket
import subprocess
import threading
import time

from . import config
from .i18n import t

log = logging.getLogger("justday.panel")

BG = "#101012"          # почти чёрный: панель читается на любых обоях
CARD = "#1c1c1e"
TEXT = "#f5f5f7"
DIM = "#9a9aa0"
CYAN = "#64d2ff"
ORANGE = "#ff9f0a"
BLUE = "#0a84ff"
RED = "#ff453a"
GREEN = "#30d158"

STATE_WORDS = {
    "listening": ("Слушаю…", CYAN),
    "transcribing": ("Распознаю…", CYAN),
    "thinking": ("Думаю…", ORANGE),
    "speaking": ("Говорю", BLUE),
    "approval": ("Жду ответа", ORANGE),
    "offline": ("Не запущен", RED),
}


def send(cmd: str, **kw) -> dict:
    """Одна команда демону — та же, что шлёт остров и командная строка."""
    try:
        with socket.socket(socket.AF_UNIX) as s:
            s.settimeout(10)
            s.connect(str(config.SOCKET_PATH))
            s.sendall((json.dumps({"cmd": cmd, **kw}, ensure_ascii=False) + "\n").encode())
            return json.loads(s.makefile("r", encoding="utf-8").readline() or "{}")
    except (OSError, ValueError) as e:
        log.debug("команда %s не прошла: %s", cmd, e)
        return {"ok": False, "error": str(e)}


class Bus(threading.Thread):
    """Подписка на демона в отдельном потоке: Tk трогать из него нельзя, поэтому всё идёт в очередь."""

    daemon = True

    def __init__(self, box: queue.Queue) -> None:
        super().__init__(name="justday-panel-bus")
        self.box = box

    def run(self) -> None:
        while True:
            try:
                with socket.socket(socket.AF_UNIX) as s:
                    s.settimeout(30)
                    s.connect(str(config.SOCKET_PATH))
                    s.sendall(b'{"cmd": "subscribe"}\n')
                    self.box.put({"_link": True})
                    fh = s.makefile("r", encoding="utf-8")
                    for line in fh:
                        if not line.strip():
                            continue
                        try:
                            self.box.put(json.loads(line))
                        except ValueError:
                            pass
            except (OSError, ValueError):
                pass
            self.box.put({"_link": False})
            time.sleep(2)


class Panel:
    """Полоска сверху экрана. Пока сказать нечего — её нет совсем."""

    def __init__(self) -> None:
        import tkinter as tk

        self.tk = tk
        self.root = tk.Tk()
        self.root.withdraw()
        self.root.title("JustDay")
        self.root.overrideredirect(True)
        self.root.attributes("-topmost", True)
        try:                                    # на X11 это делает окно панелью, а не обычным окном
            self.root.attributes("-type", "dock")
        except tk.TclError:
            pass
        self.root.configure(bg=BG)

        self.state = "idle"
        self.level = 0.0
        self.answer = ""
        self.activity = ""
        self.linked = False
        self.hide_at = 0.0
        self.player: dict | None = None
        self._screen: tuple[int, int] | None = None

        wrap = tk.Frame(self.root, bg=CARD, padx=14, pady=8)
        wrap.pack(fill="both", expand=True)
        self.dot = tk.Canvas(wrap, width=12, height=12, bg=CARD, highlightthickness=0)
        self.dot.pack(side="left", padx=(0, 10))
        self.blob = self.dot.create_oval(1, 1, 11, 11, fill=DIM, outline="")
        self.label = tk.Label(wrap, text="JustDay", bg=CARD, fg=TEXT, font=("Inter", 11, "bold"),
                              anchor="w", justify="left", wraplength=620)
        self.label.pack(side="left")
        self.meter = tk.Canvas(wrap, width=54, height=12, bg=CARD, highlightthickness=0)
        self.bars = [self.meter.create_rectangle(i * 8, 4, i * 8 + 4, 8, fill=CYAN, outline="") for i in range(6)]

        for w in (self.root, wrap, self.label, self.dot):
            w.bind("<Button-1>", lambda _e: send("toggle"))
            w.bind("<Button-3>", self.menu)
        self.box: queue.Queue = queue.Queue()
        Bus(self.box).start()
        self.root.after(80, self.pump)

    # ── внешний вид ──────────────────────────────────────────────
    def screen(self) -> tuple[int, int]:
        """(ширина, левый край) основного монитора: на двух экранах панель иначе встаёт по шву."""
        if self._screen is None:
            self._screen = (self.root.winfo_screenwidth(), 0)
            try:
                out = subprocess.run(["xrandr", "--listmonitors"], capture_output=True, text=True, timeout=3).stdout
                for line in out.splitlines()[1:]:
                    if "*" not in line and len(out.splitlines()) > 2:
                        continue
                    m = re.search(r"(\d+)/\d+x\d+/\d+\+(\d+)\+\d+", line)
                    if m:
                        self._screen = (int(m.group(1)), int(m.group(2)))
                        break
            except (OSError, subprocess.SubprocessError):
                pass
        return self._screen

    def place(self) -> None:
        self.root.update_idletasks()
        w, h = self.root.winfo_reqwidth(), self.root.winfo_reqheight()
        width, left = self.screen()
        x = left + (width - w) // 2
        self.root.geometry(f"{w}x{h}+{max(0, x)}+6")

    def show(self, seconds: float = 0) -> None:
        self.root.deiconify()
        self.root.attributes("-topmost", True)
        self.place()
        self.hide_at = time.monotonic() + seconds if seconds else 0.0

    def hide(self) -> None:
        self.root.withdraw()
        self.hide_at = 0.0

    def paint(self) -> None:
        word, colour = STATE_WORDS.get(self.state, ("", DIM))
        if not self.linked:
            word, colour = t("Не запущен"), RED
        line = self.answer or self.activity or (t(word) if word else "")
        self.label.configure(text=line[:400] or "JustDay", fg=TEXT if self.answer else DIM if not word else TEXT)
        self.dot.itemconfigure(self.blob, fill=colour)
        listening = self.state == "listening" and self.linked
        if listening and not self.meter.winfo_ismapped():
            self.meter.pack(side="left", padx=(10, 0))
        elif not listening and self.meter.winfo_ismapped():
            self.meter.pack_forget()
        for i, bar in enumerate(self.bars):
            height = 2 + 9 * min(1.0, self.level * (0.5 + 0.5 * ((i % 3) + 1) / 3))
            self.meter.coords(bar, i * 9, 6 - height / 2, i * 9 + 4, 6 + height / 2)
        if line:
            self.show(6 if self.answer and self.state == "idle" else 0)
        elif self.state == "idle" and self.linked:
            self.hide()

    # ── меню правой кнопкой ──────────────────────────────────────
    def menu(self, event) -> None:
        m = self.tk.Menu(self.root, tearoff=0, bg=CARD, fg=TEXT, activebackground=BLUE, activeforeground="white")
        m.add_command(label=t("Говорить"), command=lambda: send("toggle"))
        m.add_command(label=t("Написать…"), command=self.compose)
        m.add_command(label=t("Остановить"), command=lambda: send("stop"))
        m.add_separator()
        m.add_command(label=t("Пауза / продолжить"), command=lambda: send("media", action="toggle"))
        m.add_command(label=t("Следующий трек"), command=lambda: send("media", action="next"))
        m.add_separator()
        m.add_command(label=t("Новый разговор"), command=lambda: send("new_session"))
        m.add_command(label=t("Скрыть"), command=self.hide)
        try:
            m.tk_popup(event.x_root, event.y_root)
        finally:
            m.grab_release()

    def compose(self) -> None:
        """Маленькое окно ввода: то же, что поле на острове."""
        top = self.tk.Toplevel(self.root, bg=CARD)
        top.title("JustDay")
        top.attributes("-topmost", True)
        entry = self.tk.Entry(top, width=60, bg="#2c2c2e", fg=TEXT, insertbackground=TEXT,
                              relief="flat", font=("Inter", 12))
        entry.pack(padx=12, pady=12, ipady=6)
        entry.focus_force()

        def go(_event=None) -> None:
            text = entry.get().strip()
            top.destroy()
            if text:
                send("type", text=text)

        entry.bind("<Return>", go)
        entry.bind("<Escape>", lambda _e: top.destroy())

    # ── события демона ───────────────────────────────────────────
    def handle(self, m: dict) -> None:
        if "_link" in m:
            self.linked = bool(m["_link"])
            if not self.linked:
                self.state = "offline"
            self.paint()
            return
        if "state" in m and m["state"] != self.state:
            self.state = m["state"]
            if m["state"] in ("listening", "transcribing"):
                self.answer = ""
            if m["state"] == "listening":
                self.activity = ""
        if "level" in m:
            self.level = max(self.level * 0.6, float(m["level"] or 0))
        if "player" in m:
            self.player = m["player"]
        kind = m.get("kind")
        if kind == "say":
            self.answer = " ".join(str(m.get("detail", "")).split())
        elif kind in ("tool", "heard", "draft", "fast"):
            self.activity = " ".join(str(m.get("detail", "")).split())[:200]
        elif kind == "error":
            self.answer = str(m.get("detail", ""))
        elif kind in ("cancel", "turn_done"):
            self.activity = ""
        self.paint()

    def pump(self) -> None:
        try:
            while True:
                self.handle(self.box.get_nowait())
        except queue.Empty:
            pass
        if self.state == "listening":
            self.level *= 0.85
            self.paint()
        if self.hide_at and time.monotonic() > self.hide_at:
            self.answer = ""
            self.paint()
            if not self.activity:
                self.hide()
        self.root.after(80, self.pump)

    def run(self) -> None:
        self.paint()
        self.root.mainloop()


def main() -> int:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    try:
        Panel().run()
    except ImportError:
        print("панели нужен tkinter: поставьте python3-tkinter (Fedora) или python3-tk (Debian)")
        return 1
    except Exception as e:  # окна может не быть вовсе (нет DISPLAY, нет иксов)
        print(f"панель не запустилась: {e}")
        return 1
    return 0
