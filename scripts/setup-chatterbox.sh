#!/usr/bin/env bash
# Голос Chatterbox в своём окружении: ему нужен torch 2.6, а службе Qwen — 2.14.
# Скачивает ≈4 ГБ (torch с CUDA) и ≈3 ГБ модели при первой фразе.
set -euo pipefail
DIR="${XDG_DATA_HOME:-$HOME/.local/share}/justday/chatterbox"
uv venv --python 3.11 "$DIR/.venv"
# setuptools<81: водяной знак perth берёт pkg_resources, в новых setuptools его нет
VIRTUAL_ENV="$DIR/.venv" uv pip install chatterbox-tts "setuptools<81"
APP="$(cd "$(dirname "$0")/.." && pwd)"
UNIT="${XDG_CONFIG_HOME:-$HOME/.config}/systemd/user"
sed "s|@REPO@|$APP|" "$APP/systemd/justday-chatterbox.service" > "$UNIT/justday-chatterbox.service"
cp "$APP/systemd/justday-chatterbox.socket" "$UNIT/"
systemctl --user daemon-reload
systemctl --user enable --now justday-chatterbox.socket
echo "готово: justday config set tts.engine chatterbox"
