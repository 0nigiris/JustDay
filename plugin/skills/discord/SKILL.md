---
name: discord
description: Discord (Equibop/Discord client) — join a voice channel, open a server/channel/DM, leave voice, mute/deafen. Keyboard-driven via the Quick Switcher; use this instead of clicking around.
---

# Discord: keyboard first (fast, reliable)

The user's client may be Equibop (check memory / `justday apps find discord`). Never click the server sidebar blindly — the "+" (create server) button is right there.

## Open anything / join a voice channel
Quick Switcher (Ctrl+K) prefixes: `!` voice channels · `#` text channels · `*` servers · `@` people. Selecting a voice channel **joins** it.
1. Known target, no look needed: `justday windows focus equibop`, then ONE
   `act ["key ctrl+k", "type !<part of channel name>", "wait 400", "key Return"]` (look_after only if unsure).
2. Need to choose (e.g. "any voice channel with digits in the moderator zone"): `act ["key ctrl+k", "type !", "wait 400"]` → the returned image shows the list → `act ["key Down", "key Down", "key Return"]` or `act ["click X Y"]` on the row.
3. Not running: `justday apps launch <client>`, wait ~4 s. Done → end the turn silently.

## Send a DM / channel message
1. `justday contacts find <who>` → Discord nick. Then **before touching Discord**: `justday confirm-message --to "<who>" --via Discord --text "<exact text>"` and act on its answer (`approved` / `edit: …` / `denied`).
2. Approved → `justday windows focus equibop`, ONE `act ["key ctrl+k", "type @<nick>", "wait 500", "key Return", "wait 700", "type <text>", "key Return"]` (look_after to verify). No second confirmation — the draft approval covers the send.

## Voice controls (default Discord keybinds, window focused)
- Mute mic: `ctrl+shift+m` · Deafen: `ctrl+shift+d` · Leave call: no default key → Quick Switcher is not needed: click the "disconnect" (phone) icon found via `find_ui_elements` "Disconnect"/"Отключиться".
- Jump to server by position: `ctrl+alt+up/down`; unread: `alt+shift+up/down`.

Save server/channel names the user mentions to memory (e.g. the server they play on, favourite voice channels).
