#!/usr/bin/env bash
# JustDay installer — KDE Plasma 6 (Wayland) + Claude Code.
# Usage:  ./install.sh              (from a clone)
#         curl -fsSL https://raw.githubusercontent.com/0nigiris/JustDay/main/install.sh | bash
# Re-running is safe (idempotent). Everything is user-level except missing system packages, for which
# sudo is asked once, with the list shown first.
#
# One line per step. What the tools themselves print goes to ~/.local/state/justday/install.log and is
# shown only when a step fails.
set -euo pipefail

REPO_URL="${JUSTDAY_REPO_URL:-https://github.com/0nigiris/JustDay.git}"
HOTKEY="${JUSTDAY_HOTKEY:-Meta+J}"
STATE_DIR="${XDG_STATE_HOME:-$HOME/.local/state}/justday"
mkdir -p "$STATE_DIR"
LOG="$STATE_DIR/install.log"
: > "$LOG"
NOTE=$(mktemp) WARNS=$(mktemp)
trap 'rm -f "$NOTE" "$WARNS"; if [[ -t 1 ]]; then printf "\e[?25h"; fi' EXIT
STARTED=$SECONDS

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

# step "Title" function args… — the function's output goes to the log; a spinner (and, after a few
# seconds, the time) meanwhile; ✓ with its note, or ✗ with the end of the log and where the rest is.
# It runs as a background job even without a terminal: that is what keeps `set -e` alive inside it.
step() {
  local title=$1; shift
  : > "$NOTE"
  printf '\n── %s\n' "$title" >> "$LOG"
  local rc=0 start=$SECONDS i=0
  "$@" >> "$LOG" 2>&1 &
  local pid=$!
  if [[ $TTY == 1 ]]; then
    printf '\e[?25l'
    while kill -0 "$pid" 2>/dev/null; do
      local el=$((SECONDS - start)) extra=''
      ((el >= 4)) && extra="  $(clock "$el")"
      printf '\r\e[K  %s%s%s  %s%s%s%s' "$C" "${SPIN[i++ % 10]}" "$N" "$title" "$D" "$extra" "$N"
      sleep 0.08
    done
    printf '\e[?25h'
  fi
  wait "$pid" || rc=$?
  if ((rc == 0)); then
    row '✓' "$G" "$title" "$(cat "$NOTE")"
    flush_warns
  else
    row '✗' "$R" "$title" "$(t 'не получилось' 'failed')"
    flush_warns
    printf '\n'
    tail -n 12 "$LOG" | sed "s/^/     ${D}/; s/\$/${N}/"
    printf '\n  %s %s\n  %s %s\n\n' "$(t 'Весь журнал:' 'Full log:')" "$LOG" \
      "$(t 'Установку можно запустить ещё раз — она продолжит с того же места.' 'Running the installer again picks up where it stopped.')" ''
    exit 1
  fi
}

printf '\n  %sJustDay%s\n  %s%s%s\n\n' "$B" "$N" "$D" "$(t 'Голосовой ассистент для KDE Plasma · установка' 'A voice assistant for KDE Plasma · install')" "$N"

# ───────────── the computer ─────────────
desktop="${XDG_CURRENT_DESKTOP:-?}"
if [[ "$desktop" == *KDE* ]]; then
  v=$(plasmashell --version 2>/dev/null | awk '{print $2}' | cut -d. -f1)
  desktop="KDE Plasma${v:+ $v}"
fi
session="${XDG_SESSION_TYPE:-?}"; session="${session^}"
gpu=$(nvidia-smi --query-gpu=name --format=csv,noheader 2>/dev/null | head -1 | sed 's/^NVIDIA //' || true)
row '✓' "$G" "$(t 'Компьютер' 'Computer')" "$desktop · $session${gpu:+ · $gpu}"
[[ "${XDG_SESSION_TYPE:-}" == wayland ]] || warn "$(t 'Не Wayland: управлять рабочим столом получится только в KDE Plasma 6 на Wayland.' 'Not Wayland: desktop control needs KDE Plasma 6 on Wayland.')"
[[ "${XDG_CURRENT_DESKTOP:-}" == *KDE* ]] || warn "$(t 'Не KDE: горячие клавиши и управление столом придётся настроить вручную.' 'Not KDE: hotkeys and desktop control need manual setup.')"
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

# ───────────── system packages (only what is missing) ─────────────
need=()
for pair in pw-record:pipewire-utils wl-copy:wl-clipboard playerctl:playerctl yt-dlp:yt-dlp plocate:plocate \
            fd:fd-find rg:ripgrep jq:jq spectacle:spectacle gtk-launch:gtk3 notify-send:libnotify \
            espeak-ng:espeak-ng git:git kitty:kitty magick:ImageMagick zstd:zstd secret-tool:libsecret qdbus-qt6:qt6-qttools \
            ffmpeg:ffmpeg; do
  command -v "${pair%%:*}" >/dev/null || need+=("${pair#*:}")
done
# the island's typeface
fc-list : family 2>/dev/null | grep -qx Inter || need+=(rsms-inter-fonts)
# the island itself (Fedora ships it in a COPR, Arch in its own repos)
command -v qs >/dev/null || need+=(quickshell)
# kwin-mcp builds dbus-python, pygobject and pycairo from source: compiler + headers + AT-SPI typelib
command -v gcc >/dev/null || need+=(gcc)
command -v pkg-config >/dev/null || need+=(pkgconf-pkg-config)
for pc in dbus-1:dbus-devel glib-2.0:glib2-devel cairo:cairo-devel cairo-gobject:cairo-gobject-devel gobject-introspection-1.0:gobject-introspection-devel \
          atspi-2:at-spi2-core-devel; do
  pkg-config --exists "${pc%%:*}" 2>/dev/null || need+=("${pc#*:}")
done
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
    need=("${need[@]/quickshell/}")   # not packaged for Debian/Ubuntu yet: see the note at the end
  elif command -v pacman >/dev/null; then PM=(sudo pacman -S --needed --noconfirm)
    need=("${need[@]/pipewire-utils/pipewire}"); need=("${need[@]/fd-find/fd}"); need=("${need[@]/ImageMagick/imagemagick}"); need=("${need[@]/libnotify/libnotify}")
    need=("${need[@]/qt6-qttools/qt6-tools}"); need=("${need[@]/gcc/base-devel}"); need=("${need[@]/pkgconf-pkg-config/pkgconf}"); need=("${need[@]/dbus-devel/dbus}")
    need=("${need[@]/glib2-devel/glib2}"); need=("${need[@]/cairo-gobject-devel/cairo}"); need=("${need[@]/cairo-devel/cairo}"); need=("${need[@]/gobject-introspection-devel/gobject-introspection}")
    need=("${need[@]/at-spi2-core-devel/at-spi2-core}"); need=("${need[@]/dbus-tools/dbus}"); need=("${need[@]/rsms-inter-fonts/inter-font}")
  else
    PM=()
  fi
  mapfile -t need < <(printf '%s\n' "${need[@]}" | awk 'NF && !seen[$0]++')
  if ((${#PM[@]} == 0)); then
    row '!' "$Y" "$(t 'Системные пакеты' 'System packages')" "$(t 'неизвестный менеджер пакетов' 'unknown package manager')"
    printf '     %s\n' "$(t 'Поставьте вручную:' 'Install by hand:') ${need[*]}"
  elif sudo -n true 2>/dev/null || { [[ -r /dev/tty ]] && { : </dev/tty; } 2>/dev/null; }; then
    if ! sudo -n true 2>/dev/null; then
      printf '  %s•%s  %s%s%s\n' "$C" "$N" "$(pad "$(t 'Системные пакеты' 'System packages')" 28)" "$D" "${need[*]}"
      printf '     %s%s%s\n' "$D" "$(t 'Для них нужен пароль администратора — только для этого шага.' 'These need your admin password — for this step only.')" "$N"
      sudo -v </dev/tty || { printf '\n  %s\n\n' "$(t 'Без пароля поставить пакеты не получится.' 'Cannot install the packages without the password.')"; exit 1; }
      printf '\e[1A\e[K\e[1A\e[K\e[1A\e[K'   # the list, the hint and sudo's own prompt: the step line replaces them
    fi
    install_packages() {
      [[ -n ${COPR:-} ]] && sudo dnf copr enable -y "$COPR"
      "${PM[@]}" "${need[@]}"; note "$(t 'поставлено' 'installed'): ${#need[@]}"; }
    step "$(t 'Системные пакеты' 'System packages')" install_packages
  else
    row '!' "$Y" "$(t 'Системные пакеты' 'System packages')" "$(t 'некому спросить пароль' 'no terminal to ask for a password')"
    printf '     %s\n' "${PM[*]} ${need[*]}"
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

get_kwin_mcp() {
  command -v uv >/dev/null || curl -LsSf https://astral.sh/uv/install.sh | sh
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

# ───────────── python env and models ─────────────
python_env() {
  local s=$SECONDS
  (cd "$APP_DIR" && uv sync --python 3.12)
  mkdir -p "$HOME/.local/bin"
  ln -sf "$APP_DIR/.venv/bin/justday" "$HOME/.local/bin/justday"
  if ((SECONDS - s < 3)); then note "$(t 'уже на месте' 'up to date')"; else note "$(t 'за' 'in') $(clock $((SECONDS - s)))"; fi
}
step "$(t 'Распознавание и голос' 'Speech and voice')" python_env

models() {
  "$APP_DIR/.venv/bin/python" -c 'from justday.audio import voice_activity_model; voice_activity_model()'
  note "$(t 'паузы в речи и имя ассистента' 'pauses in speech, the assistant name')"
}
step "$(t 'Модели' 'Models')" models

# ───────────── config ─────────────
CONF_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/justday"
BRAIN_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/justday/brain"
FIRST_RUN=0; [[ -f "$CONF_DIR/config.toml" ]] || FIRST_RUN=1
settings() {
  mkdir -p "$CONF_DIR" "$BRAIN_DIR"
  if [[ ! -f "$CONF_DIR/config.toml" ]]; then
    local mic
    mic=$(pactl list short sources 2>/dev/null | awk '{print $2}' | grep -v monitor | grep -viE 'virtual|pwsp|easyeffects' | grep -i usb | head -1 || true)
    sed "s|^input = \"\"|input = \"${mic}\"|" "$APP_DIR/config.example.toml" > "$CONF_DIR/config.toml"
    note "$(t 'созданы' 'created')${mic:+ · $(t 'микрофон' 'microphone') USB}"
  else
    note "$(t 'ваши, без изменений' 'yours, unchanged')"
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
services() {
  mkdir -p "$UNIT_DIR"
  sed "s|@JUSTDAY@|$HOME/.local/bin/justday|; s|@PATH@|$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin|" \
    "$APP_DIR/systemd/justday.service" > "$UNIT_DIR/justday.service"
  systemctl --user daemon-reload
  systemctl --user enable justday.service
  systemctl --user restart justday.service
  if command -v qs >/dev/null; then
    sed "s|@REPO@|$APP_DIR|; s|@QS@|$(command -v qs)|" "$APP_DIR/systemd/justday-island.service" > "$UNIT_DIR/justday-island.service"
    systemctl --user disable --now justday-overlay.service 2>/dev/null || true   # the old GTK pill, now gone
    rm -f "$UNIT_DIR/justday-overlay.service"
    systemctl --user daemon-reload
    systemctl --user enable justday-island.service
    systemctl --user restart justday-island.service
    note "$(t 'ассистент · остров' 'assistant · island')"
  else
    note "$(t 'ассистент · без острова' 'assistant · no island')"
    warn "$(t 'Острову нужен Quickshell — поставьте его и запустите установку ещё раз' 'The island needs Quickshell — install it and run the installer again'): https://quickshell.org/docs/guide/install-setup/"
  fi
  if systemctl --user cat justday-voice.service >/dev/null 2>&1; then
    sed "s|@REPO@|$APP_DIR|" "$APP_DIR/systemd/justday-voice.service" > "$UNIT_DIR/justday-voice.service"
    systemctl --user daemon-reload
    systemctl --user try-restart justday-voice.service
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
if command -v kwriteconfig6 >/dev/null; then
  hotkeys() {
    local current
    current=$(kreadconfig6 --file kglobalshortcutsrc --group services --group net.local.justday.desktop --key _launch 2>/dev/null || true)
    if [[ -z "$current" || -n "${JUSTDAY_HOTKEY:-}" ]]; then   # keep shortcuts the user changed in Settings
      "$APP_DIR/scripts/setup-hotkey.sh" --talk "$HOTKEY"
      note "$HOTKEY $(t 'говорить' 'talk') · Meta+K $(t 'написать' 'type')"
    else
      note "$(t 'ваши, без изменений' 'yours, unchanged')"
    fi
  }
  step "$(t 'Горячие клавиши' 'Hotkeys')" hotkeys
fi

# ───────────── first run: a few questions ─────────────
if [[ "$FIRST_RUN" == 1 || "${JUSTDAY_SETUP:-}" == 1 ]] && [[ "${JUSTDAY_SETUP:-}" != 0 ]] && { : </dev/tty; } 2>/dev/null; then
  printf '\n  %s%s%s\n  %s%s%s\n\n' "$B" "$(t 'Пара вопросов' 'A few questions')" "$N" "$D" \
    "$(t 'Модель, голос, микрофон, кнопка, почта. Enter оставляет вариант по умолчанию.' 'Model, voice, microphone, button, mail. Enter keeps the default.')" "$N"
  "$HOME/.local/bin/justday" setup </dev/tty || printf '  %s\n' "$(t 'Мастер прерван — продолжить можно командой justday setup' 'Wizard interrupted — continue with: justday setup')"
fi

# ───────────── done ─────────────
talk=$(kreadconfig6 --file kglobalshortcutsrc --group services --group net.local.justday.desktop --key _launch 2>/dev/null | cut -d, -f1 | cut -f1 || true)
talk=${talk:-$HOTKEY}
printf '\n  %s%s%s  %s%s%s\n\n' "$B$G" "$(t 'Готово' 'Done')" "$N" "$D" "$(t 'за' 'in') $(clock $((SECONDS - STARTED)))" "$N"
if ! claude auth status 2>/dev/null | grep -q '"loggedIn": true'; then
  printf '  %s%s%s\n  %s\n\n' "$B" "$(t 'Остался один шаг: войдите в Claude.' 'One step left: sign in to Claude.')" "$N" \
    "$(t 'Наберите' 'Type') ${B}claude${N} $(t 'и в нём' 'and in it') ${B}/login${N}."
fi
printf '  %s %s%s%s %s\n\n' "$(t 'Нажмите' 'Press')" "$B" "$talk" "$N" "$(t 'и скажите «Привет».' 'and say "Hi".')"
printf '  %s%s%s\n' "$C" "$(pad 'justday setup' 18)" "$N$D$(t 'модель, голос, микрофон, почта' 'model, voice, microphone, mail')$N"
printf '  %s%s%s\n' "$C" "$(pad 'justday doctor' 18)" "$N$D$(t 'проверить, что всё работает' 'check that everything works')$N"
printf '  %s%s%s\n\n' "$C" "$(pad "$(t 'Руководство' 'Manual')" 18)" "$N${D}https://github.com/0nigiris/JustDay/blob/main/docs/MANUAL.md$N"
