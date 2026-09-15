#!/usr/bin/env bash
# JustDay installer — KDE Plasma 6 (Wayland) + Claude Code.
# Usage:  ./install.sh              (from a clone)
#         curl -fsSL https://raw.githubusercontent.com/0nigiris/JustDay/main/install.sh | bash
# Re-running is safe (idempotent). Everything is user-level except missing system packages.
set -euo pipefail

REPO_URL="${JUSTDAY_REPO_URL:-https://github.com/0nigiris/JustDay.git}"
HOTKEY="${JUSTDAY_HOTKEY:-Meta+J}"
say()  { printf '\033[1;36m==>\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m!!\033[0m %s\n' "$*"; }
die()  { printf '\033[1;31mxx\033[0m %s\n' "$*"; exit 1; }

# ---------- locate / fetch the code ----------
if [[ -f "$(dirname "${BASH_SOURCE[0]:-$0}")/pyproject.toml" ]]; then
  APP_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
else
  APP_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/justday/app"
  if [[ -d "$APP_DIR/.git" ]]; then git -C "$APP_DIR" pull --ff-only; else git clone --depth 1 "$REPO_URL" "$APP_DIR"; fi
fi
say "JustDay code: $APP_DIR"
"$APP_DIR/scripts/migrate-from-jarvis.sh" | grep -v "^nothing to migrate$" || true

# ---------- environment checks ----------
[[ "${XDG_SESSION_TYPE:-}" == "wayland" ]] || warn "Not a Wayland session — desktop control (kwin-mcp) needs KDE Plasma 6 on Wayland."
[[ "${XDG_CURRENT_DESKTOP:-}" == *KDE* ]] || warn "Desktop is '${XDG_CURRENT_DESKTOP:-?}', not KDE: hotkey/desktop control will need manual setup."

# ---------- system packages (only what is missing) ----------
need=()
for pair in pw-record:pipewire-utils wl-copy:wl-clipboard playerctl:playerctl yt-dlp:yt-dlp plocate:plocate \
            fd:fd-find rg:ripgrep jq:jq spectacle:spectacle gtk-launch:gtk3 notify-send:libnotify \
            espeak-ng:espeak-ng git:git kitty:kitty magick:ImageMagick zstd:zstd secret-tool:libsecret; do
  command -v "${pair%%:*}" >/dev/null || need+=("${pair#*:}")
done
# on-screen indicator: GTK4 + gtk4-layer-shell through the system Python
/usr/bin/python3 -c 'import gi, cairo; gi.require_version("Gtk4LayerShell", "1.0"); from gi.repository import Gtk4LayerShell' 2>/dev/null \
  || need+=(gtk4-layer-shell python3-gobject python3-cairo)
# kwin-mcp builds dbus-python, pygobject and pycairo from source: compiler + headers + AT-SPI typelib
command -v gcc >/dev/null || need+=(gcc)
command -v pkg-config >/dev/null || need+=(pkgconf-pkg-config)
for pc in dbus-1:dbus-devel glib-2.0:glib2-devel cairo:cairo-devel gobject-introspection-1.0:gobject-introspection-devel \
          atspi-2:at-spi2-core-devel; do
  pkg-config --exists "${pc%%:*}" 2>/dev/null || need+=("${pc#*:}")
done
command -v dbus-monitor >/dev/null || need+=(dbus-tools)
if ((${#need[@]})); then
  if command -v dnf >/dev/null; then PM=(sudo dnf install -y)
  elif command -v apt-get >/dev/null; then PM=(sudo apt-get install -y)
    need=("${need[@]/pkgconf-pkg-config/pkg-config}"); need=("${need[@]/gcc/build-essential}"); need=("${need[@]/dbus-devel/libdbus-1-dev}")
    need=("${need[@]/glib2-devel/libglib2.0-dev}"); need=("${need[@]/cairo-devel/libcairo2-dev}"); need=("${need[@]/dbus-tools/dbus-bin}")
    need=("${need[@]/gobject-introspection-devel/libgirepository-2.0-dev}"); need=("${need[@]/at-spi2-core-devel/libatspi2.0-dev}")
    need=("${need[@]/pipewire-utils/pipewire-bin}"); need=("${need[@]/gtk3/libgtk-3-bin}"); need=("${need[@]/libnotify/libnotify-bin}"); need=("${need[@]/ImageMagick/imagemagick}")
    need=("${need[@]/libsecret/libsecret-tools}"); need=("${need[@]/gtk4-layer-shell/gir1.2-gtk4layershell-1.0}"); need=("${need[@]/python3-gobject/python3-gi}")
  elif command -v pacman >/dev/null; then PM=(sudo pacman -S --needed --noconfirm)
    need=("${need[@]/pipewire-utils/pipewire}"); need=("${need[@]/fd-find/fd}"); need=("${need[@]/ImageMagick/imagemagick}"); need=("${need[@]/libnotify/libnotify}")
    need=("${need[@]/python3-gobject/python-gobject}"); need=("${need[@]/python3-cairo/python-cairo}")
    need=("${need[@]/gcc/base-devel}"); need=("${need[@]/pkgconf-pkg-config/pkgconf}"); need=("${need[@]/dbus-devel/dbus}")
    need=("${need[@]/glib2-devel/glib2}"); need=("${need[@]/cairo-devel/cairo}"); need=("${need[@]/gobject-introspection-devel/gobject-introspection}")
    need=("${need[@]/at-spi2-core-devel/at-spi2-core}"); need=("${need[@]/dbus-tools/dbus}")
  else die "Unknown package manager. Install manually: ${need[*]}"; fi
  say "Installing system packages (sudo): ${need[*]}"
  "${PM[@]}" "${need[@]}"
fi

# ---------- uv, Claude Code, kwin-mcp ----------
export PATH="$HOME/.local/bin:$PATH"
command -v uv >/dev/null || { say "Installing uv"; curl -LsSf https://astral.sh/uv/install.sh | sh; }
if ! command -v claude >/dev/null; then
  say "Installing Claude Code (official installer)"
  curl -fsSL https://claude.ai/install.sh | bash
fi
say "Installing kwin-mcp (KDE desktop MCP server)"
# pinned: plugin/bin/kwin_live.py extends this server's internals (engine, AT-SPI helper)
KWIN_MCP_REV="${KWIN_MCP_REV:-7cef7afc402d3c5892f39825290bbbe1851ae1d0}"
uv tool install --quiet --python 3.12 --reinstall "git+https://github.com/VibeProgramm/kwin-mcp@$KWIN_MCP_REV" || warn "kwin-mcp install failed"

# ---------- python env ----------
say "Installing Python dependencies (faster-whisper, Silero TTS, Agent SDK) — first run downloads ~1.5 GB"
(cd "$APP_DIR" && uv sync --python 3.12 --quiet)
if ! nvidia-smi >/dev/null 2>&1; then
  warn "No NVIDIA GPU detected — speech recognition will run on CPU (set stt.model = \"small\" for speed)."
fi
mkdir -p "$HOME/.local/bin"
ln -sf "$APP_DIR/.venv/bin/justday" "$HOME/.local/bin/justday"
ln -sf "$APP_DIR/.venv/bin/justday" "$HOME/.local/bin/jarvis"   # old name still works

# ---------- config ----------
CONF_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/justday"
BRAIN_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/justday/brain"
mkdir -p "$CONF_DIR" "$BRAIN_DIR" "${XDG_STATE_HOME:-$HOME/.local/state}/justday"
if [[ ! -f "$CONF_DIR/config.toml" ]]; then
  FIRST_RUN=1
  mic=$(pactl list short sources 2>/dev/null | awk '{print $2}' | grep -v monitor | grep -viE 'virtual|pwsp|easyeffects' | grep -i usb | head -1 || true)
  sed "s|^input = \"\"|input = \"${mic}\"|" "$APP_DIR/config.example.toml" > "$CONF_DIR/config.toml"
  say "Wrote $CONF_DIR/config.toml (mic: ${mic:-system default})"
fi
if [[ ! -f "$BRAIN_DIR/CLAUDE.md" ]]; then
  "$APP_DIR/scripts/make-profile.sh" > "$BRAIN_DIR/CLAUDE.md"
  say "Wrote machine/user profile $BRAIN_DIR/CLAUDE.md (edit it freely)"
fi

# ---------- systemd user service ----------
if ! systemctl --user show-environment >/dev/null 2>&1; then
  warn "No systemd user session here (container/SSH?) — services, hotkeys and the island are skipped. Run install.sh again from your desktop session."
  echo "Installed the program files only. Commands work: justday model list, justday doctor"
  exit 0
fi
UNIT_DIR="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
mkdir -p "$UNIT_DIR"
sed "s|@JUSTDAY@|$HOME/.local/bin/justday|; s|@PATH@|$HOME/.local/bin:/usr/local/bin:/usr/bin:/bin|" \
  "$APP_DIR/systemd/justday.service" > "$UNIT_DIR/justday.service"
systemctl --user daemon-reload
systemctl --user enable justday.service >/dev/null 2>&1
systemctl --user restart justday.service
# on-screen indicator: the Quickshell Dynamic Island when available, otherwise the simple GTK pill
if command -v qs >/dev/null; then
  sed "s|@REPO@|$APP_DIR|; s|@QS@|$(command -v qs)|" "$APP_DIR/systemd/justday-island.service" > "$UNIT_DIR/justday-island.service"
  systemctl --user disable --now justday-overlay.service >/dev/null 2>&1 || true; rm -f "$UNIT_DIR/justday-overlay.service"
  systemctl --user daemon-reload
  systemctl --user enable justday-island.service >/dev/null 2>&1
  systemctl --user restart justday-island.service
  fc-list : family | grep -qx Inter || warn "Font Inter not found — the island falls back to the default font (dnf install rsms-inter-fonts / pacman -S inter-font / apt install fonts-inter)"
  say "Services justday.service + justday-island.service (Dynamic Island) started"
else
  sed "s|@REPO@|$APP_DIR|" "$APP_DIR/systemd/justday-overlay.service" > "$UNIT_DIR/justday-overlay.service"
  systemctl --user daemon-reload
  systemctl --user enable justday-overlay.service >/dev/null 2>&1
  systemctl --user restart justday-overlay.service
  warn "Quickshell not found — using the simple indicator. For the Dynamic Island install quickshell (Fedora: dnf copr enable errornointernet/quickshell && dnf install quickshell; Arch: pacman -S quickshell) and rerun install.sh"
fi

# ---------- local model (private mail; optional brain) ----------
vram=$(nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits 2>/dev/null | head -1 || echo 0)
# the setup wizard offers it (local brain / private mail); JUSTDAY_LOCAL_LLM=1 installs it right away
if [[ "${JUSTDAY_LOCAL_LLM:-}" == 1 ]]; then
  say "Local model (Ollama + Qwen 3.5 9B, ~8 GB download)"
  "$APP_DIR/scripts/setup-local-llm.sh" || warn "Local model setup failed — rerun scripts/setup-local-llm.sh later"
fi
[[ "${JUSTDAY_VOICE:-}" == 1 ]] && { "$APP_DIR/scripts/setup-voice.sh" || warn "Neural voice setup failed"; }
if systemctl --user cat justday-voice.service >/dev/null 2>&1; then
  sed "s|@REPO@|$APP_DIR|" "$APP_DIR/systemd/justday-voice.service" > "$UNIT_DIR/justday-voice.service"
  systemctl --user daemon-reload; systemctl --user try-restart justday-voice.service
fi

# ---------- global hotkey (KDE) ----------
if command -v kwriteconfig6 >/dev/null; then
  current=$(kreadconfig6 --file kglobalshortcutsrc --group services --group net.local.justday.desktop --key _launch 2>/dev/null || true)
  if [[ -z "$current" || -n "${JUSTDAY_HOTKEY:-}" ]]; then  # keep shortcuts the user changed in Settings
    "$APP_DIR/scripts/setup-hotkey.sh" --talk "$HOTKEY" || warn "Hotkey registration failed — set it in System Settings → Shortcuts"
  fi
fi

# ---------- first-run wizard ----------
FIRST_RUN="${FIRST_RUN:-0}"
if [[ "$FIRST_RUN" == 1 || "${JUSTDAY_SETUP:-}" == 1 ]] && [[ -e /dev/tty ]] && [[ "${JUSTDAY_SETUP:-}" != 0 ]]; then
  say "Setup wizard (model, voice, microphone, button, mail) — Enter keeps the default"
  "$HOME/.local/bin/justday" setup </dev/tty || warn "Wizard interrupted — run: justday setup"
fi

# ---------- post-install ----------
cat <<EOF

JustDay installed.
  Hotkey:        $HOTKEY  (press, speak, it stops listening when you pause; press again to interrupt)
  Mouse button:  $APP_DIR/scripts/setup-hotkey.sh $HOTKEY --mouse ExtraButton1   (thumb 'back' button)
  Diagnose:      justday doctor
  Logs:          justday logs -f
  Text command:  justday ask "открой браузер"
  Setup again:   justday setup          (or: click the island → gear icon)
  Mail (local):  justday mail setup      (Google app password; letters never go to the cloud)
  Model:         justday model list      (Claude subscription, local Ollama, OpenRouter, DeepSeek…)
  Manual:        $APP_DIR/docs/MANUAL.md

If Claude Code is not logged in yet, run:  claude   (then /login)
Browser control needs the "Claude" extension in a Chromium browser: run 'claude --chrome' once.
EOF
