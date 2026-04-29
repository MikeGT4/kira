# Kira

Voice-to-text menubar app for macOS. Hold `⌥+Space`, speak, release — polished text appears at the cursor.

## Features

- 100 % local: mlx-whisper (large-v3-turbo) + Ollama (gemma2:2b)
- Context-aware polish: Mail, Slack, Terminal, VS Code, etc.
- German + English auto-detect
- Live waveform HUD
- Zero recurring cost

## Requirements

- macOS with Apple Silicon (M1 or newer)
- Python 3.12+
- [Ollama](https://ollama.com) installed

## Install

```bash
git clone https://github.com/MikeGT4/kira.git
cd kira
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e '.[dev]'
ollama pull gemma2:2b
kira
```

## Build `.app`

```bash
./scripts/build_app.sh
# drag dist/Kira.app to /Applications
```

## Permissions (first run)

- Microphone — to record your voice
- Accessibility — to inject text via Cmd+V
- Input Monitoring — for the global hotkey

## Config

Edit `~/.config/kira/config.yaml`.

## License

Personal use. See `LICENSE`.
