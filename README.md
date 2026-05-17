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

1. Lade `Kira-Setup-v0.2.2.exe` (~2 MB Setup-Stub) und `SHA256SUMS.txt` in **denselben** Ordner herunter.
   - Bei diesem Build löst Inno Disk-Spanning aus — daneben liegen `Kira-Setup-v0.2.2-1.bin` und `Kira-Setup-v0.2.2-2.bin`, die müssen mit in den selben Ordner.
2. Doppelklick auf `Kira-Setup-v0.2.2.exe`. Inno findet die `.bin`-Slices automatisch.
3. Falls Windows Defender SmartScreen warnt: „Weitere Informationen" → „Trotzdem ausführen". (Kira ist nicht code-signed.)
4. Inno-Wizard durchklicken (Welcome → Lizenz → Pfad → Installieren → Fertig).
5. **Beim ersten Start** erscheint automatisch ein zweiter Wizard, der ~10 GB Modelle pullt: Whisper-large-v3 (~3 GB) von Hugging Face plus Gemma 3 12B (~8 GB) via Ollama. Das geht einmalig, danach ist alles offline.
6. Nach „Fertigstellen" startet Kira automatisch in der Tray-Leiste — gelb gerahmtes Logo.
7. **F8 halten → sprechen → loslassen.** Polierter Text erscheint im aktiven Eingabefeld.

> **Tipp:** Mit `certutil -hashfile Kira-Setup-v0.2.2.exe SHA256` gegen die Hashes in `SHA256SUMS.txt` prüfen, falls du dem Download nicht traust (kein Code-Signing).

### Voraussetzungen

- Windows 11 (10 sollte gehen, ungetestet)
- NVIDIA-GPU mit ≥ 12 GB VRAM (empfohlen RTX 4080+ / 5080+)
- 25 GB freier Speicher (Slim-Installer ~3.5 GB + First-Run-Wizard zieht weitere ~10 GB Modelle in `%USERPROFILE%\models\` und `%USERPROFILE%\.ollama\`)
- Stabile Internet-Verbindung beim ersten Start (Wizard-Pull, einmalig)

---

## Developer install

### Requirements

- Windows 11
- Python 3.12 installed on Windows (`py -3.12 --version` works from PowerShell)
- NVIDIA driver with CUDA support (`nvidia-smi` works in PowerShell)
- `uv` (`py -3.12 -m pip install uv` if not on PATH)
- Ollama for Windows (`winget install Ollama.Ollama`) — needed for the LLM polish layer; pulls `gemma3:12b` automatically on first use
- Git for Windows

### Install (clone + run)

```powershell
git clone https://github.com/MikeGT4/kira.git C:\Users\<user>\dev\kira
cd C:\Users\<user>\dev\kira

# 1. Windows venv (runtime). Creates %USERPROFILE%\kira-venv,
#    installs faster-whisper / pystray / PyQt6, embeds the branded
#    icon into kira.exe / kira-once.exe.
.\scripts\install_win.ps1

# 2. Pull Polish-LLM
ollama pull gemma3:12b

# 3. Autostart (optional)
.\scripts\install_autostart.ps1
```

The scripts default `-Source` to the repo containing them; pass `-Source <path>` to install from a different checkout (e.g. a UNC path during dual-tree dev).

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
| „Ollama unreachable" toast | `curl http://127.0.0.1:11434/api/tags` from PowerShell — if it fails, restart `ollama app.exe` from `%LOCALAPPDATA%\Programs\Ollama\` or reinstall via `winget install Ollama.Ollama`. Use `127.0.0.1` not `localhost` (Win11 24H2+ resolves localhost to IPv6, Ollama binds IPv4). |
| Text lands in the wrong window | The foreground window at *release* time is the target — don't Alt+Tab while recording. |
| Admin-elevated app doesn't react to F8 | The Windows keyboard hook can't see events in elevated windows unless Kira itself runs elevated. Trade-off; not planned to fix. |

---

## Config

`%APPDATA%\Kira\config.yaml`. Tray → „Einstellungen…" gives you a form for the common knobs (mic gain, mic device, language, polish model, hotkey).

The `audio.input_device` value is a substring match — `'ROG Theta'` matches `Mikrofon (ROG Theta Ultimate 7.)`, `'Shure MV7+'` matches `Mikrofon (2- Shure MV7+)`. If the configured device isn't currently enumerated, Kira logs a `WARNING kira.recorder` line listing every input device it *did* see, which makes it easy to spot whether you wrote the wrong substring or the device just isn't plugged in.

**Pin your physical mic even if Windows shows it as the default.** On boxes with an ASUS Intelligo / „AI Noise-Canceling Microphone" filter installed, the Windows default can flip to that virtual filter device transiently — for example while a USB microphone is still enumerating during cold-boot — and the filter aggressively kills speech as noise. Symptom in `kira.log`: `Recorder.stop: ... peak=0.0002 rms=0.0001` followed by Whisper hallucinating „Vielen Dank." → Hallucination-Filter aborts the pipeline → no text injected. Pinning bypasses the filter. If the USB device isn't enumerated yet when you press the hotkey, you get `DeviceUnavailable` and a 3 s yellow tray icon — clearly visible — instead of a silent dictation.

### Schneller Modus (v0.2.2+)

In den Einstellungen → Polish-LLM gibt's eine Checkbox **„Schneller Modus (gemma3:4b)"**. Wenn das 12B-Modell bei dir öfter in den CPU-Offload rutscht (sichtbar in `ollama ps` als `49/51 CPU/GPU`), schaltet die Box auf das schnellere 4B-Modell um. Beim ersten Aktivieren wird `gemma3:4b` einmalig nachgeladen (~3 GB, Progress-Dialog mit Cancel).

Trade-offs: Standard-Polish (Punktuation, Filler) bleibt praktisch identisch, F9-AI-Editing-Commands werden merkbar schwächer, bei sehr langen Briefings (>250 Zeichen) wird der Stil leicht inkonsistenter. Default ist aus — bestehende User merken vom Upgrade nichts.

---

## License

Personal use. See `LICENSE` (EN + DE).
