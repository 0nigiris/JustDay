#!/usr/bin/env bash
# Local model for private tasks (mail) and, optionally, as the whole brain (`justday model use ollama qwen3.5:9b`).
# Installs Ollama into the user's home (no sudo), as a user service listening on 127.0.0.1 only.
# Usage: setup-local-llm.sh [model]        default model: qwen3.5:9b (6.6 GB, needs ~8 GB VRAM)
set -euo pipefail
MODEL="${1:-qwen3.5:9b}"
ROOT="${XDG_DATA_HOME:-$HOME/.local/share}/justday/ollama"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
OLLAMA="$ROOT/bin/ollama"
export OLLAMA_HOST=127.0.0.1:11434

if [[ ! -x "$OLLAMA" ]]; then
  ver=$(curl -fsSLI -o /dev/null -w '%{url_effective}' https://github.com/ollama/ollama/releases/latest | sed 's#.*/tag/##')
  echo "Ollama $ver → $ROOT (~1.4 GB)"
  mkdir -p "$ROOT"
  curl -fL --progress-bar "https://github.com/ollama/ollama/releases/download/$ver/ollama-linux-amd64.tar.zst" \
    | zstd -d | tar -x -C "$ROOT"
fi

mkdir -p "$HOME/.config/systemd/user"
cp "$REPO/systemd/justday-ollama.service" "$HOME/.config/systemd/user/"
systemctl --user daemon-reload
systemctl --user enable --now justday-ollama.service
for _ in $(seq 30); do curl -fs "http://$OLLAMA_HOST/api/version" >/dev/null && break; sleep 1; done

if "$OLLAMA" list | awk '{print $1}' | grep -qx "$MODEL"; then
  echo "model $MODEL already present"
  exit 0
fi

echo "pulling $MODEL from the Ollama registry…"
if "$OLLAMA" pull "$MODEL"; then
  exit 0
fi

# The registry stores files on Cloudflare R2, which some ISPs block (TLS error "certificate is not valid").
# Fallback for the default model: the same weights from Hugging Face + Ollama's built-in Qwen 3.5 chat renderer
# (the GGUF's own Jinja template rejects Claude Code's mid-conversation system messages).
if [[ "$MODEL" != "qwen3.5:9b" ]]; then
  echo "pull failed; for other models use a VPN or an hf.co/<repo>:<quant> GGUF" >&2
  exit 1
fi
echo "registry unreachable — fetching the GGUF from Hugging Face instead"
"$OLLAMA" pull hf.co/unsloth/Qwen3.5-9B-GGUF:Q4_K_M
tmp=$(mktemp)
cat > "$tmp" <<'EOF'
FROM hf.co/unsloth/Qwen3.5-9B-GGUF:Q4_K_M
RENDERER qwen3.5
PARSER qwen3.5
PARAMETER temperature 1
PARAMETER top_k 20
PARAMETER top_p 0.95
PARAMETER presence_penalty 1.5
EOF
"$OLLAMA" create "$MODEL" -f "$tmp"
rm -f "$tmp"
echo "model $MODEL ready"
