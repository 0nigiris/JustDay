#!/usr/bin/env bash
# Screenshots for the README: the island in its main states, in an isolated headless KWin.
#   SHOTS_LANG=ru|en tests/ui/readme_shots.sh WORKDIR WALLPAPER.png [VIDEO_THUMB.jpg] [COVER.jpg] [CLIP.mp4]
# Needs kwin-mcp (uv tool install kwin-mcp). Results: WORKDIR/<scene>.png (1600×900) and
# WORKDIR/island-<scene>.png — cut around the island, as in docs/assets (ru) and docs/assets/en (en).
#
# Everything shown is the default setup, not the machine the script runs on: the island gets the
# settings a fresh install has, and the Settings window reads an empty config directory of its own.
set -euo pipefail
repo=$(cd "$(dirname "$0")/../.." && pwd)
J=$(realpath -m "$1"); WALL=$(realpath "$2"); THUMB=${3:+$(realpath "$3")}; COVER=${4:+$(realpath "$4")}; CLIP=${5:+$(realpath "$5")}
LANG_=${SHOTS_LANG:-ru}
L() { if [[ $LANG_ == en ]]; then printf '%s' "$2"; else printf '%s' "$1"; fi; }   # L "по-русски" "in English"
mkdir -p "$J" "$J/config/justday"
NAME=$(L "Джарвис" "Jarvis"); ADDR=$(L "сэр" "sir")

# a fresh install's config, for the Settings window (it asks `justday settings-data`, which reads it)
cat > "$J/config/justday/config.toml" <<EOF
[user]
language = "$LANG_"
assistant_name = "$NAME"
address_as = "$ADDR"
[stt]
language = "$LANG_"
EOF

python3 - "$J/hello.json" "$LANG_" "$NAME" <<'PY'
import json, sys
path, lang, name = sys.argv[1:]
ru = lang == "ru"
hello = {
    "state": "idle", "workers": 0,
    "settings": {"provider": "claude", "model": "sonnet", "assistant_name": name, "language": lang, "earcons": True,
                 "notifications": True, "wakeword": False, "mail": False, "mail_announce": True, "accessibility": True,
                 "island": {"animations": "spring", "show_weather": True, "show_events": True, "show_notifications": True},
                 "microphone": True, "voice": True, "volume": 100, "tts_engine": "silero",
                 "hotkeys": {"talk": "Meta+J", "extra": "F19", "cancel": "Meta+Shift+J", "type": "Meta+K", "yes": "Meta+Y", "no": "Meta+N"},
                 "media": {"video_where": "ask", "show_player": True, "volume": 70, "duck": True, "color": "theme"}},
    "history": [{"ts": "14:52", "q": "поставь OBS" if ru else "install OBS",
                 "a": "OBS Studio установлен с Flathub." if ru else "OBS Studio is installed from Flathub."},
                {"ts": "14:40", "q": "нарисуй обои с космосом" if ru else "draw me a space wallpaper",
                 "a": "Готово, обои в Изображениях." if ru else "Done, the wallpaper is in Pictures."},
                {"ts": "14:31", "q": "что у меня завтра" if ru else "what do I have tomorrow",
                 "a": "Завтра в 10:00 созвон с Ильёй." if ru else "A call with Ilya tomorrow at 10:00."}],
    "weather": {"temp": 18, "text": "Малооблачно" if ru else "Partly cloudy", "icon": "cloud-sun"},
}
json.dump(hello, open(path, "w"), ensure_ascii=False)
PY
python3 "$repo/tests/ui/fake_daemon.py" "$J/fake.sock" "$J/events.fifo" "$J/hello.json" > "$J/fake.log" 2>&1 &
fake=$!
JUSTDAY_SHOTS_CONFIG_HOME="$J/config" JUSTDAY_ISLAND_WALLPAPER="$WALL" \
  "$(uv tool dir)/kwin-mcp/bin/python" "$repo/tests/ui/island_session.py" "$J" > "$J/session.log" 2>&1 &
sleep 8
pid=$(qs list --all | awk -v d="wayland-mcp" '/Process ID/ {p=$3} /Display connection/ && $0 ~ d {print p}' | tail -1)

ev() { printf '%s\n' "$1" > "$J/events.fifo"; }  # printf: zsh's echo would expand \n inside the JSON
js() { python3 -c 'import json,sys; print(json.dumps(sys.argv[1], ensure_ascii=False))' "$1"; }   # a JSON string
ipc() { qs ipc --pid "$pid" call island "$@"; }
# the island's box on screen (the window is 1000 px wide, centred on the 1600 px screen) + a margin of wallpaper
cut() {
  local g; g=$(ipc status | python3 -c 'import json,sys; x,y,w,h,_=json.load(sys.stdin)["island"]; print(int(300+x-46), int(w+92), int(y+h+46))')
  set -- "$1" $g
  ffmpeg -v error -y -i "$J/$1.png" -vf "crop=$3:$4:$2:0" "$J/island-$1.png"
}
shot() { sleep "${2:-1.6}"; echo "shot $1" > "$J/ctl"; sleep 0.9; cut "$1"; }

ipc peek; shot peek
ev '{"state":"listening","level":0.1}'
for _ in 1 2 3 4 5 6 7 8; do ev "{\"level\":0.$((RANDOM % 7 + 2))}"; sleep 0.08; done
echo "shot listening" > "$J/ctl"; sleep 1; cut listening
ev '{"state":"thinking"}'; ev "{\"kind\":\"heard\",\"detail\":$(js "$(L 'какая завтра погода в Праге' "what's the weather in Prague tomorrow")")}"; sleep 0.8
ev "{\"kind\":\"tool\",\"detail\":$(js "$(L 'Ищу в интернете: погода в Праге завтра' 'Searching the web: Prague weather tomorrow')"),\"icon\":\"system-search\"}"; shot thinking
ev '{"state":"speaking"}'
ev "{\"kind\":\"say\",\"detail\":$(js "$(L 'Завтра в Праге до двадцати одного градуса и солнечно. В календаре одна встреча: в десять утра созвон с Ильёй.' 'Tomorrow in Prague it is up to 21 degrees and sunny. One meeting on the calendar: a call with Ilya at 10 am.')")}"
shot answer
ev '{"state":"idle"}'; sleep 0.5
ev "{\"kind\":\"compose\",\"text\":$(js "$(L 'Объясни простыми словами и переведи на русский' 'Explain this in plain words')"),\"context\":{\"selection\":\"Retrieval-augmented generation combines a language model with a search index so answers can cite fresh sources.\"}}"
shot compose
echo "key Escape" > "$J/ctl"; sleep 0.8
ev '{"kind":"compose","text":"/"}'; shot slash
echo "key Escape" > "$J/ctl"; sleep 0.8
if [[ -n "$THUMB" ]]; then
  ev "{\"kind\":\"card\",\"card\":{\"type\":\"media\",\"kind\":\"video\",\"label\":$(js "$(L видео video)"),\"file\":\"$THUMB\",\"name\":\"2026-09-19 kitten.mp4\",\"thumb\":\"$THUMB\"}}"
  shot media 2.2
  ev '{"kind":"card_close"}'; sleep 0.6
fi
ev "{\"kind\":\"card\",\"card\":{\"type\":\"message_draft\",\"to\":$(js "$(L Илья Ilya)"),\"via\":\"Discord\",\"body\":$(js "$(L 'Привет! Когда сможешь поиграть? Я свободен после шести.' "Hey! When can you play? I'm free after six.")")}}"
shot message 2
ev '{"kind":"card_close"}'; sleep 0.6
if [[ -n "$COVER" ]]; then
  ev "{\"player\":{\"title\":\"Believer\",\"artist\":\"Imagine Dragons\",\"thumb\":\"$COVER\",\"color\":\"#c0662b\",\"file\":\"/x.m4a\",\"pos\":78,\"duration\":203,\"paused\":false,\"index\":1,\"count\":6,\"next\":\"Thunder\",\"volume\":70,\"loading\":null,\"repeat\":\"one\",\"shuffle\":true,\"source\":\"Evolve\",\"queue\":[{\"i\":0,\"title\":\"Next To Me\",\"artist\":\"Imagine Dragons\"},{\"i\":1,\"title\":\"Believer\",\"artist\":\"Imagine Dragons\",\"thumb\":\"$COVER\"},{\"i\":2,\"title\":\"Thunder\",\"artist\":\"Imagine Dragons\"},{\"i\":3,\"title\":\"Whatever It Takes\",\"artist\":\"Imagine Dragons\"},{\"i\":4,\"title\":\"Walking The Wire\",\"artist\":\"Imagine Dragons\"},{\"i\":5,\"title\":\"Rise Up\",\"artist\":\"Imagine Dragons\"}]}}"
  shot music 1.8
  echo "click 800 28" > "$J/ctl"; sleep 2
  g=$(ipc status | python3 -c 'import json,sys; x,y,w,h,_=json.load(sys.stdin)["island"]; print(int(300+x+18+42), int(y+18+42))')
  echo "click $g" > "$J/ctl"; shot cover 2    # a tap on the cover: the cover, large
  echo "click $g" > "$J/ctl"; sleep 1.2       # and back
  g=$(ipc status | python3 -c 'import json,sys; x,y,w,h,_=json.load(sys.stdin)["island"]; print(int(300+x+18+60), int(y+h-33))')
  echo "click $g" > "$J/ctl"; shot player 2   # with the queue open
  echo "key Escape" > "$J/ctl"; sleep 0.8
  ipc expand; shot menu 2                     # the menu while music plays: the card and three volumes
  ipc collapse; sleep 0.8
  ev '{"player":null}'; sleep 0.8
fi
ev "{\"kind\":\"notification\",\"notification\":{\"app\":\"Telegram\",\"icon\":\"org.telegram.desktop\",\"desktop\":\"org.telegram.desktop\",\"summary\":$(js "$(L Илья Ilya)"),\"body\":$(js "$(L 'Привет! Ты завтра сможешь поиграть? Я думал после шести собраться в Minecraft: у нас там недостроенный замок, и ещё хочу показать мод, который нашёл вчера. Если не сможешь — напиши, перенесём на субботу.' "Hey! Can you play tomorrow? I was thinking Minecraft after six: our castle is still half built, and I want to show you a mod I found yesterday. If you can't, text me and we'll move it to Saturday.")")}}"
sleep 1.4
g=$(ipc status | python3 -c 'import json,sys; x,y,w,h,_=json.load(sys.stdin)["island"]; print(int(300+x+w-12-28-8-14), 35)')
echo "click $g" > "$J/ctl"; shot notification 1.6
g=$(ipc status | python3 -c 'import json,sys; x,y,w,h,_=json.load(sys.stdin)["island"]; print(int(300+x+w-12-14), 35)')
echo "click $g" > "$J/ctl"; sleep 0.8   # ✕
if [[ -n "$CLIP" ]]; then
  where=$(python3 - "$LANG_" "${THUMB:-}" <<'PY'
import json, sys
ru = sys.argv[1] == "ru"
print(json.dumps({"kind": "card", "card": {"type": "question",
    "header": "Где включить видео?" if ru else "Where should the video play?",
    "question": "A cat meowing for 20 seconds\nCat World · 0:20", "thumb": sys.argv[2],
    "options": [{"label": "В острове" if ru else "In the island", "description": "прямо здесь, поверх окон" if ru else "right here, above the windows", "icon": "go-top"},
                {"label": "В окне" if ru else "In a window", "description": "отдельный плеер, есть весь экран" if ru else "its own player, full screen too", "icon": "window-new"},
                {"label": "YouTube", "description": "в браузере, с комментариями" if ru else "in the browser, with comments", "icon": "internet-web-browser"}]}}, ensure_ascii=False))
PY
)
  ev "$where"
  shot where 2.4
  ev '{"kind":"card_close"}'; sleep 0.6
  ev "{\"video\":{\"title\":\"A cat meowing for 20 seconds\",\"channel\":\"Cat World\",\"thumb\":\"\",\"file\":\"$CLIP\",\"url\":\"https://www.youtube.com/watch?v=09nyvwzzM3Q\",\"progress\":1}}"
  sleep 3; echo "click 800 200" > "$J/ctl"; shot video 1.2
  ev '{"video":null}'; sleep 0.8
fi
[[ -n "$COVER" ]] || { ipc expand; shot menu 2; }
ipc settingsPage general; shot settings 2.5
ipc settingsPage character; shot character 2.5
ipc collapse; sleep 0.5

echo quit > "$J/ctl"
sleep 2
kill "$fake" 2>/dev/null || true
ls "$J"/*.png
