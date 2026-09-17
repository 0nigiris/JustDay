#!/usr/bin/env bash
# Screenshots for the README: the island in its main states, in an isolated headless KWin.
#   tests/ui/readme_shots.sh WORKDIR WALLPAPER.png [VIDEO_THUMB.jpg]
# Needs kwin-mcp (uv tool install kwin-mcp). Results: WORKDIR/<scene>.png (1600×900).
set -euo pipefail
repo=$(cd "$(dirname "$0")/../.." && pwd)
J=$(realpath -m "$1"); WALL=$(realpath "$2"); THUMB=${3:+$(realpath "$3")}
mkdir -p "$J"
cat > "$J/hello.json" <<'EOF'
{"state": "idle", "workers": 0,
 "settings": {"provider": "claude", "model": "sonnet", "assistant_name": "Джарвис", "language": "ru", "earcons": true,
   "notifications": true, "wakeword": true, "mail": true, "mail_announce": true, "accessibility": true,
   "island": {"animations": "spring", "show_weather": true, "show_events": true, "show_notifications": true},
   "microphone": true, "voice": true,
   "hotkeys": {"talk": "Meta+J", "extra": "F19", "cancel": "Meta+Shift+J", "type": "Meta+K", "yes": "Meta+Y", "no": "Meta+N"}},
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

ev() { echo "$1" > "$J/events.fifo"; }
shot() { sleep "${2:-1.6}"; echo "shot $1" > "$J/ctl"; sleep 0.9; }
ipc() { qs ipc --pid "$pid" call island "$@"; }

ipc peek; shot peek
ev '{"state":"listening","level":0.1}'
for _ in 1 2 3 4 5 6 7 8; do ev "{\"level\":0.$((RANDOM % 7 + 2))}"; sleep 0.08; done
echo "shot listening" > "$J/ctl"; sleep 1
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
  ev "{\"kind\":\"card\",\"card\":{\"type\":\"media\",\"kind\":\"video\",\"label\":\"видео\",\"file\":\"$THUMB\",\"name\":\"2026-09-17 red sports car.mp4\",\"thumb\":\"$THUMB\"}}"
  shot media 2.2
  ev '{"kind":"card_close"}'; sleep 0.6
fi
ev '{"kind":"card","card":{"type":"message_draft","to":"Илья","via":"Discord","body":"Привет! Когда сможешь поиграть? Я свободен после шести."}}'
shot message 2
ev '{"kind":"card_close"}'; sleep 0.6
ipc expand; shot menu 2
ipc settingsPage general; shot settings 2.5
ipc collapse; sleep 0.5

echo quit > "$J/ctl"
sleep 2
kill "$fake" 2>/dev/null || true
ls "$J"/*.png
