# Kira

Voice-to-text menubar / tray app for **macOS** and **Windows 11**. Hold a hotkey, speak, release — polished text appears at the cursor.

## Features

- 100 % local: Whisper (Apple MLX on Mac / faster-whisper+CUDA on Win) + Ollama
- Context-aware polish: Mail, Slack, Terminal, VS Code, Cursor, Obsidian, etc.
- German + English auto-detect
- Live waveform HUD
- Zero recurring cost

---

## macOS (`main` branch)

### Requirements
- macOS with Apple Silicon (M1 or newer)
- Python 3.12+
- [Ollama](https://ollama.com) installed

### Install
```bash
git clone https://github.com/MikeGT4/kira.git
cd kira
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e '.[mac,dev]'
ollama pull gemma2:2b
kira
```

### Permissions (first run)
- Microphone — to record your voice
- Accessibility — to inject text via Cmd+V
- Input Monitoring — for the global hotkey

---

## Windows — End-user install

Download the latest `Kira-Setup-vX.Y.Z.exe` from [GitHub Releases](https://github.com/MikeGT4/kira/releases/latest).

1. Doppelklick auf die `.exe`.
2. Falls Windows Defender SmartScreen warnt: „Weitere Informationen" → „Trotzdem ausführen". (Kira ist nicht code-signed.)
3. Wizard durchklicken (Welcome → Lizenz → Pfad → Optionen → Installieren → Fertig).
4. Nach „Fertig" startet Kira automatisch in der Tray-Leiste.
5. **F8 halten → sprechen → loslassen.** Polierter Text erscheint im aktiven Eingabefeld.

### Voraussetzungen
- Windows 11 (10 sollte gehen, ungetestet)
- NVIDIA-GPU mit ≥ 12 GB VRAM (empfohlen RTX 4080+/5080+)
- 25 GB freier Speicher

---

## Windows — Developer install (`windows-port` branch)

### Requirements
- Windows 11
- Python 3.12 installed on Windows (`py -3.12 --version` works from PowerShell)
- WSL2 Ubuntu with NVIDIA CUDA-for-WSL driver (`nvidia-smi` returns the GPU inside WSL)
- `uv` (`py -3.12 -m pip install uv` if not on PATH)
- Repo cloned in WSL at `/home/<user>/claude_kira`

### Install (three scripts, run in order)

```bash
# Ollama in WSL — pulls gemma3:12b (~7 GB)
bash scripts/install_wsl_ollama.sh
```

```powershell
# Windows venv (runtime)
powershell -ExecutionPolicy Bypass -File \\wsl.localhost\Ubuntu\home\<user>\claude_kira\scripts\install_win.ps1

# Autostart (optional)
powershell -ExecutionPolicy Bypass -File \\wsl.localhost\Ubuntu\home\<user>\claude_kira\scripts\install_autostart.ps1
```

### Run manually
```powershell
C:\Users\<user>\kira-venv\Scripts\kira.exe
```

### Troubleshooting

| Problem | Fix |
|---|---|
| Tray icon never appears | Check log at `%LOCALAPPDATA%\Kira\kira.log` |
| faster-whisper cuDNN error | `py -3.12 -m uv pip install --python C:\Users\<user>\kira-venv\Scripts\python.exe --force-reinstall nvidia-cudnn-cu12` |
| "Ollama unreachable" toast | In WSL: `curl http://localhost:11434/api/tags` — if it fails, re-run `install_wsl_ollama.sh` |
| Text lands in wrong window | Foreground window at *release* time is the target — don't Alt+Tab mid-record. |
| Admin-elevated app doesn't react to F8 | The keyboard hook can't see events in elevated windows unless Kira runs elevated. |

---

## Config

Edit `~/.config/kira/config.yaml` (Mac) or `%APPDATA%\Kira\config.yaml` (Windows). On Windows, Tray → „Einstellungen…" gives you a form for the common knobs (mic gain, mic device, language, polish model, hotkey).

## License

Personal use. See `LICENSE`.
