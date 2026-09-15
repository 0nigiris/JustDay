#!/usr/bin/env bash
# Neural voice: Qwen3-TTS (Apache-2.0) through faster-qwen3-tts (MIT, CUDA graphs + streaming) in its own venv.
# Needs an NVIDIA GPU with ~3 GB free VRAM. Downloads ~3 GB (CUDA PyTorch) + ~1.3 GB (0.6B model).
# Usage: setup-voice.sh            then: justday config set tts.engine qwen
set -euo pipefail
REPO="$(cd "$(dirname "$0")/.." && pwd)"
ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/justday/voice"
nvidia-smi >/dev/null 2>&1 || { echo "neural voice needs an NVIDIA GPU; keeping Silero" >&2; exit 1; }
mkdir -p "$ROOT"
[[ -x "$ROOT/.venv/bin/python" ]] || uv venv -q --python 3.12 "$ROOT/.venv"
# transformers pinned: 5.16+ breaks the Mimi codec config used by Qwen3-TTS (rope_theta)
VIRTUAL_ENV="$ROOT/.venv" uv pip install -q "faster-qwen3-tts>=0.4" "transformers==5.15.1" soundfile
"$ROOT/.venv/bin/python" -c "import torch; assert torch.cuda.is_available(), 'CUDA not available'"
echo "downloading the voice model (first run only)…"
"$ROOT/.venv/bin/python" -c "from huggingface_hub import snapshot_download as d; d('Qwen/Qwen3-TTS-12Hz-0.6B-Base')" >/dev/null
mkdir -p "$HOME/.config/systemd/user"
sed "s|@REPO@|$REPO|" "$REPO/systemd/justday-voice.service" > "$HOME/.config/systemd/user/justday-voice.service"
systemctl --user daemon-reload
systemctl --user enable --now justday-voice.service
echo "neural voice ready: justday config set tts.engine qwen   (voices: jarvis, friday)"
