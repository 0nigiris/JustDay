#!/usr/bin/env bash
# Screenshots for the README: the island in its main states, in an isolated headless KWin.
#   tests/ui/readme_shots.sh WORKDIR WALLPAPER.png [VIDEO_THUMB.jpg] [COVER.jpg] [CLIP.mp4]
# Needs kwin-mcp (uv tool install kwin-mcp). Results: WORKDIR/<scene>.png (1600×900) and
# WORKDIR/island-<scene>.png — cut around the island, as in docs/assets.
set -euo pipefail
repo=$(cd "$(dirname "$0")/../.." && pwd)
J=$(realpath -m "$1"); WALL=$(realpath "$2"); THUMB=${3:+$(realpath "$3")}; COVER=${4:+$(realpath "$4")}; CLIP=${5:+$(realpath "$5")}
mkdir -p "$J"
cat > "$J/hello.json" <<'EOF'
{"state": "idle", "workers": 0,
 "settings": {"provider": "claude", "model": "sonnet", "assistant_name": "Джарвис", "language": "ru", "earcons": true,
   "notifications": true, "wakeword": true, "mail": true, "mail_announce": true, "accessibility": true,
   "island": {"animations": "spring", "show_weather": true, "show_events": true, "show_notifications": true},
   "microphone": true, "voice": true,
   "hotkeys": {"talk": "Meta+J", "extra": "F19", "cancel": "Meta+Shift+J", "type": "Meta+K", "yes": "Meta+Y", "no": "Meta+N"},
   "media": {"video_where": "ask", "show_player": true, "volume": 70, "duck": true}},
 "history": [{"ts": "14:52", "q": "поставь OBS", "a": "OBS Studio установлен с Flathub."},
             {"ts": "14:40", "q": "нарисуй обои с космосом", "a": "Готово, обои в Изображениях."},
             {"ts": "14:31", "q": "что у меня завтра", "a": "Завтра в 10:00 созвон с Ильёй."}],
 "weather": {"temp": 18, "text": "Малооблачно", "icon": "cloud-sun"}}
EOF
python3 "$repo/tests/ui/fake_daemon.py" "$J/fake.sock" "$J/events.fifo" "$J/hello.json" > "$J/fake.log" 2>&1 &
fake=$!
JUSTDAY_ISLAND_WALLPAPER="$WALL" "$(uv tool dir)/kwin-mcp/bin/python" "$repo/tests/ui/island_session.py" "$J" > "$J/session.log" 2>&1 &
sleep 8
pid=$(qs list --all | awk -v d="wayland-mcp" '/Process ID/ {p=$3} /Display connection/ && $0 ~ d {print p}' | tail -1)

ev() { printf '%s\n' "$1" > "$J/events.fifo"; }  # printf: zsh's echo would expand \n inside the JSON
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
ev '{"state":"thinking"}'; ev '{"kind":"heard","detail":"какая завтра погода в Праге"}'; sleep 0.8
ev '{"kind":"tool","detail":"Ищу в интернете: погода в Праге завтра","icon":"system-search"}'; shot thinking
ev '{"state":"speaking"}'
ev '{"kind":"say","detail":"Завтра в Праге до двадцати одного градуса и солнечно. В календаре одна встреча: в десять утра созвон с Ильёй."}'
shot answer
ev '{"state":"idle"}'; sleep 0.5
ev '{"kind":"compose","text":"Объясни простыми словами и переведи на русский","context":{"selection":"Retrieval-augmented generation combines a language model with a search index so answers can cite fresh sources."}}'
shot compose
echo "key Escape" > "$J/ctl"; sleep 0.8
ev '{"kind":"compose","text":"/"}'; shot slash
echo "key Escape" > "$J/ctl"; sleep 0.8
if [[ -n "$THUMB" ]]; then
  ev "{\"kind\":\"card\",\"card\":{\"type\":\"media\",\"kind\":\"video\",\"label\":\"видео\",\"file\":\"$THUMB\",\"name\":\"2026-09-19 kitten.mp4\",\"thumb\":\"$THUMB\"}}"
  shot media 2.2
  ev '{"kind":"card_close"}'; sleep 0.6
fi
ev '{"kind":"card","card":{"type":"message_draft","to":"Илья","via":"Discord","body":"Привет! Когда сможешь поиграть? Я свободен после шести."}}'
shot message 2
ev '{"kind":"card_close"}'; sleep 0.6
if [[ -n "$COVER" ]]; then
  ev "{\"player\":{\"title\":\"Believer\",\"artist\":\"Imagine Dragons\",\"thumb\":\"$COVER\",\"color\":\"#c0662b\",\"file\":\"/x.m4a\",\"pos\":78,\"duration\":203,\"paused\":false,\"index\":1,\"count\":6,\"next\":\"Thunder\",\"volume\":70,\"loading\":null,\"repeat\":\"one\",\"shuffle\":true,\"source\":\"Evolve\",\"queue\":[{\"i\":0,\"title\":\"Next To Me\",\"artist\":\"Imagine Dragons\"},{\"i\":1,\"title\":\"Believer\",\"artist\":\"Imagine Dragons\",\"thumb\":\"$COVER\"},{\"i\":2,\"title\":\"Thunder\",\"artist\":\"Imagine Dragons\"},{\"i\":3,\"title\":\"Whatever It Takes\",\"artist\":\"Imagine Dragons\"},{\"i\":4,\"title\":\"Walking The Wire\",\"artist\":\"Imagine Dragons\"},{\"i\":5,\"title\":\"Rise Up\",\"artist\":\"Imagine Dragons\"}]}}"
  shot music 1.8
  echo "click 800 28" > "$J/ctl"; sleep 2
  g=$(ipc status | python3 -c 'import json,sys; x,y,w,h,_=json.load(sys.stdin)["island"]; print(int(300+x+18+60), int(y+h-33))')
  echo "click $g" > "$J/ctl"; shot player 2   # with the queue open
  echo "key Escape" > "$J/ctl"; sleep 0.8
fi
ev '{"kind":"notification","notification":{"app":"Telegram","icon":"org.telegram.desktop","desktop":"org.telegram.desktop","summary":"Илья","body":"Привет! Ты завтра сможешь поиграть? Я думал после шести собраться в Minecraft: у нас там недостроенный замок, и ещё хочу показать мод, который нашёл вчера. Если не сможешь — напиши, перенесём на субботу."}}'
sleep 1.4
g=$(ipc status | python3 -c 'import json,sys; x,y,w,h,_=json.load(sys.stdin)["island"]; print(int(300+x+w-12-28-8-14), 35)')
echo "click $g" > "$J/ctl"; shot notification 1.6
g=$(ipc status | python3 -c 'import json,sys; x,y,w,h,_=json.load(sys.stdin)["island"]; print(int(300+x+w-12-14), 35)')
echo "click $g" > "$J/ctl"; sleep 0.8   # ✕
if [[ -n "$CLIP" ]]; then
  ev "{\"kind\":\"card\",\"card\":{\"type\":\"question\",\"header\":\"Где включить видео?\",\"question\":\"A cat meowing for 20 seconds\\nCat World · 0:20\",\"thumb\":\"${THUMB:-}\",\"options\":[{\"label\":\"В острове\",\"description\":\"прямо здесь, поверх окон\",\"icon\":\"go-top\"},{\"label\":\"В окне\",\"description\":\"отдельный плеер, есть весь экран\",\"icon\":\"window-new\"},{\"label\":\"YouTube\",\"description\":\"в браузере, с комментариями\",\"icon\":\"internet-web-browser\"}]}}"
  shot where 2.4
  ev '{"kind":"card_close"}'; sleep 0.6
  ev "{\"video\":{\"title\":\"A cat meowing for 20 seconds\",\"channel\":\"Cat World\",\"thumb\":\"\",\"file\":\"$CLIP\",\"url\":\"https://www.youtube.com/watch?v=09nyvwzzM3Q\",\"progress\":1}}"
  sleep 3; echo "click 800 200" > "$J/ctl"; shot video 1.2
  ev '{"video":null}'; ev '{"player":null}'; sleep 0.8
fi
ipc expand; shot menu 2
ipc settingsPage general; shot settings 2.5
ipc collapse; sleep 0.5

echo quit > "$J/ctl"
sleep 2
kill "$fake" 2>/dev/null || true
ls "$J"/*.png
