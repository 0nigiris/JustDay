#!/usr/bin/env bash
# Студия (ComfyUI) по кнопке «Поставить» в островке: в ядро её не кладём — локальное 3D и видео нужны не всем,
# а весят десятки гигабайт (П6). Всё ложится в домашнюю папку, без sudo; движок слушает только 127.0.0.1.
# Ставится движок и одна модель — картинки (Flux schnell, 17 ГБ). Остальные модели (правка, видео, музыка, 3D)
# студия называет сама, когда понадобятся: качать 60 ГБ «на всякий случай» незачем.
set -euo pipefail
ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/justday/studio"
COMFY="$ROOT/ComfyUI"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
UV="$(command -v uv || echo "$HOME/.local/bin/uv")"
mkdir -p "$ROOT"

if [[ ! -f "$COMFY/main.py" ]]; then
  echo "ComfyUI → $COMFY"
  git clone --depth 1 https://github.com/comfyanonymous/ComfyUI "$COMFY"
fi
if [[ ! -x "$ROOT/venv/bin/python" ]]; then
  "$UV" venv --python 3.12 "$ROOT/venv"
fi
# Колёса torch под CUDA — только при видеокарте NVIDIA; без неё ставится сборка для процессора (медленно, но работает).
if command -v nvidia-smi >/dev/null; then
  index=https://download.pytorch.org/whl/cu128
else
  index=https://download.pytorch.org/whl/cpu
fi
VIRTUAL_ENV="$ROOT/venv" "$UV" pip install --index-url "$index" torch torchvision torchaudio
VIRTUAL_ENV="$ROOT/venv" "$UV" pip install -r "$COMFY/requirements.txt"

get() {  # папка файл адрес — докачивает, если оборвалось
  mkdir -p "$COMFY/models/$1"
  [[ -s "$COMFY/models/$1/$2" ]] && return 0
  echo "модель $2"
  curl -fL --progress-bar -C - -o "$COMFY/models/$1/$2.part" "$3"
  mv "$COMFY/models/$1/$2.part" "$COMFY/models/$1/$2"
}
get checkpoints flux1-schnell-fp8.safetensors \
  https://huggingface.co/Comfy-Org/flux1-schnell/resolve/main/flux1-schnell-fp8.safetensors
get upscale_models 4x-UltraSharp.pth https://huggingface.co/Kim2091/UltraSharp/resolve/main/4x-UltraSharp.pth

"$REPO/.venv/bin/justday" config set studio.comfy_dir "$COMFY" >/dev/null
"$REPO/.venv/bin/justday" config set studio.python "$ROOT/venv/bin/python" >/dev/null
echo "студия готова: $COMFY"
