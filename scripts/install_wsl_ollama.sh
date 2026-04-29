#!/usr/bin/env bash
# Install Ollama inside WSL2 Ubuntu and pull gemma3:12b for Kira polish.
# Assumes CUDA already works in WSL (nvidia-smi returns the 5090).
set -euo pipefail

MODEL="${KIRA_POLISH_MODEL:-gemma3:12b}"

echo "==> Verifying CUDA in WSL"
if ! command -v nvidia-smi >/dev/null 2>&1; then
    echo "ERROR: nvidia-smi not found. Install NVIDIA CUDA-for-WSL driver on Windows host first."
    echo "  See: https://developer.nvidia.com/cuda/wsl"
    exit 1
fi
nvidia-smi --query-gpu=name,memory.total --format=csv,noheader

echo
echo "==> Checking for existing Ollama"
if command -v ollama >/dev/null 2>&1; then
    echo "Ollama already installed: $(ollama --version 2>&1 | head -1)"
else
    echo "==> Installing Ollama (official script)"
    curl -fsSL https://ollama.com/install.sh | sh
fi

echo
echo "==> Starting Ollama service"
if command -v systemctl >/dev/null 2>&1 && systemctl is-system-running 2>/dev/null | grep -qE "running|degraded"; then
    sudo systemctl enable --now ollama
    sudo systemctl status ollama --no-pager || true
else
    # Non-systemd WSL — start manually in background
    if ! pgrep -f "ollama serve" >/dev/null; then
        echo "Starting 'ollama serve' in background (non-systemd WSL)"
        nohup ollama serve >/tmp/ollama.log 2>&1 &
        sleep 2
    fi
fi

echo
echo "==> Health-check"
for i in 1 2 3 4 5; do
    if curl -sf http://localhost:11434/api/tags >/dev/null; then
        echo "Ollama reachable on localhost:11434"
        break
    fi
    echo "Waiting for Ollama... ($i/5)"
    sleep 2
done

echo
echo "==> Pulling model: $MODEL (this can take several minutes)"
ollama pull "$MODEL"

echo
echo "==> Smoke-test: polish a German sentence"
PROMPT_TEST="Korrigiere das folgende per Spracherkennung transkribierte Fragment. Nur der korrigierte Text, ohne Einleitung:

ähm also das ist ein test"
ollama run "$MODEL" "$PROMPT_TEST" | head -3

echo
echo "==> Done. Windows-Kira can now reach Ollama at http://localhost:11434"
