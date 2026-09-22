---
name: studio
description: Create and edit media on the local GPU — pictures ("нарисуй", "сделай фото/обои/логотип/иконку"), photo edits, upscaling, background removal, video from text or from a photo ("оживи фото"), music and beats, 3D models (GLB/STL), voice-over, subtitles, and montage (cut, join, music under video, burned-in subtitles, vertical shorts, remove pauses, speed, GIF, slideshow). Free and private — nothing leaves the computer.
---

# Studio (`justday studio …`)

Everything runs locally. Never mention model or engine names to the user — say what you made, not how.
`justday studio status` shows what this computer can do (`can.image`, `can.video` … false → that part is not installed; say so in one sentence, don't try to install tens of GB without a clear "yes").
Every command prints JSON: `state` done / running / failed, `file` = the result. When a file is ready, a card with a preview and "Open" already appears on the island — **don't** open the file yourself unless asked, and don't read the path aloud.

## Prompts
Write generation prompts **in English**, concrete: subject, setting, light, style, camera. Improve the user's words silently (one pass): "кот в космосе" → `a fluffy ginger cat floating in a spacesuit inside a space station, earth in the window, cinematic lighting, detailed, photorealistic`. Text on a picture: put it in quotes inside the prompt. Music `tags` = genre, mood, instruments, bpm (English); lyrics may be in any language with `[verse]` `[chorus]` markers.

## Generation
| Want | Command | Time |
|---|---|---|
| picture | `justday studio image "PROMPT" size=square\|wide\|tall\|banner\|WxH` | ~25 s |
| picture with transparent background (logo, icon, sticker) | `… image "PROMPT" transparent=1` | ~40 s |
| change a photo ("сделай оправу золотой") | `justday studio edit PHOTO "INSTRUCTION in English"` | 1–2 min |
| enlarge ×4 / clean up | `justday studio upscale PHOTO` | ~10 s |
| remove background | `justday studio nobg PHOTO` | ~15 s |
| video from text | `justday studio video "PROMPT with motion" seconds=3 size=wide\|tall\|square` | ~8 min per 3 s |
| bring a photo to life | `justday studio animate PHOTO "what moves, camera motion"` | ~8 min |
| music / beat / song | `justday studio music "TAGS" seconds=30 lyrics="…"` (no lyrics = instrumental) | ~1 min |
| 3D model | `justday studio 3d "OBJECT description"` or `justday studio 3d PHOTO` → .glb + .stl | ~3 min |
| voice-over in your voice | `justday studio speech "TEXT"` (voice=jarvis …) | seconds |

Options everywhere: `out=PATH` (file or folder/), `seed=N` (repeat a variant). Defaults save to ~/Pictures/JustDay, ~/Videos/JustDay, ~/Music/JustDay, ~/Documents/JustDay/3D.

**Long jobs** (video, animate, 3d) return `state: running` + `ready_in_s` at once and continue in the background — tell the user "будет готово минут через N, я скажу", and go on with other requests. When it finishes you get a `[Событие JustDay]` message; then say one sentence. `justday studio jobs` lists jobs, `justday studio job ID wait=60` waits.
Only one heavy job at a time (12 GB GPU): don't start a second video while one is running — queue it after the first.

## Quality check
After a picture, look at it (Read the PNG) when the request was specific (text on it, a count of objects, a likeness): if it's clearly wrong — fix the prompt and generate again (at most 2 retries), then give the best one and say in one phrase what didn't come out. Videos and music are not re-checked automatically (too slow) — offer "переделать?" instead.

## Montage (ffmpeg, fast, no GPU)
The user does the creative cut; you do the mechanics they ask for. Input files: find them with `justday recent` / plocate if the user says "последнее видео", "запись с рабочего стола".
| Want | Command |
|---|---|
| video length, size, sound? | `justday studio info FILE` |
| cut a piece | `justday studio cut FILE from=00:01:05 to=00:01:40` |
| glue clips / pictures one after another | `justday studio join A.mp4 B.mp4 pic.png …` |
| music or voice-over under video | `justday studio audio VIDEO MUSIC.mp3 volume=0.3` (`replace=1` = only the new sound) |
| subtitles (.srt + text) from speech | `justday studio subs VIDEO_OR_AUDIO` |
| burn subtitles into the video | `justday studio burn VIDEO [SUBS.srt]` (makes them if missing; `burn=0` = switchable track) |
| vertical 9:16 for Shorts/TikTok/Reels | `justday studio vertical VIDEO` (`mode=crop` = fill the frame) |
| remove pauses | `justday studio nopause VIDEO pause=0.6` |
| speed up / slow down | `justday studio speed VIDEO 1.5` |
| GIF | `justday studio gif VIDEO from=00:00:03 seconds=4 width=480` |
| slideshow from pictures | `justday studio slideshow a.png b.png … each=3 music=track.mp3` |
Results are saved next to the source with a suffix ("… без пауз.mp4"); the original is never overwritten. Anything these don't cover → plain `ffmpeg` (write to a new file).

## Chains
Build them from the pieces, in order, waiting for each: "реклама моих очков" → `image` (product shot) → `animate` it → `music` → `audio` (music under the clip) → `vertical` if it's for shorts. "говорящий ролик по тексту" → `speech` → `image` per paragraph → `slideshow … music=` / `audio replace=1`. Tell the user the plan in one sentence first if it takes more than ~5 minutes.

## If there is no local studio
(`status.engine` is empty — e.g. a computer without an NVIDIA card): montage, subtitles and voice-over still work. For pictures/video/music say that this computer can't generate them locally.
