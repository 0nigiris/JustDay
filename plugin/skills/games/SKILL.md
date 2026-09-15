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
