---
name: media
description: Play music and videos — "включи песню/трек/музыку …", "поставь что-нибудь для учёбы", "включи видео/ролик/клип про …", pause, next, volume of JustDay's own player. Music is found on YouTube, downloaded and played in JustDay's player on the Dynamic Island; videos play in the island, a window or on YouTube (the user is asked where). Use this instead of opening YouTube in the browser for listening/watching.
---

# Music and video (`justday play` / `justday video` / `justday player`)

JustDay has its own player. Don't open YouTube in the browser to *play* something — use these commands.
Each prints JSON (`ok`, `title`, `done`). The island already shows what plays (cover, bars, a player on click).
**After starting music or a video say NOTHING** — no "включено", no "играет …", no artist or title: your final
reply is empty (the done chime is enough). If you picked the wrong thing, the user will say so. Speak only on an
error ("не нашёл …") or when the user asked a question. Never read file paths aloud.

## Music
| Want | Command |
|---|---|
| a song | `justday play "Imagine Dragons Believer"` — write the query as it would be on YouTube (artist + title in their original language/spelling: «имэджин драгонс» → `Imagine Dragons`) |
| an album / a playlist / "best of" | `justday play "Linkin Park Meteora" playlist=1` — the whole album in order (official uploads preferred); a YouTube playlist link works too |
| shuffled | add `shuffle=1` («включи вперемешку …», «перемешай») |
| several songs / an artist / a mood | `justday play "Linkin Park" count=8`, `justday play "lofi hip hop for studying" count=10` — the first starts in ~3 s, the rest queue up in the background |
| add to the queue | `… add=1` (after the queue) · `… next=1` (right after the current song) |
| a local file or a folder | `justday play ~/Music/album` |
| a YouTube link | `justday play "https://youtu.be/…"` |
| control | `justday player pause \| resume \| toggle \| next \| prev \| restart \| stop` |
| jump / volume | `justday player seek 90` · `justday player volume 40` (the player's own level, 0–130) |
| repeat | `justday player repeat one` (this song, «на повтор») · `repeat all` (the whole queue) · `repeat off` |
| shuffle | `justday player shuffle on` / `off` |
| a song from the queue | `justday player jump 4` (index from `status` → `queue`) |
| what is playing | `justday player status` |

Songs are saved to ~/Music/JustDay/YouTube and play from disk next time (offline too).
Artist without a song («включи Linkin Park») → their top songs: `count=15`. An album («альбом Meteora») → `playlist=1`.
"включи что-нибудь" without a hint: pick by the time of day and what the user usually likes (memory), count=10, and name the choice in 3–5 words.
System volume ("громче", "тише") is `wpctl`, not the player.

## Video
`justday video "what to find or a link"` — finds the video and **asks the user where to play it** (the island shows three buttons: in the island, in a window, on YouTube; the user can also answer by voice). Wait for it; it returns `where`.
If the user already said where («в окне», «на ютубе», «прямо тут», «на весь экран» = window): `where=island|window|browser`.
Local video files: `justday video ~/Videos/clip.mp4 where=window`.
In the island a video downloads first (≤720p; ~10–30 s for a clip, longer for long videos — say so for >20 min videos); window and YouTube start at once.
Pause / resume / close a video in the island: `justday player pause|resume|stop`.

Choosing a video: tutorials and lectures → reputable channels, sane length; "клип" = the official music video.
