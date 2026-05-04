# Kira

Voice-to-text tray app for **Windows 11** with NVIDIA GPU. Hold a hotkey, speak, release — polished text appears at the cursor.

100 % local: `faster-whisper` (CUDA) for transcription, Ollama (Gemma 3 12B) for context-aware polish. No subscriptions, no cloud calls, no recurring cost.

> **Status:** Windows 11 build is ready (this `windows-port` branch). macOS port is in development (`main` branch) — code exists but is not yet release-ready, please don't try to install it from `main` until that note disappears.

---

## What it does

- **Hold-to-record hotkey (F8 default).** 250 ms pre-roll buffer captures the first word even if you start speaking before the keyboard hook fires.
- **Whisper (faster-whisper, CUDA).** German + English auto-detect, runs on the GPU.
- **Polish via Ollama.** Detects the active app (Mail, Slack, Terminal, VS Code, Cursor, Obsidian, …) and rewrites in the right register. Model stays warm for 24 h, so the first F8 after boot has the same latency as the hundredth.
- **Live HUD.** Waveform during recording, status text during transcribe / polish / inject.
- **Branded tray icon.** Yellow rounded-square background with the Kira logo, visible in both Light- and Dark-mode trays. Red overlay-dot during recording, orange-red on errors.
- **Tolerant of a missing microphone.** If the configured input device isn't connected when Kira starts (USB headset off, hardware mute), the app comes up anyway — pressing F8 turns the tray icon yellow-orange for 3 s instead of crashing the process. Reconnect the mic and the next F8 works again.
- **Crash diagnostics.** `faulthandler`, threading exception hook, Qt message handler and a 60 s heartbeat all flow into `kira.log`, so post-mortem debugging works even though `pythonw.exe` has no stderr.

---

## End-user install

Download von der [Releases-Seite](https://github.com/MikeGT4/kira/releases/latest):

1. **Alle 8 Assets** in **denselben** Ordner herunterladen (~13 GB, leerer Ordner mit 25 GB freiem Speicher empfohlen):
   - `Kira-Setup-v0.1.0.exe` (Setup-Wizard, 2 MB)
   - `Kira-Setup-v0.1.0-1.bin` … `-7.bin` (sieben 2 GB-Splits, Inno Setup verlangt sie alle nebeneinander)
2. Doppelklick auf die `.exe`. Inno findet die `.bin`-Slices automatisch.
3. Falls Windows Defender SmartScreen warnt: „Weitere Informationen" → „Trotzdem ausführen". (Kira ist nicht code-signed.)
4. Wizard durchklicken (Welcome → Lizenz → Pfad → Optionen → Installieren → Fertig).
5. Nach „Fertig" startet Kira automatisch in der Tray-Leiste — gelb-orangenes Icon mit dem Kira-Logo.
6. **F8 halten → sprechen → loslassen.** Polierter Text erscheint im aktiven Eingabefeld.

> **Tipp:** Auf der Release-Seite sieht „Assets" zusammengeklappt aus — auf den Pfeil klicken, dann siehst du alle 8 Files. Nicht nur die `.exe` ziehen, sonst meldet der Wizard „Disk slice not found" nach den ersten paar MB.

### Voraussetzungen

- Windows 11 (10 sollte gehen, ungetestet)
- NVIDIA-GPU mit ≥ 12 GB VRAM (empfohlen RTX 4080+ / 5080+)
- 25 GB freier Speicher (Whisper-Modell + Gemma 3 12B + Ollama-Runtime)

---

## Developer install

### Requirements

- Windows 11
- Python 3.12 installed on Windows (`py -3.12 --version` works from PowerShell)
- WSL2 Ubuntu with NVIDIA CUDA-for-WSL driver (`nvidia-smi` returns the GPU inside WSL)
- `uv` (`py -3.12 -m pip install uv` if not on PATH)
- Repo cloned in WSL at `/home/<user>/claude_kira` (current dev setup; the install scripts hardcode this path — porting them to a generic location is on the roadmap)

### Install (three scripts, run in order)

```bash
# 1. Ollama in WSL — pulls gemma3:12b (~7 GB)
bash scripts/install_wsl_ollama.sh
```

```powershell
# 2. Windows venv (runtime). Creates C:\Users\<user>\kira-venv,
#    installs faster-whisper / pystray / PyQt6, embeds the branded
#    icon into kira.exe / kira-once.exe.
powershell -ExecutionPolicy Bypass -File \\wsl.localhost\Ubuntu\home\<user>\claude_kira\scripts\install_win.ps1

# 3. Autostart (optional)
powershell -ExecutionPolicy Bypass -File \\wsl.localhost\Ubuntu\home\<user>\claude_kira\scripts\install_autostart.ps1
```

### Run manually

```powershell
C:\Users\<user>\kira-venv\Scripts\kira.exe
```

### Re-embed the branded icon

`pip install` regenerates the entry-point wrappers without resource info, so the EXE icon falls back to the generic Python icon. Re-run after every reinstall:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\embed_icon.ps1
```

If you change the source logo (`assets/icon.ico`), regenerate the branded variant first:

```powershell
py -3.12 scripts\regenerate_branded_icon.py
```

### Troubleshooting

| Symptom | Fix |
|---|---|
| Tray icon never appears | Check `%LOCALAPPDATA%\Kira\kira.log` for boot errors; native crashes land in `%LOCALAPPDATA%\Kira\kira-faulthandler.log`. |
| F8 press does nothing visible | Watch `kira.log` — every press logs either `Recorder.stop` (success) or `WARNING kira.app: Hotkey press but input device unavailable` (mic missing). Tray icon turns yellow-orange for 3 s in the second case; if your tray icons are auto-hidden in Windows 11 you may need to pin Kira's icon for the state-change to be visible. |
| `faster-whisper` cuDNN error | `py -3.12 -m uv pip install --python C:\Users\<user>\kira-venv\Scripts\python.exe --force-reinstall nvidia-cudnn-cu12` |
| „Ollama unreachable" toast | In WSL: `curl http://localhost:11434/api/tags` — if it fails, re-run `install_wsl_ollama.sh`. |
| Text lands in the wrong window | The foreground window at *release* time is the target — don't Alt+Tab while recording. |
| Admin-elevated app doesn't react to F8 | The Windows keyboard hook can't see events in elevated windows unless Kira itself runs elevated. Trade-off; not planned to fix. |

---

## Config

`%APPDATA%\Kira\config.yaml`. Tray → „Einstellungen…" gives you a form for the common knobs (mic gain, mic device, language, polish model, hotkey).

The `audio.input_device` value is a substring match — `'ROG Theta'` matches `Mikrofon (ROG Theta Ultimate 7.)`. If the configured device isn't currently enumerated, Kira logs a `WARNING kira.recorder` line listing every input device it *did* see, which makes it easy to spot whether you wrote the wrong substring or the device just isn't plugged in.

---

## License

Personal use. See `LICENSE` (EN + DE).
