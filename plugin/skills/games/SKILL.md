---
name: games
description: Launch games — Steam (native or Flatpak, Proton), Heroic (Epic/GOG), other launchers and Windows .exe via Proton; troubleshoot a game that does not start.
---

# Games

1. `justday games list` — installed Steam (all library folders, native + Flatpak) and Heroic games with ids.
2. `justday games launch <name>` — fuzzy match and launch (`steam steam://rungameid/<appid>`; Proton is applied by Steam automatically per game settings).
3. Not found there: `justday apps find <name>` (games often have .desktop shortcuts: Minecraft, Roblox/Sober, osu!, AppImages), or `plocate -i <name> | grep -iE '\.(exe|AppImage|sh|desktop)$'`.
4. A Windows .exe outside Steam: prefer adding it to Steam as a non-Steam game or Heroic; otherwise run with Proton via `umu-run` if installed, else tell the user what is needed.

## Verify & recover
- After ~15–40 s check it is running: `pgrep -af -i "<name>|reaper|proton"` and/or kwin `list_windows`.
- Steam not running yet → the steam:// URL starts it first; allow up to a minute.
- Failure: read `~/.local/share/Steam/logs/console-linux.txt` tail (Flatpak: `~/.var/app/com.valvesoftware.Steam/.local/share/Steam/logs/`), and `~/steam-<appid>.log` if PROTON_LOG was on. Typical fixes: switch Proton version (ask before changing game settings), verify files `steam steam://validate/<appid>`.

## Playing: moving a character (Roblox/Sober and other 3D games)
Real-time control works through `act` steps; each look → act round costs a few seconds, so play in short, deliberate moves (stop, look, move), never "hold W and hope".
1. `justday windows focus sober` (or the game), then `look` to see the scene.
2. Movement — keys with durations (`press`), several in one `act`:
   - walk forward 0.8 s: `["press w 800"]`; strafe: `press a 400` / `press d 400`; back: `press s 500`;
   - run-jump over a gap: `["hold w", "wait 250", "key space", "wait 450", "release w"]` (jump while already moving);
   - sprint in games that use Shift: `hold shift` … `release shift`.
3. Camera — relative mouse (`turn`): `["turn 300 0 250"]` rotates right smoothly over 250 ms; negative X = left, Y = up/down.
   Roblox: the camera turns while the right button is held (unless Shift-Lock is on): `["mouse down right", "turn 400 0 300", "mouse up right"]`.
   Calibrate once per game: turn by 300 and compare looks — remember "N px ≈ 90°" in memory for that game.
4. After each act: check the returned image (did the character land? fall?). Fell → respawn is usually automatic; retry with a shorter/longer press.
5. Parkour: approach the edge with short `press w 200` steps, look, then jump with the hold-w pattern; adjust duration by distance.
6. Never type into game chat, never buy anything (Robux/in-game currency), don't interact with other players unless the user asked.
