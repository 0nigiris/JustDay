---
name: claude-code
description: Delegate coding work to Claude Code and supervise it — open Claude Code, run it in a project, give it tasks, continue/resume sessions, check what it changed, run tests, review diffs, push follow-ups, stop it. Also how to react to "[Событие JustDay]" worker events.
---

# Claude Code as JustDay's engineer

You (JustDay) are the dispatcher and reviewer. Claude Code worker sessions do the coding. All via the official CLI, wrapped by `justday claude`:

| Intent | Command |
|---|---|
| "Open Claude Code (in X)" — visible interactive session | `justday claude open --cwd <dir>` |
| Give Claude a task (runs in background) | `justday claude start --cwd <dir> "<prompt>"` → returns `id` |
| What is running / recent sessions | `justday claude list` |
| What did it do / its final message / edited files | `justday claude result <id>` |
| Follow-up / continue / fix failures / resume | `justday claude send <id> "<message>"` |
| Wait for completion (only for short tasks) | `justday claude wait <id> --timeout 600` |
| Show a worker on screen | `justday claude open <id>` |
| Stop it | `justday claude stop <id>` |
| Quick read-only question, answer needed now | `cd <dir> && timeout 300 claude -p "<question>" --output-format json` (use `.result`) |

Model override: `--model opus|sonnet` on `start` (default = user's Claude Code default).

## Finding the project
"my project", "the game launcher", "what we worked on yesterday": check memory first, then `justday recent` (Claude projects + recent files), then `plocate -i <name> | grep -v node_modules | head`, `fd -t d -i <name> ~ -d 4`. Confirm the choice in a few words when not obvious ("Беру проект Notes.").
Before starting: `git -C <dir> status --short` and note uncommitted changes (tell the user if there are many unrelated ones).

## Writing the worker prompt
Write it like a good ticket (in the language the user speaks):
- Goal and the user's words; relevant context you know (paths, errors, what was tried).
- Constraints: keep changes minimal, follow project conventions, no git commit/push (JustDay adds this automatically).
- Definition of done + how to verify (which tests/commands to run; add a test when fixing a bug).
Never paste secrets.

## Supervising loop
1. `start` → say one short line ("Клод взялся за задачу, доложу, когда закончит.") and end your turn; do not block on long tasks.
2. The daemon polls sessions and sends you "[Событие JustDay] … состояние «done|blocked|failed|stopped»".
3. On `done`: `justday claude result <id>`; `git -C <dir> diff --stat` and read the relevant diff; run the project's tests/build/lint (detect: package.json scripts, Cargo.toml → `cargo test`, pyproject/pytest, Makefile, go.mod). Judge whether the goal is met.
   - Not met / tests fail → `justday claude send <id> "<precise feedback with failing output excerpt>"`. At most 3 automatic rounds per user request, then report and ask.
   - Met → report in 1–2 sentences: what changed, tests status.
4. On `blocked`: read `waiting_for` via `result`. Permission prompt or question → decide if it is safe and within the user's request; answer via `send` (the stopped session resumes with your message) or ask the user. Open it visibly (`justday claude open <id>`) if the user must interact.
5. On `failed`: read result/transcript tail, retry once with an adjusted prompt, otherwise report.

## "Check Claude's work" / "what did it change" / "run the tests" / "review the diff"
Do it yourself: `git -C <dir> status`, `git diff`, run tests, read changed files. Report concise verdict with numbers ("Изменено 3 файла, 147 тестов прошли").

## Continue yesterday's work
Look at `justday claude list` (includes finished sessions), `justday recent`, and the JustDay journal (`~/.local/state/justday/events.jsonl`, kinds request/say/worker_start). Resume the matching session with `send`.
