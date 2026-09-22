---
name: software
description: Install, remove, update or look up software ("установи OBS", "удали телеграм", "обнови всё", "откуда стоит дискорд") through JII (Just Install It) — it searches DNF, COPR, Flatpak, GitHub releases, cargo, pipx… at once, picks the most trusted source and asks for root only through the system password dialog.
---

# Software (JII)

`jii` must be on PATH (`command -v jii`). If it is not, say so and offer the one-liner from https://github.com/0nigiris/JII (the user runs it); for a single package you may fall back to `flatpak install --user flathub <id>` or `sudo dnf install` (asks the user).

Always pass `--json`, never pipe jii into `head` (a closed pipe makes it exit 101), and give installs/updates a long timeout (600000 ms): Flatpaks and dnf transactions often take minutes.

## Install
1. **Find the real package name first.** JII searches by exact name, and a vague name matches junk: `obs` → an unrelated cargo crate, `telegram` → an empty PyPI package. Translate what the user said into the project's package name/ID: OBS → `obs-studio`, Telegram → `telegram-desktop` (or Flatpak `org.telegram.desktop`), Discord → `discord`, VS Code → `code`, Яндекс Браузер → `ru.yandex.Browser`. Not sure → `jii search <name> --json` (JSON list: `source_id`, `trust`, `version`, `suspicious`) and pick the entry that is clearly the app.
2. **Preview:** `jii install <name> --dry-run --auto --json`. Read the plan line: `source`, `reasons`, `needs_root`. Stop and rethink if there is an `"level":"error"` line (JII flags an obscure look-alike) or the source/summary does not match the app — search again with the precise name, or force a source: `<name>:flatpak`, `<name>:dnf`.
3. **Install:** `jii install <name> --auto --json` with a Bash `description` the user sees on the island. `needs_root: true` → the system asks for the user's password in its own dialog; write the description as "Устанавливаю OBS — подтвердите паролем в окне системы" so they know to look. Never type or ask for the password yourself.
   - `--auto` installs only trusted sources (official / community). An untrusted pick is refused: tell the user which source it was and why (reasons), and that they can install it themselves in a terminal (`jii <name>:<source>`). Do not try to get around it.
   - Just installed and the user wanted to use it → `justday apps launch <name>`.
4. Reply in one short sentence: what, from where, version ("Поставил OBS 31 из репозитория Fedora").

Several apps → one command: `jii install a b c --auto --json`.

## Remove, update, explain
- Remove: `jii remove <name> --json` — uses the manager that installed it. The user is asked to confirm (it is a destructive action); say what will be removed in the request.
- Update one: `jii update <name> --json`. Update everything: `jii update --json` (system upgrade + Flatpak + pipx/npm/brew, and JII itself); preview first with `--dry-run` and say in one sentence what it will touch — it is long and may need the password dialog.
- Anything that takes minutes — `jii update --json`, a big install — runs as a background job so the assistant stays free: `justday job start "Обновление системы" -- jii update --json`, then end the turn with one sentence. The daemon reports when it ends (`justday job log ID` for the whole log).
- Where did it come from / why that source: `jii how <name> --json`. Details, versions, trust: `jii info <name> --json`. Installed via JII: `jii list --json`; history: `jii history --json`.
- Installed without JII (Steam games, AppImages, older installs) is still found by `justday apps find <name>`, `rpm -q`, `flatpak list`.

## Don't
- `jii doctor`, `jii setup`, `jii sources add|remove|disable` — interactive or change the system's package setup; leave them to the user (explain what to run).
- `-y`/`--yes` on remove or system update, or `allow_untrusted_auto` in `~/.config/jii/config.toml` — never.
