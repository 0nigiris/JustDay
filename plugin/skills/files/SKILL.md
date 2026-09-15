---
name: files
description: Find, open, create, move, rename and search files and projects on the user's computer, including "the file I worked on yesterday", screenshots, configs, READMEs. Use for any filesystem question.
---

# Files

## Search strategy (fast → slow)
1. Memory (known project/location).
2. Recent activity: `justday recent --hours 48` — KDE activity DB + recently-used files + Claude Code projects with timestamps. Best for "yesterday", "that file I was editing".
3. Filename index: `plocate -i -l 50 <part>` (whole disk, instant; index refreshes daily — add `-e` to drop deleted files). Filter noise: `| grep -vE 'node_modules|/\.cache/|/\.git/|/\.local/share/Steam'`.
4. Fresh/unindexed: `fd -i -H <pattern> ~ --max-depth 6 -E node_modules -E .cache`.
5. Content: `rg -i -l "<text>" <dir> -g '!node_modules'` (scope to a directory, not the whole home).
6. Modified recently: `fd . ~ -t f --changed-within 1d -E .cache -E .local -E .var | head -50`.

Typical places: projects in `~` root (git repos), `~/Documents`, `~/Downloads`, screenshots in `~/Pictures/Screenshots` (Spectacle), configs `~/.config/<app>`, flatpak data `~/.var/app/<id>`, Steam `~/.local/share/Steam`.
Screenshot "taken yesterday": `fd -e png -e jpg --changed-within 2d . ~/Pictures`.

## Acting
- Open: `xdg-open <file>`; show in file manager: `dolphin --select <file> &`.
- Create/edit: normal Write/Edit tools.
- Move/rename: `mv -n` (never overwrite silently).
- Delete: `gio trash <paths>` (recoverable). Permanent deletion only on explicit request; it will require confirmation.
- When you discover a useful location (project dir, config, game folder), save it to memory.
