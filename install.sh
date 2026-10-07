#!/usr/bin/env bash
# JustDay installer — KDE Plasma 6 (Wayland) + Claude Code, and as much as possible everywhere else.
# Usage:  ./install.sh [options]        (from a clone)
#         curl -fsSL https://raw.githubusercontent.com/0nigiris/JustDay/main/install.sh | bash
#
# Options (all optional — without them the installer asks):
#   --everything        speech recognition, the neural voice and NVIDIA acceleration
#   --setup             ask again on an existing install (parts, screen, model, voice)
#   --no-gpu            the same without the 2.2 GB of CUDA libraries
#   --text-only         no microphone, no voice: 250 MB, commands typed
#   --parts a,b,c       exactly these: speech, voice, cuda
#   --yes               do not ask anything, take what fits this computer
#   --debug             show what every tool prints, as it prints it
#   --no-sudo           never ask for the admin password
#   --help
# Environment: JUSTDAY_PARTS, JUSTDAY_DEBUG=1, JUSTDAY_NO_SUDO=1, JUSTDAY_YES=1, JUSTDAY_HOTKEY,
#              JUSTDAY_ASK=1 (ask what to install even when something is already installed).
#
# Re-running is safe (idempotent) and picks up where an interrupted run stopped. Everything is
# user-level except missing system packages, for which sudo is asked once, with the list shown first.
#
# One line per step, with what it is doing now next to it. The full output of every tool goes to
# ~/.local/state/justday/install.log, and with --debug also to the screen.
set -euo pipefail

REPO_URL="${JUSTDAY_REPO_URL:-https://github.com/0nigiris/JustDay.git}"
HOTKEY="${JUSTDAY_HOTKEY:-Meta+J}"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/justday"
mkdir -p "$STATE_DIR"
LOG="$STATE_DIR/install.log"
: > "$LOG"
NOTE=$(mktemp) WARNS=$(mktemp)
STARTED=$SECONDS

# ───────────── what was asked for ─────────────
DEBUG=${JUSTDAY_DEBUG:-0}
ASK=1; [[ "${JUSTDAY_YES:-}" == 1 ]] && ASK=0
WANT="${JUSTDAY_PARTS-}"       # пусто = ещё не выбрано; "-" = ничего необязательного
usage() { sed -n '2,20p' "${BASH_SOURCE[0]:-$0}" | sed 's/^# \{0,1\}//'; exit 0; }
while (($#)); do
  case "$1" in
    --everything|--all|--full) WANT="speech,voice,cuda"; ASK=0 ;;
    --no-gpu|--cpu)           WANT="speech,voice"; ASK=0 ;;
    --text-only|--minimal)    WANT="-"; ASK=0 ;;
    --parts)                  WANT="${2:-}"; ASK=0; shift ;;
    --parts=*)                WANT="${1#*=}"; ASK=0 ;;
    --yes|-y)                 ASK=0 ;;
    # Перенастроить уже установленное: те же вопросы, что при первой установке, включая «что
    # показывать на экране». Без него обновление молча оставляет всё как было — и правильно
    # делает, но человеку нужен способ передумать, не вспоминая названия переменных.
    --setup|--reconfigure)    JUSTDAY_ASK=1; JUSTDAY_SETUP=1 ;;
    --debug|-d)               DEBUG=1 ;;
    --no-sudo)                JUSTDAY_NO_SUDO=1 ;;
    --help|-h)                usage ;;
    *) printf 'unknown option: %s (--help)\n' "$1" >&2; exit 2 ;;
  esac
  shift
done

# ───────────── how it looks ─────────────
TTY=0; [[ -t 1 ]] && TTY=1
if [[ $TTY == 1 && -z "${NO_COLOR:-}" ]]; then
  B=$'\e[1m' D=$'\e[2m' G=$'\e[32m' Y=$'\e[33m' R=$'\e[31m' C=$'\e[36m' N=$'\e[0m'
else
  B='' D='' G='' Y='' R='' C='' N=''
fi
RU=0; [[ "${LC_ALL:-${LC_MESSAGES:-${LANG:-}}}" == ru* ]] && RU=1
t() { if [[ $RU == 1 ]]; then printf '%s' "$1"; else printf '%s' "$2"; fi; }   # t "по-русски" "in English"

SPIN=(⠋ ⠙ ⠹ ⠸ ⠼ ⠴ ⠦ ⠧ ⠇ ⠏)
clock() { local s=$1; if ((s >= 60)); then printf '%d:%02d' $((s / 60)) $((s % 60)); else printf '%d %s' "$s" "$(t с s)"; fi; }
pad() { local n=$(( $2 - ${#1} )); ((n < 2)) && n=2; printf '%s%*s' "$1" "$n" ''; }
row() { # row MARK COLOUR TITLE [DETAIL]
  [[ $TTY == 1 ]] && printf '\r\e[K'
  printf '  %s%s%s  %s%s%s%s\n' "$2" "$1" "$N" "$(pad "$3" 28)" "$D" "${4:-}" "$N"
}
note() { printf '%s' "$*" > "$NOTE"; }            # the grey words after a finished step
warn() { printf '%s\n' "$*" >> "$WARNS"; }        # a line under the step, marked «!»
flush_warns() {
  while IFS= read -r w; do [[ -n "$w" ]] && printf '     %s!%s %s\n' "$Y" "$N" "$w"; done < "$WARNS"
  : > "$WARNS"
}
WIDTH=${COLUMNS:-0}; ((WIDTH > 0)) || WIDTH=$(tput cols 2>/dev/null || echo 80); ((WIDTH > 64)) && WIDTH=64; ((WIDTH < 40)) && WIDTH=40
line() { local n=$((WIDTH - 2)) i s=''; for ((i = 0; i < n; i++)); do s+='─'; done; printf '%s' "$s"; }
plate() { # plate "первая строка" ["вторая, приглушённая"] — рамка вокруг заголовка
  # Ширина считается в символах, а не в байтах: иначе русские строки уезжают за рамку.
  local w=$((WIDTH - 4))
  printf '\n  %s╭%s╮%s\n' "$D" "$(line)" "$N"
  printf '  %s│%s  %s%s%s%s│%s\n' "$D" "$N" "$B" "$(pad "$1" "$w")" "$N" "$D" "$N"
  [[ -n "${2:-}" ]] && printf '  %s│%s  %s%s%s%s│%s\n' "$D" "$N" "$D" "$(pad "$2" "$w")" "$N" "$D" "$N"
  printf '  %s╰%s╯%s\n\n' "$D" "$(line)" "$N"
}
section() { # section "Ставим" — тонкий заголовок группы шагов
  local left="  $B$1$N " rest=$((WIDTH - ${#1} - 1)) i s=''
  ((rest < 3)) && rest=3
  for ((i = 0; i < rest; i++)); do s+='─'; done
  printf '\n%s%s%s%s\n' "$left" "$D" "$s" "$N"
}
hsize() { # hsize 1400 → «1.4 ГБ» / «320 МБ»
  local m=$1
  if ((m >= 1024)); then printf '%d.%d %s' $((m / 1024)) $(((m % 1024) * 10 / 1024)) "$(t ГБ GB)"
  else printf '%d %s' "$m" "$(t МБ MB)"; fi
}
mib() { hsize "$(du -sm "$1" 2>/dev/null | awk '{print $1+0}')"; }   # сколько уже лежит на диске

# Пока шаг идёт, рядом с ним пишется, чем он занят: сначала PROGRESS (если шаг её задал),
# иначе последняя строка журнала. Молчащий спиннер на двадцать минут — это и была та жалоба,
# после которой человек нажал Ctrl+C, решив, что всё повисло.
PROGRESS=""     # имя функции, печатающей одну короткую строку
SIZE_HINT=""    # «~1.5 ГБ» — чтобы долгое скачивание не выглядело зависанием
last_log_line() { tail -n 60 "$LOG" 2>/dev/null | tr -d '\r' | grep -v '^[[:space:]]*$' | grep -v '^── ' | tail -n 1; }
status_line() {
  local line=''
  [[ -n "$PROGRESS" ]] && line=$("$PROGRESS" 2>/dev/null || true)
  [[ -z "$line" ]] && line=$(last_log_line)
  line=${line//$'\t'/ }
  printf '%s' "${line:0:56}"
}

# Прервали на полпути — надо сказать, что уже сделанное никуда не пропало.
JOB=""
on_int() {
  trap - INT TERM
  [[ -n "$JOB" ]] && kill "$JOB" 2>/dev/null || true
  [[ $TTY == 1 ]] && printf '\e[?25h\r\e[K'
  printf '\n  %s%s%s\n' "$Y" "$(t 'Прервано.' 'Interrupted.')" "$N"
  printf '  %s%s%s\n' "$D" "$(t 'Скачанное сохранено: запустите установку ещё раз — она продолжит с этого места.' \
    'What was downloaded is kept: run the installer again and it continues from here.')" "$N"
  printf '  %s%s %s%s\n\n' "$D" "$(t 'Журнал:' 'Log:')" "$LOG" "$N"
  exit 130
}
trap on_int INT TERM
trap 'rm -f "$NOTE" "$WARNS"; if [[ -t 1 ]]; then printf "\e[?25h"; fi' EXIT

# step "Title" function args… — the function's output goes to the log (and, with --debug, to the screen);
# meanwhile the line shows a spinner, the elapsed time and what the step is doing right now.
# ✓ with its note, or ✗ with the end of the log and where the rest is.
# It runs as a background job even without a terminal: that is what keeps `set -e` alive inside it.
step() {
  local title=$1; shift
  : > "$NOTE"
  printf '\n── %s\n' "$title" >> "$LOG"
  local rc=0 start=$SECONDS i=0
  if [[ $DEBUG == 1 ]]; then
    printf '  %s·%s  %s%s%s\n' "$C" "$N" "$(pad "$title" 28)" "$D" "${SIZE_HINT:-}$N"
    "$@" > >(tee -a "$LOG" | sed -u "s/^/       ${D}/; s/\$/${N}/") 2>&1 || rc=$?
    wait 2>/dev/null || true      # дать tee дописать, иначе строки шага перемешаются со следующим
  else
    "$@" >> "$LOG" 2>&1 &
    JOB=$!
    if [[ $TTY == 1 ]]; then
      printf '\e[?25l'
      local live=''
      while kill -0 "$JOB" 2>/dev/null; do
        ((i % 12 == 0)) && live=$(status_line)          # раз в секунду: du и tail не бесплатны
        local el=$((SECONDS - start)) tail_bits=''
        ((el >= 3)) && tail_bits="$(clock "$el")"
        [[ -n "$live" ]] && tail_bits="${live}${tail_bits:+  ·  $tail_bits}"
        [[ -z "$tail_bits" && -n "$SIZE_HINT" ]] && tail_bits="$SIZE_HINT"
        printf '\r\e[K  %s%s%s  %s%s%s%s' "$C" "${SPIN[i++ % 10]}" "$N" "$(pad "$title" 28)" "$D" "$tail_bits" "$N"
        sleep 0.08
      done
      printf '\e[?25h'
    fi
    wait "$JOB" || rc=$?
    JOB=""
  fi
  PROGRESS=""; SIZE_HINT=""
  if ((rc == 0)); then
    row '✓' "$G" "$title" "$(cat "$NOTE")"
    flush_warns
  else
    row '✗' "$R" "$title" "$(t 'не получилось' 'failed')"
    flush_warns
    printf '\n'
    tail -n 12 "$LOG" | sed "s/^/     ${D}/; s/\$/${N}/"
    printf '\n  %s %s\n  %s\n  %s\n\n' "$(t 'Весь журнал:' 'Full log:')" "$LOG" \
      "$(t 'Установку можно запустить ещё раз — она продолжит с того же места.' 'Running the installer again picks up where it stopped.')" \
      "$(t 'Подробный разбор:' 'To see everything as it happens:') ${B}./install.sh --debug${N}"
    exit 1
  fi
}

plate "JustDay" "$(t 'голосовой ассистент · установка' 'a voice assistant · install')"

# ───────────── the computer ─────────────
section "$(t 'Этот компьютер' 'This computer')"
desktop="${XDG_CURRENT_DESKTOP:-?}"
PLASMA=0
if [[ "$desktop" == *KDE* ]]; then
  PLASMA=$(plasmashell --version 2>/dev/null | awk '{print $2}' | cut -d. -f1)
  PLASMA=${PLASMA:-0}
  desktop="KDE Plasma${PLASMA:+ $PLASMA}"
fi
session="${XDG_SESSION_TYPE:-?}"; session="${session^}"
gpu=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 | sed 's/^NVIDIA //' || true)
# Что эта машина потянет. Остальное просто не ставится — вместо ошибки на пол-установки.
WAYLAND=0; [[ "${XDG_SESSION_TYPE:-}" == wayland ]] && WAYLAND=1
ISLAND=$WAYLAND                       # что увидим в ЭТОМ сеансе: остров рисуется только на Wayland
DESKTOP_CONTROL=0                     # нажимать кнопки в чужих окнах умеет только KWin 6 на Wayland
[[ $WAYLAND == 1 && "${XDG_CURRENT_DESKTOP:-}" == *KDE* && ${PLASMA:-0} -ge 6 ]] && DESKTOP_CONTROL=1
row '✓' "$G" "$(t 'Компьютер' 'Computer')" "$desktop · $session${gpu:+ · $gpu}"
if [[ $WAYLAND == 0 ]]; then
  warn "$(t 'X11: голос, горячие клавиши и уведомления работают; вместо острова — полоска сверху, ему нужен Wayland. Войдёте через Wayland — остров появится сам, переустанавливать не нужно.' 'X11: voice, hotkeys and notifications work; instead of the island there is a strip along the top, the island needs Wayland. Log in through Wayland and it appears by itself — no reinstall.')"
fi
if [[ "${XDG_CURRENT_DESKTOP:-}" == *KDE* && ${PLASMA:-0} -gt 0 && ${PLASMA:-0} -lt 6 ]]; then
  warn "$(t "Plasma $PLASMA: горячие клавиши настроятся, а нажимать кнопки в чужих окнах ассистент не сможет — для этого нужен KWin 6." "Plasma $PLASMA: hotkeys are set up, but the assistant cannot press buttons inside other windows — that needs KWin 6.")"
elif [[ "${XDG_CURRENT_DESKTOP:-}" != *KDE* ]]; then
  warn "$(t 'Не KDE: горячие клавиши и управление столом придётся настроить вручную.' 'Not KDE: hotkeys and desktop control need manual setup.')"
fi
[[ -n "$gpu" ]] || warn "$(t 'Нет видеокарты NVIDIA: речь будет распознаваться на процессоре, медленнее.' 'No NVIDIA GPU: speech recognition runs on the CPU, slower.')"
flush_warns

# ───────────── the code ─────────────
if [[ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/pyproject.toml" ]]; then
  APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"; FROM_CLONE=1
else
  APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/justday/app"; FROM_CLONE=0
fi
get_code() {
  if [[ $FROM_CLONE == 1 ]]; then
    note "$(t 'из этой папки' 'this folder') · $(git -C "$APP_DIR" rev-parse --short HEAD 2>/dev/null || echo '?')"
  else
    if [[ -d "$APP_DIR/.git" ]]; then git -C "$APP_DIR" pull --ff-only; else git clone --depth 1 "$REPO_URL" "$APP_DIR"; fi
    note "$(t 'версия' 'version') $(git -C "$APP_DIR" rev-parse --short HEAD)"
  fi
}
step "$(t 'Программа' 'Program')" get_code

# ───────────── what to install ─────────────
# Полный набор — около 3.5 ГБ, и почти всё это распознавание речи, нейросетевой голос и библиотеки
# CUDA. Человеку без микрофона и наушников они не нужны вовсе, без видеокарты NVIDIA — половина.
# Поэтому спрашиваем один раз, а доставить остальное можно потом: justday parts add speech.
SITE="$APP_DIR/.venv/lib/python3.12/site-packages"
have_part() {
  case $1 in
    speech) [[ -d "$SITE/faster_whisper" ]] ;;
    voice)  [[ -d "$SITE/torch" ]] ;;
    cuda)   [[ -d "$SITE/nvidia" ]] ;;
    *) false ;;
  esac
}
here=()
for part in speech voice cuda; do have_part "$part" && here+=("$part"); done

if [[ -z "$WANT" ]]; then                       # ни флага, ни переменной: спросить или решить самим
  guess="speech,voice"; [[ -n "$gpu" ]] && guess="speech,voice,cuda"
  ((${#here[@]})) && guess=$(IFS=,; printf '%s' "${here[*]}")   # уже что-то стоит — не отбирать
  # Повторный запуск — это починка или обновление, а не новая установка. Спрашивать «что
  # установить» у того, у кого уже всё стоит, значит предлагать скачать заново то, что он скачал
  # вчера: вопрос выглядит как требование выбрать, а любой выбор, кроме прежнего, отнимет или
  # добавит гигабайты молча. Поэтому состав просто остаётся прежним, и сказано, как его сменить.
  if ((${#here[@]})) && [[ -z "${JUSTDAY_ASK:-}" ]]; then
    WANT="$guess"
    printf '\n  %s%s %s%s\n' "$D" "$(t 'Уже стоит:' 'Already installed:')" "${here[*]}" "$N"
    printf '  %s%s%s\n\n' "$D" "$(t 'Обновляю это же. Сменить состав: justday parts add speech · перенастроить: ./install.sh --setup' 'Updating the same. To change: justday parts add speech · reconfigure: ./install.sh --setup')" "$N"
  elif ((ASK == 1)) && { : </dev/tty; } 2>/dev/null; then
    # Выбор галочками, а не цифрами.
    #
    # Четыре готовых набора — это чужое представление о том, как людям нужно. Кому-то не нужен
    # голос, но нужен микрофон; кому-то наоборот; кто-то хочет только текстом и без островка.
    # Готовые наборы остались первой строкой — для тех, кому всё равно, — а ниже каждая часть
    # отмечается отдельно.
    #
    # Стрелками, потому что цифрами выбирают то, что уже прочитали и поняли, а галочками —
    # разбираясь по дороге. Второе и есть установка.
    # Общий выбор галочками: работает по спискам PICK_KEY/PICK_NAME/PICK_DESC/PICK_ON,
    # складывает отмеченное в PICK_OUT. Рисует прямо в терминал — вывод забирает подстановка
    # команд, и напечатанное в stdout человек бы не увидел вовсе.
    pick_list() {
      local n=${#PICK_KEY[@]} at=0 drawn=0 i hint
      hint="$(t 'Пробел — отметить · ↑↓ — выбрать · Enter — дальше' 'Space — toggle · ↑↓ — move · Enter — continue')"
      while :; do
        ((drawn)) && printf '\e[%dA' $((n + 2)) >/dev/tty
        drawn=1
        for ((i = 0; i < n; i++)); do
          local mark cursor
          [[ ${PICK_ON[$i]} == 1 ]] && mark="${C}◉${N}" || mark="${D}○${N}"
          [[ $i == $at ]] && cursor="${B}❯${N}" || cursor=" "
          printf '\e[K   %s %s  %s%s%s\n' "$cursor" "$mark" "$(pad "${PICK_NAME[$i]}" 26)" "$D" "${PICK_DESC[$i]}$N" >/dev/tty
        done
        printf '\e[K\n' >/dev/tty
        printf '\e[K  %s%s%s\n' "$D" "$hint" "$N" >/dev/tty
        local chunk
        IFS= read -rsn1 chunk </dev/tty || break
        case "$chunk" in
          $'\e') IFS= read -rsn2 -t 0.1 chunk </dev/tty || chunk=""
                 case "$chunk" in "[A") at=$(((at + n - 1) % n)) ;; "[B") at=$(((at + 1) % n)) ;; esac ;;
          " ") [[ ${PICK_ON[$at]} == 1 ]] && PICK_ON[$at]=0 || PICK_ON[$at]=1 ;;
          "") break ;;
          k) at=$(((at + n - 1) % n)) ;;
          j) at=$(((at + 1) % n)) ;;
        esac
      done
      PICK_OUT=()
      # if, а не `[[ ]] && …`: у последней строки цикла код выхода 1, когда последний пункт не
      # отмечен (на машине без NVIDIA — это «ускорение»), и `set -e` молча завершал весь установщик.
      for ((i = 0; i < n; i++)); do
        if [[ ${PICK_ON[$i]} == 1 ]]; then PICK_OUT+=("${PICK_KEY[$i]}"); fi
      done
    }

    printf '\n  %s%s%s\n\n' "$B" "$(t 'Что установить' 'What to install')" "$N"
    if ((${#here[@]})); then
      printf '  %s%s %s%s\n\n' "$D" "$(t 'Уже стоит:' 'Already installed:')" "${here[*]}" "$N"
    fi
    PICK_KEY=(speech voice cuda)
    PICK_NAME=("$(t 'Распознавание речи' 'Speech recognition')" "$(t 'Нейросетевой голос' 'Neural voice')" "$(t 'Ускорение на видеокарте' 'GPU acceleration')")
    PICK_DESC=("$(t '~550 МБ · слышит вас' '~550 MB · hears you')" "$(t '~750 МБ · отвечает голосом' '~750 MB · answers out loud')" "$(t '~2.2 ГБ · NVIDIA, быстрее распознаёт' '~2.2 GB · NVIDIA, faster recognition')")
    PICK_ON=(0 0 0)
    for i in 0 1 2; do [[ ",$guess," == *",${PICK_KEY[$i]},"* ]] && PICK_ON[$i]=1; done
    pick_list
    WANT=$(IFS=,; printf '%s' "${PICK_OUT[*]}"); WANT=${WANT:--}
    printf '\e[K'

    # Второй выбор — про экран, а не про гигабайты. Кому-то нужен только голосовой Джарвис: ни
    # дока, ни лотка, ни островка. Раньше это настраивалось потом, в настройках, то есть не
    # настраивалось никогда — человек не знает, что у него есть лишнее, пока оно ему не мешает.
    printf '\n  %s%s%s\n\n' "$B" "$(t 'Что показывать на экране' 'What to show on screen')" "$N"
    PICK_KEY=(island dock tray)
    PICK_NAME=("$(t 'Островок' 'The island')" "$(t 'Док' 'The dock')" "$(t 'Полоса лотка' 'The tray strip')")
    PICK_DESC=("$(t 'полоса сверху: ответы, музыка, уведомления' 'the strip on top: answers, music, notifications')" "$(t 'программы снизу, как на макоси' 'apps along the bottom, macOS-style')" "$(t 'чужие значки отдельной полосой сбоку' "other apps' icons in their own strip")")
    PICK_ON=(1 1 1)
    pick_list
    SCREEN=$(IFS=,; printf '%s' "${PICK_OUT[*]}")
    printf '\e[K'
  else
    WANT="$guess"
  fi
fi

SPEECH=0 VOICE=0 CUDA=0
[[ ",$WANT," == *,speech,* ]] && SPEECH=1
[[ ",$WANT," == *,voice,* ]] && VOICE=1
[[ ",$WANT," == *,cuda,* ]] && CUDA=1
EXTRAS=()
((SPEECH)) && EXTRAS+=(--extra speech)
((VOICE)) && EXTRAS+=(--extra voice)
((CUDA)) && EXTRAS+=(--extra cuda)
PY_MB=$((250 + SPEECH * 550 + VOICE * 750 + CUDA * 2200))
chosen=$(t 'ядро' 'core')
((SPEECH)) && chosen="$chosen · $(t 'речь' 'speech')"
((VOICE)) && chosen="$chosen · $(t 'голос' 'voice')"
((CUDA)) && chosen="$chosen · $(t 'видеокарта' 'GPU')"
if ((CUDA)) && [[ -z "$gpu" ]]; then
  warn "$(t 'Видеокарты NVIDIA не видно, а библиотеки CUDA выбраны: 2.2 ГБ пролежат без дела.' 'No NVIDIA GPU here, but the CUDA libraries are selected: 2.2 GB will sit unused.')"
fi
row '✓' "$G" "$(t 'Набор' 'Selection')" "$chosen · ~$(hsize $PY_MB)"
flush_warns

# Места должно хватить до начала скачивания, а не после половины: гигабайты торча и CUDA
# кончаются на диске именно в середине длинного шага.
free_mb=$(df -Pm "$HOME" 2>/dev/null | awk 'NR==2{print $4+0}')
if ((free_mb > 0)); then
  if ((free_mb < PY_MB + 300)); then
    row '!' "$Y" "$(t 'Место на диске' 'Disk space')" "$(t 'свободно' 'free') $(hsize "$free_mb") · $(t 'нужно около' 'about') $(hsize $((PY_MB + 300)))"
    hint=$(t 'Меньший набор: ./install.sh --no-gpu (без CUDA) или --text-only (250 МБ).' \
             'A smaller selection: ./install.sh --no-gpu (no CUDA) or --text-only (250 MB).')
    if ((free_mb < 400)); then
      printf '     %s%s%s\n\n' "$R" "$(t 'Столько не поместится — установка остановлена, чтобы не оборваться на середине.' \
        'That will not fit — stopping now instead of breaking halfway.')" "$N"
      printf '  %s%s%s\n\n' "$D" "$hint" "$N"
      exit 1
    fi
    printf '     %s%s%s\n' "$D" "$hint" "$N"
  fi
fi

# ───────────── system packages (only what is missing) ─────────────
section "$(t 'Ставим' 'Installing')"
MISSING=()   # то, что не удалось поставить: сводка в конце, а установка идёт дальше
need=()
for pair in playerctl:playerctl yt-dlp:yt-dlp plocate:plocate \
            fd:fd-find rg:ripgrep jq:jq spectacle:spectacle gtk-launch:gtk3 notify-send:libnotify \
            git:git kitty:kitty magick:ImageMagick zstd:zstd secret-tool:libsecret qdbus-qt6:qt6-qttools \
            ffmpeg:ffmpeg; do
  command -v "${pair%%:*}" >/dev/null || need+=("${pair#*:}")
done
# Микрофон и голос — только если их выбрали: в текстовом наборе просить пароль за espeak-ng незачем.
((SPEECH)) && { command -v pw-record >/dev/null || need+=(pipewire-utils); }
((SPEECH || VOICE)) && { command -v espeak-ng >/dev/null || need+=(espeak-ng); }
# clipboard: wl-clipboard on Wayland, xclip on X11
if [[ $WAYLAND == 1 ]]; then command -v wl-copy >/dev/null || need+=(wl-clipboard)
else command -v xclip >/dev/null || need+=(xclip); fi
# Обычные утилиты иксов: ими управляются окна везде, кроме KWin 6 на Wayland. Ставим их и на
# Wayland, если иксы вообще есть (Xwayland считается): это цена одного мегабайта за то, что вход
# через X11 на той же машине не окажется без «закрой дискорд» и без снимка экрана.
if [[ -n "${DISPLAY:-}" ]]; then
  command -v wmctrl >/dev/null || need+=(wmctrl)
  command -v xdotool >/dev/null || need+=(xdotool)
  command -v xprop >/dev/null || need+=(xorg-x11-utils)
  command -v spectacle >/dev/null || command -v gnome-screenshot >/dev/null || command -v maim >/dev/null \
    || command -v scrot >/dev/null || need+=(maim)
fi
# the island's typeface
fc-list : family 2>/dev/null | grep -qx Inter || need+=(rsms-inter-fonts)
# Остров (в Fedora он в COPR, в Arch в своих репозиториях) и tkinter для запасной полоски — оба,
# независимо от сеанса, из которого ставят. На машине, где на экране входа есть и Wayland, и X11,
# нужное выбирается при каждом входе; поставить только половину значит оставить второй сеанс без лица.
command -v qs >/dev/null || command -v quickshell >/dev/null || need+=(quickshell)
python3 -c "import tkinter" 2>/dev/null || need+=(python3-tkinter)
# kwin-mcp builds dbus-python, pygobject and pycairo from source: compiler + headers + AT-SPI typelib.
# On X11 or Plasma 5 it is not installed at all, so none of this is asked for either.
if [[ $DESKTOP_CONTROL == 1 ]]; then
  command -v gcc >/dev/null || need+=(gcc)
  command -v pkg-config >/dev/null || need+=(pkgconf-pkg-config)
  for pc in dbus-1:dbus-devel glib-2.0:glib2-devel cairo:cairo-devel cairo-gobject:cairo-gobject-devel gobject-introspection-1.0:gobject-introspection-devel \
            atspi-2:at-spi2-core-devel; do
    pkg-config --exists "${pc%%:*}" 2>/dev/null || need+=("${pc#*:}")
  done
fi
command -v dbus-monitor >/dev/null || need+=(dbus-tools)
if ((${#need[@]})); then
  if command -v dnf >/dev/null; then PM=(sudo dnf install -y)
    need=("${need[@]/#ffmpeg/ffmpeg-free}")   # Fedora's own build; the full one needs RPM Fusion
    [[ " ${need[*]} " == *" quickshell "* ]] && COPR=errornointernet/quickshell
  elif command -v apt-get >/dev/null; then PM=(sudo apt-get install -y)
    need=("${need[@]/spectacle/kde-spectacle}"); need=("${need[@]/qt6-qttools/qdbus-qt6}"); need=("${need[@]/pkgconf-pkg-config/pkg-config}"); need=("${need[@]/gcc/build-essential}"); need=("${need[@]/dbus-devel/libdbus-1-dev}")
    need=("${need[@]/glib2-devel/libglib2.0-dev}"); need=("${need[@]/cairo-gobject-devel/libcairo2-dev}"); need=("${need[@]/cairo-devel/libcairo2-dev}"); need=("${need[@]/dbus-tools/dbus-bin}")
    need=("${need[@]/gobject-introspection-devel/libgirepository-2.0-dev}"); need=("${need[@]/at-spi2-core-devel/libatspi2.0-dev}")
    need=("${need[@]/pipewire-utils/pipewire-bin}"); need=("${need[@]/gtk3/libgtk-3-bin}"); need=("${need[@]/libnotify/libnotify-bin}"); need=("${need[@]/ImageMagick/imagemagick}")
    need=("${need[@]/libsecret/libsecret-tools}"); need=("${need[@]/rsms-inter-fonts/fonts-inter}")
    need=("${need[@]/xorg-x11-utils/x11-utils}"); need=("${need[@]/python3-tkinter/python3-tk}")
    need=("${need[@]/quickshell/}")   # not packaged for Debian/Ubuntu yet: see the note at the end
  elif command -v zypper >/dev/null; then
    # `--ignore-unknown` есть не у всякой версии zypper, а без него один неугаданный пакет валит
    # установку остальных. Поэтому спрашиваем у самого zypper, знает ли он такой ключ.
    if zypper --help install 2>&1 | grep -q -- --ignore-unknown; then
      PM=(sudo zypper --non-interactive install --no-recommends --ignore-unknown)
    else
      PM=(sudo zypper --non-interactive install --no-recommends)
    fi
    # openSUSE. `--ignore-unknown` здесь не лень, а осознанный выбор: имена пакетов у них свои, и
    # один неугаданный не должен валить установку остального. Чего не нашлось — перечислится в
    # конце, вместе с тем, что без него не работает.
    need=("${need[@]/pipewire-utils/pipewire-tools}"); need=("${need[@]/fd-find/fd}")
    need=("${need[@]/qt6-qttools/qt6-tools}"); need=("${need[@]/pkgconf-pkg-config/pkgconf-pkg-config}")
    need=("${need[@]/dbus-devel/dbus-1-devel}"); need=("${need[@]/dbus-tools/dbus-1-tools}")
    need=("${need[@]/cairo-gobject-devel/cairo-devel}")
    need=("${need[@]/libnotify/libnotify-tools}"); need=("${need[@]/libsecret/libsecret-tools}")
    need=("${need[@]/rsms-inter-fonts/inter-fonts}")
    need=("${need[@]/xorg-x11-utils/xprop}"); need=("${need[@]/python3-tkinter/python3-tk}")
    need=("${need[@]/gtk3/gtk3-tools}")
    # Quickshell в основных репозиториях openSUSE не лежит: он собирается в OBS, и подключать чужой
    # репозиторий за человека нельзя — это его система. Скажем прямо и оставим выбор ему.
    need=("${need[@]/quickshell/}")
  elif command -v pacman >/dev/null; then PM=(sudo pacman -S --needed --noconfirm)
    need=("${need[@]/pipewire-utils/pipewire}"); need=("${need[@]/fd-find/fd}"); need=("${need[@]/ImageMagick/imagemagick}"); need=("${need[@]/libnotify/libnotify}")
    need=("${need[@]/qt6-qttools/qt6-tools}"); need=("${need[@]/gcc/base-devel}"); need=("${need[@]/pkgconf-pkg-config/pkgconf}"); need=("${need[@]/dbus-devel/dbus}")
    need=("${need[@]/glib2-devel/glib2}"); need=("${need[@]/cairo-gobject-devel/cairo}"); need=("${need[@]/cairo-devel/cairo}"); need=("${need[@]/gobject-introspection-devel/gobject-introspection}")
    need=("${need[@]/at-spi2-core-devel/at-spi2-core}"); need=("${need[@]/dbus-tools/dbus}"); need=("${need[@]/rsms-inter-fonts/inter-font}")
    need=("${need[@]/xorg-x11-utils/xorg-xprop}"); need=("${need[@]/python3-tkinter/tk}")
  else
    PM=()
  fi
  mapfile -t need < <(printf '%s\n' "${need[@]}" | awk 'NF && !seen[$0]++')
  # Нет пароля администратора — не беда: всё остальное ставится в домашнюю папку и работает.
  # Чего именно не будет без пакета, написано в конце (skipped_note).
  if ((${#PM[@]} == 0)); then
    row '!' "$Y" "$(t 'Системные пакеты' 'System packages')" "$(t 'неизвестный менеджер пакетов' 'unknown package manager')"
    MISSING=("${need[@]}")
  elif [[ "${JUSTDAY_NO_SUDO:-}" == 1 ]]; then
    row '!' "$Y" "$(t 'Системные пакеты' 'System packages')" "$(t 'пропущены: JUSTDAY_NO_SUDO=1' 'skipped: JUSTDAY_NO_SUDO=1')"
    MISSING=("${need[@]}")
  elif sudo -n true 2>/dev/null || { [[ -r /dev/tty ]] && { : </dev/tty; } 2>/dev/null; }; then
    if ! sudo -n true 2>/dev/null; then
      printf '  %s•%s  %s%s%s\n' "$C" "$N" "$(pad "$(t 'Системные пакеты' 'System packages')" 28)" "$D" "${need[*]}"
      printf '     %s%s%s\n' "$D" "$(t 'Для них нужен пароль администратора — только для этого шага. Без него установка продолжится без этих пакетов.' 'These need your admin password — for this step only. Without it the install carries on without them.')" "$N"
      if sudo -v </dev/tty; then
        printf '\e[1A\e[K\e[1A\e[K\e[1A\e[K'   # the list, the hint and sudo's own prompt: the step line replaces them
      else
        printf '\e[1A\e[K\e[1A\e[K\e[1A\e[K'
        row '!' "$Y" "$(t 'Системные пакеты' 'System packages')" "$(t 'без прав администратора' 'no admin rights')"
        MISSING=("${need[@]}")
      fi
    fi
    if ((${#MISSING[@]} == 0)); then
      # Ставим пачкой, а если пачка не прошла — по одному.
      #
      # Это не перестраховка. Имена пакетов у каждого дистрибутива свои, угадать все невозможно, а
      # менеджер падает на первом же незнакомом и не ставит **ничего** — включая те двадцать, что
      # он прекрасно знает. Так у человека на openSUSE установка легла целиком из-за одного шрифта.
      # Поэтому: не вышло пачкой — идём по одному, и список непоставленного уходит в конец, где и
      # так объясняется, чего без чего не будет.
      install_packages() {
        [[ -n ${COPR:-} ]] && sudo dnf copr enable -y "$COPR"
        if "${PM[@]}" "${need[@]}"; then
          note "$(t 'поставлено' 'installed'): ${#need[@]}"
          return 0
        fi
        printf '\n── %s\n' "$(t 'по одному' 'one by one')" >> "$LOG"
        local ok=0 bad=()
        for pkg in "${need[@]}"; do
          if "${PM[@]}" "$pkg" >> "$LOG" 2>&1; then ok=$((ok + 1)); else bad+=("$pkg"); fi
        done
        MISSING+=("${bad[@]}")
        if ((${#bad[@]})); then
          note "$(t 'поставлено' 'installed'): $ok · $(t 'не нашлось' 'not found'): ${#bad[@]}"
        else
          note "$(t 'поставлено' 'installed'): $ok"
        fi
        return 0
      }
      step "$(t 'Системные пакеты' 'System packages')" install_packages
    fi
  else
    row '!' "$Y" "$(t 'Системные пакеты' 'System packages')" "$(t 'некому спросить пароль' 'no terminal to ask for a password')"
    MISSING=("${need[@]}")
  fi
  if ((${#MISSING[@]})); then
    printf '     %s%s%s\n' "$D" "$(t 'Поставит администратор:' 'For an admin to run:') ${PM[*]:-<package manager>} ${MISSING[*]}" "$N"
  fi
else
  row '✓' "$G" "$(t 'Системные пакеты' 'System packages')" "$(t 'всё уже есть' 'all there')"
fi

# ───────────── uv, Claude Code, kwin-mcp ─────────────
export PATH="$HOME/.local/bin:$PATH"
get_claude() {
  if command -v claude >/dev/null; then
    note "$(claude --version 2>/dev/null | awk '{print $1}')"
  else
    curl -fsSL https://claude.ai/install.sh | bash
    note "$(t 'установлен' 'installed')"
  fi
}
step "Claude Code" get_claude

get_uv() {
  if command -v uv >/dev/null; then note "$(t 'уже есть' 'already here')"
  else curl -LsSf https://astral.sh/uv/install.sh | sh; note "$(t 'установлен' 'installed')"; fi
}
step "uv" get_uv

# Без прав администратора кое-что ставится и в домашнюю папку — музыка не должна пропадать
# только потому, что на этом компьютере нет пароля.
if ((${#MISSING[@]})) && [[ " ${MISSING[*]} " == *" yt-dlp "* ]] && ! command -v yt-dlp >/dev/null; then
  user_tools() { uv tool install yt-dlp; note "yt-dlp"; }
  step "$(t 'Музыка и видео' 'Music and video')" user_tools
  MISSING=("${MISSING[@]/yt-dlp/}")
fi

if [[ $DESKTOP_CONTROL == 1 ]]; then
  get_kwin_mcp() {
    # pinned: plugin/bin/kwin_live.py extends this server's internals (engine, AT-SPI helper)
    local rev="${KWIN_MCP_REV:-7cef7afc402d3c5892f39825290bbbe1851ae1d0}"
    if uv tool install --python 3.12 --reinstall "git+https://github.com/VibeProgramm/kwin-mcp@$rev"; then
      note "kwin-mcp"
    else
      note "$(t 'не поставилось' 'not installed')"
      warn "$(t 'Без него ассистент не сможет нажимать кнопки в окнах. Подробности в журнале.' 'Without it the assistant cannot press buttons in windows. See the log.')"
    fi
  }
  step "$(t 'Управление рабочим столом' 'Desktop control')" get_kwin_mcp
else
  row '•' "$C" "$(t 'Управление рабочим столом' 'Desktop control')" "$(t 'пропущено: нужен KWin 6 на Wayland' 'skipped: needs KWin 6 on Wayland')"
fi

# ───────────── python env and models ─────────────
# Самый долгий шаг во всей установке, и раньше он выглядел как зависший спиннер: рядом с ним
# теперь видно, сколько уже скачано и сколько всего ожидается.
venv_grew() {
  local m; m=$(du -sm "$APP_DIR/.venv" 2>/dev/null | awk '{print $1+0}')
  ((m > 0)) || return 0
  printf '%s %s ~%s' "$(hsize "$m")" "$(t из of)" "$(hsize $PY_MB)"
}
python_env() {
  local s=$SECONDS
  (cd "$APP_DIR" && uv sync --python 3.12 "${EXTRAS[@]}")
  mkdir -p "$HOME/.local/bin"
  ln -sf "$APP_DIR/.venv/bin/justday" "$HOME/.local/bin/justday"
  local where; where=$(mib "$APP_DIR/.venv")
  if ((SECONDS - s < 3)); then note "$(t 'уже на месте' 'up to date') · $where"
  else note "$(t 'за' 'in') $(clock $((SECONDS - s))) · $where"; fi
}
PROGRESS=venv_grew
SIZE_HINT="~$(hsize $PY_MB), $(t 'на медленном интернете это минуты' 'minutes on a slow connection')"
if ((SPEECH || VOICE)); then env_title=$(t 'Распознавание и голос' 'Speech and voice'); else env_title=$(t 'Ассистент' 'The assistant'); fi
step "$env_title" python_env

if ((SPEECH)); then
  models() {
    "$APP_DIR/.venv/bin/python" -c 'from justday.audio import voice_activity_model; voice_activity_model()'
    note "$(t 'паузы в речи и имя ассистента' 'pauses in speech, the assistant name')"
  }
  step "$(t 'Модели' 'Models')" models
else
  row '•' "$C" "$(t 'Модели' 'Models')" "$(t 'не нужны: распознавание речи не ставили' 'not needed: speech recognition was not installed')"
fi

# ───────────── config ─────────────
section "$(t 'Настраиваем' 'Setting up')"
CONF_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/justday"
BRAIN_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/justday/brain"
FIRST_RUN=0; [[ -f "$CONF_DIR/config.toml" ]] || FIRST_RUN=1
# Что человек отметил на вопросе «что показывать на экране». Пишем своим же конфигуратором, а не
# sed: вставленная строка дала бы второй ключ enabled в секции, где он уже есть, а TOML с двумя
# одинаковыми ключами не читается вовсе — установка кончилась бы конфигом, который не открывается.
#
# Ставим и true, и false, а не только false: при перенастройке человек может и вернуть то, что
# когда-то убрал, и «включить обратно» должно работать так же просто, как «убрать».
apply_screen() {
  [[ -n "${SCREEN+x}" ]] || return 0
  local part on
  for part in island dock tray; do
    on=false
    [[ ",$SCREEN," == *",$part,"* ]] && on=true
    # Молча проглотить ошибку нельзя: человек снял галочку, а на экране всё осталось бы как было —
    # и он бы решил, что выбор ничего не значит. Поэтому строкой под шагом.
    "$APP_DIR/.venv/bin/justday" config set "$part.enabled" "$on" >/dev/null 2>&1 \
      || warn "$(t "не удалось записать" "could not write") $part.enabled — $(t "поправьте в настройках" "change it in settings")"
  done
}

settings() {
  mkdir -p "$CONF_DIR" "$BRAIN_DIR"
  if [[ ! -f "$CONF_DIR/config.toml" ]]; then
    local mic
    mic=$(pactl list short sources 2>/dev/null | awk '{print $2}' | grep -v monitor | grep -viE 'virtual|pwsp|easyeffects' | grep -i usb | head -1 || true)
    sed "s|^input = \"\"|input = \"${mic}\"|" "$APP_DIR/config.example.toml" > "$CONF_DIR/config.toml"
    # Что человек отметил на втором вопросе. Пишем своим же конфигуратором, а не sed: вставленная
    # строка дала бы второй ключ enabled в секции, где он уже есть, а TOML с двумя одинаковыми
    # ключами не читается вовсе — установка кончилась бы конфигом, который не открывается.
    apply_screen
    # Настройки под выбранный набор: без распознавания речи кнопка открывает поле ввода,
    # а не запись; без нейросетевого голоса отвечает espeak-ng, а в текстовом наборе — молча.
    ((SPEECH)) || sed -i 's/^microphone = true/microphone = false/' "$CONF_DIR/config.toml"
    if ((VOICE == 0)); then
      if ((SPEECH)); then sed -i 's/^engine = "silero"/engine = "espeak"/' "$CONF_DIR/config.toml"
      else sed -i 's/^engine = "silero"/engine = "none"/' "$CONF_DIR/config.toml"; fi
    fi
    note "$(t 'созданы' 'created')${mic:+ · $(t 'микрофон' 'microphone') USB}"
  else
    if [[ -n "${SCREEN+x}" ]]; then
      apply_screen
      note "$(t 'ваши, обновлён выбор для экрана' 'yours, screen choice updated')"
    else
      note "$(t 'ваши, без изменений' 'yours, unchanged')"
    fi
  fi
  [[ -f "$BRAIN_DIR/CLAUDE.md" ]] || "$APP_DIR/scripts/make-profile.sh" > "$BRAIN_DIR/CLAUDE.md"
}
step "$(t 'Настройки' 'Settings')" settings

# ───────────── services ─────────────
if ! systemctl --user show-environment >/dev/null 2>&1; then
  row '!' "$Y" "$(t 'Службы' 'Services')" "$(t 'нет сеанса systemd (контейнер или SSH?)' 'no systemd user session (container or SSH?)')"
  printf '     %s\n\n' "$(t 'Программа поставлена. Запустите установку ещё раз из рабочего стола — появятся остров и горячие клавиши.' 'The program is installed. Run the installer again from your desktop for the island and the hotkeys.')"
  exit 0
fi
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
# Лицо ассистента — одна служба на оба сеанса.
#
# Раньше выбор делали здесь, при установке: на Wayland включали остров и выключали полоску, на X11
# наоборот. На машине, где на экране входа есть и то и другое, выбор оказывался неверным ровно в
# половине входов — и переустановка была единственным способом это исправить. Теперь `justday ui`
# смотрит на сеанс при каждом запуске службы, то есть при каждом входе.
face_service() {
  sed "s|@JUSTDAY@|$HOME/.local/bin/justday|" "$APP_DIR/systemd/justday-ui.service" > "$UNIT_DIR/justday-ui.service"
  # Прежние службы по отдельности больше не нужны: их место заняла одна. Убираем и файлы, иначе
  # на следующем входе поднялись бы обе и нарисовали два лица.
  for old in justday-island justday-panel justday-overlay; do
    systemctl --user disable --now "$old.service" 2>/dev/null || true
    rm -f "${UNIT_DIR:?}/${old:?}.service"
  done
  systemctl --user daemon-reload
  systemctl --user enable justday-ui.service
  systemctl --user restart justday-ui.service
}
services() {
  mkdir -p "$UNIT_DIR"
  sed "s|@JUSTDAY@|$HOME/.local/bin/justday|; s|@PATH@|$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin|" \
    "$APP_DIR/systemd/justday.service" > "$UNIT_DIR/justday.service"
  systemctl --user daemon-reload
  systemctl --user enable justday.service
  systemctl --user restart justday.service
  face_service
  # Что именно поднялось — спрашиваем у той же программы, которая это и решает: два ответа на один
  # вопрос расходятся, один — нет.
  face=$("$APP_DIR/.venv/bin/python" -c 'from justday import face; w, y = face.pick(); print(w, y, sep="|")' 2>/dev/null || echo 'panel|')
  if [[ "${face%%|*}" == island ]]; then
    note "$(t 'ассистент · остров' 'assistant · island')"
  else
    note "$(t 'ассистент · полоска сверху' 'assistant · strip along the top')"
    printf '     %s\n' "${face#*|}"
    if ! "$APP_DIR/.venv/bin/python" -c "import tkinter" 2>/dev/null; then
      warn "$(t 'Полоске нужен tkinter: python3-tkinter (Fedora), python3-tk (Debian), tk (Arch).' 'The strip needs tkinter: python3-tkinter (Fedora), python3-tk (Debian), tk (Arch).')"
    elif ! command -v qs >/dev/null && ! command -v quickshell >/dev/null; then
      warn "$(t 'Острову нужен Quickshell; поставьте его, и на следующем входе в Wayland он появится сам' 'The island needs Quickshell; install it and it appears by itself at the next Wayland login'): https://quickshell.org/docs/guide/install-setup/"
    fi
  fi
  if systemctl --user cat justday-voice.service >/dev/null 2>&1; then
    sed "s|@REPO@|$APP_DIR|" "$APP_DIR/systemd/justday-voice.service" > "$UNIT_DIR/justday-voice.service"
    # Гнездо переживает службу: голос выходит, когда с машиной долго молчат, и возвращается на
    # первую же просьбу. Без него выход был бы уходом навсегда.
    cp "$APP_DIR/systemd/justday-voice.socket" "$UNIT_DIR/justday-voice.socket"
    systemctl --user daemon-reload
    systemctl --user enable --now justday-voice.socket
    systemctl --user try-restart justday-voice.service
  fi
  if systemctl --user cat justday-chatterbox.service >/dev/null 2>&1; then
    sed "s|@REPO@|$APP_DIR|" "$APP_DIR/systemd/justday-chatterbox.service" > "$UNIT_DIR/justday-chatterbox.service"
    cp "$APP_DIR/systemd/justday-chatterbox.socket" "$UNIT_DIR/justday-chatterbox.socket"
    systemctl --user daemon-reload
    systemctl --user try-restart justday-chatterbox.service
  fi
}
step "$(t 'Службы' 'Services')" services

# optional extras, asked for with environment variables (the setup wizard offers them too)
if [[ "${JUSTDAY_LOCAL_LLM:-}" == 1 ]]; then
  local_llm() { "$APP_DIR/scripts/setup-local-llm.sh"; note "Ollama · Qwen 3.5 9B"; }
  step "$(t 'Локальная модель' 'Local model')" local_llm
fi
if [[ "${JUSTDAY_VOICE:-}" == 1 ]]; then
  neural_voice() { "$APP_DIR/scripts/setup-voice.sh"; note "Qwen3-TTS"; }
  step "$(t 'Нейросетевой голос' 'Neural voice')" neural_voice
fi

# ───────────── hotkeys (KDE) ─────────────
if ! command -v kwriteconfig6 >/dev/null && ! command -v kwriteconfig5 >/dev/null && command -v gsettings >/dev/null \
   && [[ "${XDG_CURRENT_DESKTOP:-}" == *GNOME* ]]; then
  gnome_hotkeys() {
    "$APP_DIR/scripts/setup-hotkey-gnome.sh" --talk "<Super>j"
    note "Super+J $(t 'говорить' 'talk') · Super+K $(t 'написать' 'type')"
  }
  step "$(t 'Горячие клавиши' 'Hotkeys')" gnome_hotkeys
elif command -v kwriteconfig6 >/dev/null || command -v kwriteconfig5 >/dev/null; then
  hotkeys() {
    local current menu_now emoji_now apps_now extras=()
    local kread; kread=$(command -v kreadconfig6 || command -v kreadconfig5)
    current=$("$kread" --file kglobalshortcutsrc --group services --group net.local.justday.desktop --key _launch 2>/dev/null || true)
    menu_now=$("$kread" --file kglobalshortcutsrc --group services --group net.local.justday-menu.desktop --key _launch 2>/dev/null || true)
    emoji_now=$("$kread" --file kglobalshortcutsrc --group services --group net.local.justday-emoji.desktop --key _launch 2>/dev/null || true)
    apps_now=$("$kread" --file kglobalshortcutsrc --group services --group net.local.justday-apps.desktop --key _launch 2>/dev/null || true)
    if [[ -z "$current" || -n "${JUSTDAY_HOTKEY:-}" ]]; then   # keep shortcuts the user changed in Settings
      "$APP_DIR/scripts/setup-hotkey.sh" --talk "$HOTKEY"
      # setup-hotkey пишет desktop-файлы; justday hotkey set отбирает Meta у plasmashell
      # и Alt+Space у KRunner, оставляя Alt+F1 / Alt+F2, и вешает сочетания живьём (без перезахода).
      # Meta → меню JustDay; Meta+. → эмодзи; Alt+Space → поиск программ.
      "$HOME/.local/bin/justday" hotkey set >/dev/null 2>&1 || true
      note "$HOTKEY $(t 'говорить' 'talk') · Meta $(t 'меню' 'menu') · Meta+. $(t 'эмодзи' 'emoji') · Alt+Space $(t 'поиск' 'spotlight') · Meta+K $(t 'написать' 'type')"
    else
      # Upgrade path: talk already set, but older installs lacked Meta→menu, Meta+.→emoji,
      # and/or never stole Alt+Space from KRunner for apps search.
      if [[ -z "$menu_now" || "$menu_now" == "none" ]]; then
        extras+=(--menu Meta)
      fi
      if [[ -z "$emoji_now" || "$emoji_now" == "none" ]]; then
        extras+=(--emoji "Meta+.")
      fi
      # Apps: unset, or still co-owned by KRunner (builtin Alt+Space often missing from the file).
      # Qt key code for Alt+Space is 134217760.
      if [[ -z "$apps_now" || "$apps_now" == "none" ]]; then
        extras+=(--apps "Alt+Space")
      elif gdbus call --session --dest org.kde.kglobalaccel --object-path /kglobalaccel \
             --method org.kde.KGlobalAccel.getGlobalShortcutsByKey 134217760 2>/dev/null \
             | grep -q 'org.kde.krunner.desktop'; then
        extras+=(--apps "Alt+Space")
      fi
      if ((${#extras[@]})); then
        "$HOME/.local/bin/justday" hotkey set "${extras[@]}" >/dev/null 2>&1 \
          || "$APP_DIR/scripts/setup-hotkey.sh" "${extras[@]}" >/dev/null 2>&1 || true
        note "$(t 'ваши +' 'yours +')${extras[*]}"
      else
        note "$(t 'ваши, без изменений' 'yours, unchanged')"
      fi
    fi
  }
  step "$(t 'Горячие клавиши' 'Hotkeys')" hotkeys
fi

# ───────────── notifications: JustDay owns the toasts (+ mute Plasma OSD) ─────────────
#
# Architecture: plasmashell usually keeps org.freedesktop.Notifications on the bus (history,
# tray). JustDay mirrors Notify via dbus-monitor (or becomes the server if the name is free)
# and draws its own toast. Plasma's popup is silenced with Do-Not-Disturb for ~50 years
# (`justday popups island` → island.system_popups = false). Tray history stays.
# Volume/brightness/keyboard OSD: plasmarc [OSD] Enabled=false + plasmaparc VolumeOsd=false
# when island.show_osd is on, so only the JustDay island HUD shows (no duplicate Plasma OSD).
# Manual undo: justday popups system  (and/or island.show_osd=false to restore Plasma OSD)
# If a toast still doubles: System Settings → Notifications → application → disable popups,
# or confirm Do Not Disturb is on.
if command -v kwriteconfig6 >/dev/null || command -v kwriteconfig5 >/dev/null; then
  claim_notifs() {
    if "$HOME/.local/bin/justday" popups island >/dev/null 2>&1; then
      note "$(t 'всплывашки Plasma выкл — показывает JustDay' 'Plasma popups off — JustDay shows them')"
      note "$(t 'OSD Plasma выкл — громкость/яркость на острове' 'Plasma OSD off — volume/brightness on island')"
    else
      # Daemon may not be up yet during a fresh install; write the same keys directly.
      local kw; kw=$(command -v kwriteconfig6 || command -v kwriteconfig5)
      local until
      until=$(date -d '+50 years' '+%Y,%-m,%-d,%-H,%-M,%-S.000' 2>/dev/null \
           || date -v+50y '+%Y,%-m,%-d,%-H,%-M,%-S.000' 2>/dev/null || true)
      if [[ -n "$until" ]]; then
        "$kw" --file plasmanotifyrc --group DoNotDisturb --key Until "$until" || true
        "$kw" --file plasmanotifyrc --group Notifications --key CriticalInDndMode false || true
      fi
      # Durable Plasma 6 OSD mute (Workspace Behavior → visual feedback + Sound volume OSD).
      "$kw" --file plasmarc --group OSD --key Enabled false || true
      "$kw" --file plasmarc --group OSD --key kbdLayoutChangedEnabled false || true
      for _osd_key in VolumeOsd MuteOsd MicrophoneSensitivityOsd PushToTalkOsd \
                      MutedMicrophoneReminderOsd DefaultOutputDeviceOsd; do
        "$kw" --file plasmaparc --group General --key "$_osd_key" false || true
      done
      "$HOME/.local/bin/justday" config set island.system_popups false >/dev/null 2>&1 || true
      "$HOME/.local/bin/justday" config set island.show_notifications true >/dev/null 2>&1 || true
      "$HOME/.local/bin/justday" config set island.show_osd true >/dev/null 2>&1 || true
      note "$(t 'всплывашки Plasma выкл (DND) — показывает JustDay' 'Plasma popups off (DND) — JustDay shows them')"
      note "$(t 'OSD Plasma выкл (plasmarc) — показывает JustDay' 'Plasma OSD off (plasmarc) — JustDay shows it')"
    fi
    printf '     %s%s%s\n' "$D" "$(t 'Вернуть Plasma: justday popups system' 'Restore Plasma: justday popups system')" "$N"
  }
  step "$(t 'Уведомления' 'Notifications')" claim_notifs
fi

# ───────────── first run: a few questions ─────────────
if [[ "$FIRST_RUN" == 1 || "${JUSTDAY_SETUP:-}" == 1 ]] && [[ "${JUSTDAY_SETUP:-}" != 0 ]] && { : </dev/tty; } 2>/dev/null; then
  printf '\n  %s%s%s\n  %s%s%s\n\n' "$B" "$(t 'Пара вопросов' 'A few questions')" "$N" "$D" \
    "$(t 'Модель, голос, микрофон, кнопка, почта. Enter оставляет вариант по умолчанию.' 'Model, voice, microphone, button, mail. Enter keeps the default.')" "$N"
  "$HOME/.local/bin/justday" setup </dev/tty || printf '  %s\n' "$(t 'Мастер прерван — продолжить можно командой justday setup' 'Wizard interrupted — continue with: justday setup')"
fi

# ───────────── what could not be installed without an admin ─────────────
why_missing() {
  case "$1" in
    yt-dlp) t 'музыка и видео с YouTube' 'music and video from YouTube' ;;
    pipewire*) t 'микрофон' 'the microphone' ;;
    espeak-ng) t 'запасной голос' 'the fallback voice' ;;
    quickshell) t 'остров сверху экрана' 'the island at the top of the screen' ;;
    wl-clipboard|xclip) t 'выделенный текст и вставка' 'the selected text and pasting' ;;
    kitty) t 'терминал для длинных команд' 'the terminal for long commands' ;;
    ImageMagick|imagemagick) t 'картинки студии' 'studio pictures' ;;
    spectacle|kde-spectacle) t 'снимки экрана' 'screenshots' ;;
    ffmpeg*) t 'звук и видео' 'sound and video' ;;
    libsecret*) t 'пароли в связке ключей' 'passwords in the keyring' ;;
    plocate|fd|fd-find|ripgrep) t 'быстрый поиск файлов' 'fast file search' ;;
    libnotify*) t 'уведомления' 'notifications' ;;
    *inter*font*|*font*inter*) t 'шрифт островка — без него возьмётся системный' 'the island font — the system one is used instead' ;;
    python3*-tk*|*tkinter*) t 'окно настроек при первом запуске' 'the setup window on first run' ;;
    wmctrl|xdotool|x11-utils|xorg-x11-utils|xorg-xprop) t 'переключение и закрытие окон' 'switching and closing windows' ;;
    maim|scrot) t 'снимки экрана' 'screenshots' ;;
    *) printf '' ;;
  esac
}
mapfile -t MISSING < <(printf '%s\n' "${MISSING[@]:-}" | awk 'NF')
if ((${#MISSING[@]})); then
  printf '\n  %s%s%s\n' "$B$Y" "$(t 'Осталось без администратора' 'Left out: no admin rights')" "$N"
  for pkg in "${MISSING[@]}"; do
    reason=$(why_missing "$pkg")
    printf '     %s%s%s%s\n' "$(pad "$pkg" 22)" "$D" "${reason:+— $reason}" "$N"
  done
  printf '  %s%s%s\n' "$D" "$(t 'Попросите администратора:' 'Ask an admin to run:') ${PM[*]:-<package manager>} ${MISSING[*]}" "$N"
  printf '  %s%s%s\n' "$D" "$(t 'Остальное уже работает — всё лежит в домашней папке.' 'Everything else already works — it all lives in your home folder.')" "$N"
fi

# ───────────── did it actually start? ─────────────
#
# «Скачалось, но не включается» — худший из возможных концов установки: человек видит «Готово», а
# ничего нет, и дальше ему некуда идти. Поэтому спрашиваем systemd прямо здесь и, если служба не
# поднялась, печатаем причину её словами и готовые команды. Установщик, который не проверил
# результат своей работы, перекладывает её на того, кто меньше всех может её сделать.
check_services() {
  local bad=() unit
  systemctl --user show-environment >/dev/null 2>&1 || return 0
  for unit in justday justday-ui; do
    systemctl --user is-active --quiet "$unit.service" || bad+=("$unit")
  done
  ((${#bad[@]})) || return 0
  printf '\n  %s%s%s\n' "$B$Y" "$(t 'Служба не поднялась' 'The service did not start')" "$N"
  for unit in "${bad[@]}"; do
    printf '     %s%s%s %s\n' "$(pad "$unit" 16)" "$D" "$(systemctl --user is-active "$unit.service" 2>&1)" "$N"
    journalctl --user -u "$unit" -n 4 --no-pager -o cat 2>/dev/null | sed "s/^/       ${D}/; s/\$/${N}/"
  done
  printf '  %s%s%s\n' "$D" "$(t 'Что делать:' 'What to do:') justday doctor · journalctl --user -u ${bad[0]} -n 50" "$N"
  printf '  %s%s%s\n' "$D" "$(t 'Весь журнал установки:' 'Full install log:') $LOG" "$N"
}
check_services

# ───────────── done ─────────────
kread=$(command -v kreadconfig6 || command -v kreadconfig5 || echo true)
talk=$("$kread" --file kglobalshortcutsrc --group services --group net.local.justday.desktop --key _launch 2>/dev/null | cut -d, -f1 | cut -f1 || true)
talk=${talk:-$HOTKEY}
plate "$(t 'Готово' 'Done') · $(clock $((SECONDS - STARTED)))" "$chosen · $(mib "$APP_DIR/.venv")"
if ! claude auth status 2>/dev/null | grep -q '"loggedIn": true'; then
  printf '  %s%s%s\n  %s\n\n' "$B" "$(t 'Остался один шаг: войдите в Claude.' 'One step left: sign in to Claude.')" "$N" \
    "$(t 'Наберите' 'Type') ${B}claude${N} $(t 'и в нём' 'and in it') ${B}/login${N}."
fi
if ((SPEECH)); then
  printf '  %s %s%s%s %s\n\n' "$(t 'Нажмите' 'Press')" "$B" "$talk" "$N" "$(t 'и скажите «Привет».' 'and say "Hi".')"
else
  printf '  %s %s%s%s %s\n\n' "$(t 'Нажмите' 'Press')" "$B" "Meta+K" "$N" \
    "$(t 'и напишите «Привет» — распознавания речи в этом наборе нет.' 'and type "Hi" — this selection has no speech recognition.')"
fi
printf '  %s%s%s\n' "$C" "$(pad 'justday setup' 18)" "$N$D$(t 'модель, голос, микрофон, почта' 'model, voice, microphone, mail')$N"
printf '  %s%s%s\n' "$C" "$(pad 'justday parts' 18)" "$N$D$(t 'доставить речь, голос, ускорение NVIDIA' 'add speech, voice, NVIDIA acceleration')$N"
printf '  %s%s%s\n' "$C" "$(pad 'justday doctor' 18)" "$N$D$(t 'проверить, что всё работает' 'check that everything works')$N"
printf '  %s%s%s\n' "$C" "$(pad 'justday popups' 18)" "$N$D$(t 'island = только JustDay · system = ещё Plasma' 'island = JustDay only · system = Plasma too')$N"
printf '  %s%s%s\n' "$C" "$(pad "$(t 'Руководство' 'Manual')" 18)" "$N${D}https://github.com/0nigiris/JustDay/blob/main/docs/MANUAL.md$N"
# Путь к журналу печатается всегда, а не только когда что-то сломалось: он нужен ровно тогда, когда
# установка прошла «успешно», а работать не стало, — и именно в этот момент его никто не помнит.
printf '  %s%s%s\n\n' "$C" "$(pad "$(t 'Журнал' 'Log')" 18)" "$N$D$LOG$N"
