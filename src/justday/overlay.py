#!/usr/bin/python3
"""JustDay on-screen indicator — a "dynamic island" pill at the top of the screen (Wayland layer-shell).

Runs with the *system* Python (PyGObject + GTK4 + gtk4-layer-shell from distro packages), so it has no
dependency on the JustDay virtualenv. It subscribes to the daemon's Unix socket and renders:
  listening    — arc-reactor ring pulsing with your voice
  transcribing — ring spinning
  thinking     — amber ring + what JustDay is doing (tool calls)
  speaking     — cyan ripples + the sentence being spoken
  approval     — orange blinking ring + what needs confirmation
  idle         — hidden (or a small dot while Claude Code workers are running)
The window is click-through and never takes focus.
"""
from __future__ import annotations

import json
import math
import os
import socket
import threading
import time
from ctypes import CDLL

CDLL("libgtk4-layer-shell.so.0")  # must be loaded before GTK (per gtk4-layer-shell docs)

import cairo  # noqa: E402
import gi  # noqa: E402

gi.require_version("Gtk", "4.0")
gi.require_version("Gtk4LayerShell", "1.0")
gi.require_foreign("cairo")
from gi.repository import GLib, Gtk  # noqa: E402
from gi.repository import Gtk4LayerShell as LayerShell  # noqa: E402

SOCKET = os.path.join(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"), "justday.sock")

STATES = {  # title, rgb
    "listening": ("Слушаю", (0.35, 0.85, 1.0)),
    "transcribing": ("Распознаю", (0.75, 0.9, 1.0)),
    "thinking": ("Думаю", (1.0, 0.72, 0.2)),
    "speaking": ("Говорю", (0.35, 0.85, 1.0)),
    "approval": ("Нужно подтверждение", (1.0, 0.45, 0.15)),
    "offline": ("JustDay не запущен", (0.9, 0.3, 0.3)),
}

CSS = b"""
window { background: transparent; }
.pill {
  background: rgba(12, 16, 22, 0.88);
  border-radius: 999px;
  padding: 6px 18px 6px 8px;
  border: 1px solid rgba(120, 200, 255, 0.18);
  box-shadow: 0 4px 18px rgba(0,0,0,0.45);
}
.title { color: #e8f4ff; font-weight: 700; font-size: 13px; }
.detail { color: rgba(220, 235, 250, 0.72); font-size: 12px; }
"""


class Overlay(Gtk.Application):
    def __init__(self) -> None:
        super().__init__(application_id="net.local.justday.overlay")
        self.state = "offline"
        self.detail = ""
        self.level = 0.0
        self.workers = 0
        self.opacity = 0.0
        self.t0 = time.monotonic()
        self.last_change = time.monotonic()

    # ---------- UI ----------
    def do_activate(self) -> None:
        provider = Gtk.CssProvider()
        provider.load_from_data(CSS)
        Gtk.StyleContext.add_provider_for_display(
            Gtk.Widget.get_display(Gtk.Label()), provider, Gtk.STYLE_PROVIDER_PRIORITY_APPLICATION)

        self.win = Gtk.ApplicationWindow(application=self)
        LayerShell.init_for_window(self.win)
        LayerShell.set_layer(self.win, LayerShell.Layer.OVERLAY)
        LayerShell.set_anchor(self.win, LayerShell.Edge.TOP, True)
        LayerShell.set_margin(self.win, LayerShell.Edge.TOP, 10)
        LayerShell.set_keyboard_mode(self.win, LayerShell.KeyboardMode.NONE)
        LayerShell.set_namespace(self.win, "justday-overlay")

        box = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=10)
        box.add_css_class("pill")
        self.ring = Gtk.DrawingArea()
        self.ring.set_content_width(34)
        self.ring.set_content_height(34)
        self.ring.set_draw_func(self.draw_ring)
        texts = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=0, valign=Gtk.Align.CENTER)
        self.title = Gtk.Label(xalign=0)
        self.title.add_css_class("title")
        self.sub = Gtk.Label(xalign=0, max_width_chars=52, ellipsize=3)  # PANGO_ELLIPSIZE_END
        self.sub.add_css_class("detail")
        texts.append(self.title)
        texts.append(self.sub)
        box.append(self.ring)
        box.append(texts)
        self.box = box
        self.win.set_child(box)
        self.win.connect("realize", self.on_realize)
        self.win.present()
        self.render_text()
        GLib.timeout_add(33, self.tick)
        threading.Thread(target=self.reader, daemon=True).start()

    def on_realize(self, win) -> None:
        surface = win.get_surface()
        if surface:
            surface.set_input_region(cairo.Region())  # click-through

    def visible_state(self) -> bool:
        if self.state in ("idle",):
            return self.workers > 0
        if self.state == "offline":
            return False
        return True

    def render_text(self) -> None:
        if self.state == "idle" and self.workers:
            self.title.set_text("Клод работает" + (f" ×{self.workers}" if self.workers > 1 else ""))
            self.sub.set_text("")
        else:
            self.title.set_text(STATES.get(self.state, (self.state, None))[0])
            self.sub.set_text(self.detail)
        self.sub.set_visible(bool(self.sub.get_text()))

    def tick(self) -> bool:
        target = 1.0 if self.visible_state() else 0.0
        self.opacity += (target - self.opacity) * 0.18
        self.box.set_opacity(max(0.0, min(1.0, self.opacity)))
        if self.opacity > 0.01:
            self.ring.queue_draw()
        self.level *= 0.85
        return True

    def draw_ring(self, area, cr, w, h) -> None:
        t = time.monotonic() - self.t0
        cx, cy = w / 2, h / 2
        state = self.state
        rgb = STATES.get(state, ("", (0.35, 0.85, 1.0)))[1] if state != "idle" else (0.55, 0.65, 0.75)
        base = 9.0
        if state == "listening":
            r = base + 5.5 * min(1.0, self.level)
            glow = 0.35 + 0.65 * min(1.0, self.level)
        elif state == "speaking":
            r = base + 2.5 * (0.5 + 0.5 * math.sin(t * 9))
            glow = 0.6
        elif state == "thinking":
            r = base + 1.5 * math.sin(t * 3)
            glow = 0.45 + 0.25 * math.sin(t * 3)
        elif state == "approval":
            r, glow = base + 2, 0.4 + 0.6 * (0.5 + 0.5 * math.sin(t * 7))
        else:
            r, glow = base - 3, 0.5
        # outer glow
        for i in range(4, 0, -1):
            cr.set_source_rgba(*rgb, 0.07 * glow * i)
            cr.arc(cx, cy, r + i * 2.2, 0, 2 * math.pi)
            cr.fill()
        # ring
        cr.set_line_width(2.6)
        cr.set_source_rgba(*rgb, 0.95)
        if state in ("transcribing", "thinking"):
            start = t * 5
            cr.arc(cx, cy, r, start, start + math.pi * 1.4)
        else:
            cr.arc(cx, cy, r, 0, 2 * math.pi)
        cr.stroke()
        # core
        cr.set_source_rgba(0.9, 0.97, 1.0, 0.55 + 0.45 * glow)
        cr.arc(cx, cy, max(2.0, r * 0.35), 0, 2 * math.pi)
        cr.fill()
        # speaking ripples
        if state == "speaking":
            for k in range(2):
                phase = (t * 1.6 + k * 0.5) % 1.0
                cr.set_source_rgba(*rgb, 0.5 * (1 - phase))
                cr.set_line_width(1.2)
                cr.arc(cx, cy, r + 2 + phase * 6, 0, 2 * math.pi)
                cr.stroke()

    # ---------- data ----------
    def apply(self, msg: dict) -> bool:
        if "state" in msg:
            if msg["state"] != self.state:
                self.state = msg["state"]
                if self.state in ("listening", "idle"):
                    self.detail = ""
                self.last_change = time.monotonic()
        if "detail" in msg:
            kind = msg.get("kind")
            # while listening don't overwrite; heard/say/tool texts describe what is going on
            if kind in ("heard", "tool", "say", "draft", "approval_wait", "worker_start", "brain_error", "turn_failed"):
                self.detail = msg["detail"]
        if "level" in msg:
            self.level = max(self.level, float(msg["level"]))
        if "workers" in msg:
            self.workers = int(msg["workers"])
        self.render_text()
        return False

    def reader(self) -> None:
        while True:
            try:
                s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
                s.connect(SOCKET)
                s.sendall(b'{"cmd": "subscribe"}\n')
                f = s.makefile("r", encoding="utf-8")
                for line in f:
                    try:
                        GLib.idle_add(self.apply, json.loads(line))
                    except json.JSONDecodeError:
                        pass
            except OSError:
                pass
            GLib.idle_add(self.apply, {"state": "offline"})
            time.sleep(2)


if __name__ == "__main__":
    Overlay().run([])
