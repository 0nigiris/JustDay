---
name: browser
description: Web and browser tasks — open sites, web search, YouTube search and playing a video, reading pages, clicking/filling forms in the user's logged-in browser, downloads. Use whenever the request involves the internet or a website.
---

# Browser & web

Pick the lightest tool that does the job:

| Need | Tool |
|---|---|
| Answer a question from the internet | `WebSearch` / `WebFetch` (no browser window) |
| Just open a site / search page for the user | `xdg-open "<url>"` (default browser) |
| Find and play a YouTube video | `yt-dlp` search → `xdg-open` watch URL |
| Multi-step interaction, logged-in sites, forms, reading a live page | `claude-in-chrome` MCP tools |
| Download a file | `curl -L --fail -o ~/Downloads/<name> "<url>"` |

## YouTube
- Search results page: `xdg-open "https://www.youtube.com/results?search_query=<url-encoded query>"`.
- Play the best match directly:
  `yt-dlp --flat-playlist --print "%(id)s | %(title)s | %(channel)s | %(duration_string)s | %(view_count)s" "ytsearch8:<query>"`
  Pick by relevance, recency, views and sane duration (tutorials: prefer 10–60 min, reputable channels), then
  `xdg-open "https://www.youtube.com/watch?v=<id>"` — it autoplays. Tell the user the title in one sentence.
- Pause/resume afterwards: `playerctl play-pause` (browser media is exposed over MPRIS).

## claude-in-chrome (user's real browser with their logins)
1. `tabs_context_mcp` first (use `createIfEmpty: true` if there is no group), then `tabs_create_mcp` for a new tab.
2. `navigate`, then `get_page_text` / `find` / `read_page` to understand the page — do not guess coordinates.
3. Interact with `computer` (click/type/key), `form_input`; `file_upload` to attach local files.
4. Re-read the page after each significant action; if the layout changed, adapt.
5. Login pages / CAPTCHAs: stop and ask the user to handle them. Never type passwords or payment data.
6. Avoid clicking things that open JS alert/confirm dialogs; they freeze the extension.
If the extension is not connected, fall back to `xdg-open` + kwin `look`/`act`, and tell the user that the Claude extension in the browser needs reconnecting.

## Forms & purchases
Fill forms only when the user asked for that outcome. Before a final irreversible submit (sending, posting, ordering) state briefly what will be submitted and get a yes. Never pay.
