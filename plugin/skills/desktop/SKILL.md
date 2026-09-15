---
name: desktop
description: Control the KDE Plasma 6 Wayland desktop — launch/close/focus apps and windows, type, click, hotkeys, clipboard, screenshots ("look at my screen"), volume, media playback, notifications, lock screen. Use for any request about apps, windows or what is on screen.
---

# Desktop control (KDE Plasma 6, Wayland)

Prefer direct commands; use the `kwin` MCP server for real GUI interaction; screenshots to observe.

## Launch / close apps
- Launch by fuzzy name (handles flatpaks, Russian names): `justday apps launch discord` → prints the matched entry. If the match looks wrong: `justday apps find <name>` and launch the right id with `gtk-launch <id>`.
- Open a file/URL/folder with its default app: `xdg-open <path-or-url>`; folder in Dolphin: `dolphin <dir> &`.
- Terminal in a directory: `kitty --detach --directory <dir>` (optionally followed by a command).
- Windows (fast, native KWin scripting): `justday windows list`, `justday windows focus <app or title>`, `justday windows close <app or title>` (same as the close button — apps can save), `justday windows minimize <…>`.
- Close an app: `justday windows close <name>`; check with `pgrep`. Only if it has no window or ignores close: `pkill -TERM -x <process>` (never -9 first; never `pkill -f` with a pattern that could match your own shell).
- Is it running? `pgrep -af <name>`.

## Windows & input (kwin MCP) — every model turn costs ~3 s, so batch
The kwin server is already connected to the live desktop (no `session_connect`; never `session_start`).
1. **`look`** (optionally `window="discord"` to focus it first) returns the image of the active window directly.
2. **`act`** runs a list of steps in pixels of that image and returns a fresh look:
   `["click 412 88", "type Привет", "key Return"]`, `["key ctrl+k", "type общий", "wait 300", "key Return"]`,
   drawing: `["drag 100 100 300 100 300 300 100 300 100 100"]`, `["hold ctrl", "click 10 20", "click 10 60", "release ctrl"]`, `scroll X Y -5`.
   Put everything you can already predict into ONE `act`. Typing supports any language. No coordinate math: use image pixels.
3. Loop: look → act (with look_after) → act … Usually 2–3 calls for a whole GUI task.
4. Qt/KDE apps also expose `find_ui_elements` (click by name, no image needed). Electron apps (Discord, WhatsApp, browsers) don't — use keyboard shortcuts and `act`.
5. Don't use the single-step tools (`mouse_click`, `keyboard_*`, `justday screenshot` + Read) unless `act` can't do it.

## Look at the screen
- «Что у меня на экране»: `look` (active window) or `look whole_screen=true`. `justday screenshot --full` + Read only for tiny text.
- Describe briefly what matters for the user's question; if something is broken, say what and offer/perform the fix.

## Clipboard, notifications, system
- Clipboard: `wl-paste`, `wl-copy "text"`.
- Notification: `notify-send -a JustDay "Title" "Body"`.
- Volume: `wpctl set-volume @DEFAULT_AUDIO_SINK@ 5%+` / `5%-` / `wpctl set-mute @DEFAULT_AUDIO_SINK@ toggle`; read: `wpctl get-volume @DEFAULT_AUDIO_SINK@`.
- Media: `playerctl play-pause|next|previous|status|metadata`.
- Lock screen: `loginctl lock-session`. Sleep/shutdown/reboot need explicit user request (`systemctl suspend|poweroff|reboot`).
- KWin / Plasma D-Bus: `qdbus-qt6 org.kde.KWin /KWin` (e.g. `org.kde.KWin.showDesktop`), `qdbus-qt6 org.kde.plasmashell /PlasmaShell`.
- Settings changes via `kwriteconfig6 --notify` are allowed for harmless UI prefs; say what you changed.
