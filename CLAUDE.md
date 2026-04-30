# Kira — developer notes

Personal-use voice-to-text app. macOS menubar (`main` branch) + Windows 11
tray (`windows-port` branch). Hold a hotkey, speak, release — polished
text appears at the cursor.

## Branch strategy

- **`main`** — macOS build. Apple MLX-Whisper, rumps, PyObjC. Imports
  `kira.hotkey`, `kira.injector`, `kira.context`, `kira.permissions`,
  `kira.welcome`, `kira.transcriber`, `kira.ui.menubar`, `kira.ui.popup`.
- **`windows-port`** — Windows 11 + WSL2 build. faster-whisper+CUDA,
  pystray, PyQt6, pywin32, `keyboard` lib. Imports the `*_win.py` peer
  modules (`hotkey_win`, `injector_win`, `context_win`, `permissions_win`,
  `welcome_win`, `transcriber_fw`, `ui/tray_win`, `ui/hud_qt`).

### Dual-branch rules

- **Platform-specific files live on exactly one branch.** Don't port
  these between branches: `kira/hotkey.py` (Mac-only), `kira/hotkey_win.py`
  (Win-only), `kira/ui/menubar.py` (Mac), `kira/ui/tray_win.py` (Win),
  `scripts/build_app.sh` (Mac), `scripts/install_*.ps1` (Win),
  `scripts/install_wsl_ollama.sh` (Win).
- **Shared modules that are platform-aware** (`kira/main.py`,
  `kira/app.py`, `kira/config.py`) branch via `if sys.platform == "win32":`
  in the same file. Cherry-pick changes to common parts between branches;
  the platform-specific sections diverge naturally.
- **Truly shared, platform-agnostic files** (`kira/recorder.py`,
  `kira/styler.py`, `kira/cli.py`, `prompts/*.md`, test fixtures, specs)
  stay in lockstep — cherry-pick to the other branch the same session
  when they change.

### Merging

- `windows-port` was forked from `main` and contains the full Mac history.
  Periodic `git merge main` into `windows-port` keeps the shared pieces
  in sync without polluting `main` with Windows commits.
- Do NOT merge `windows-port` into `main` — it would pull Windows-only
  files into the Mac build.

## Runtime paths

### Windows
- Source: WSL `/home/<user>/claude_kira/`
- Venv: `C:\Users\<user>\kira-venv\` (Windows-side, NOT WSL — binary
  wheels with CUDA/Qt6 DLLs need to be on a real NTFS path)
- Launcher: `C:\Users\<user>\kira-venv\Scripts\kira.exe`
- Autostart: `%APPDATA%\Microsoft\Windows\Start Menu\Programs\Startup\Kira.lnk`
- Log (Python + Qt + heartbeat): `%LOCALAPPDATA%\Kira\kira.log`
- Log (native crashes — CUDA/audio/Qt DLL): `%LOCALAPPDATA%\Kira\kira-faulthandler.log`
- Config: `%APPDATA%\Kira\config.yaml`
- Whisper model cache: `%USERPROFILE%\.cache\faster-whisper\` (or pinned
  to a local dir via `whisper.model: C:/Users/<user>/models/...`)

### macOS
- Source: project dir on local filesystem
- Venv: project-local `.venv/`
- Log: `~/Library/Logs/kira.log`
- Config: `~/.config/kira/config.yaml`

## Crash forensics

`pythonw.exe` has no stderr, so without explicit hooks every native
crash and every daemon-thread exception dies silently. `run()` in
`kira/main.py` wires up four channels at boot:

- `faulthandler` (writes raw frames to `kira-faulthandler.log` —
  separate file because it bypasses the logging formatter)
- `sys.excepthook` → top-level Python exceptions into `kira.log`
- `threading.excepthook` → daemon-thread exceptions into `kira.log`
- `qInstallMessageHandler` → Qt warnings/criticals as `kira.qt` logger

Plus a 60-s heartbeat (`heartbeat: uptime=Ns`) so post-mortem can
floor "when did Kira die?" without correlating user interactions.

**When investigating a crash, always read both log files** — Python
exceptions land in `kira.log`, native crashes in `kira-faulthandler.log`.

## Tray-app lifecycle

Kira runs as a tray-only app — pystray's icon is **not** a Qt window.
Qt's default `quitOnLastWindowClosed=True` therefore tears down the
process whenever a modal dialog (Settings, About, Welcome) closes,
because Qt sees zero open windows afterwards. `_run_windows()` calls
`qt_app.setQuitOnLastWindowClosed(False)` right after the
`QApplication` constructor; only the tray's explicit "Quit Kira" can
end the event loop.

**If you add a new Qt window**, audit whether it should keep the loop
alive on its own — don't rely on the flag toggle as the only guard.

## Ollama warmup & keep_alive

Two related mechanisms keep first-press latency near zero:

- `StylerConfig.keep_alive` (default `"24h"`) is passed to every
  `ollama.chat()` call. Ollama's own default is 5 min, after which
  the model is unloaded and the next request pays the cold-start
  cost again.
- `StylerConfig.warmup_on_start` (default `True`) schedules
  `Styler.warmup()` on the asyncio loop at app boot — a 1-token chat
  that forces Ollama to load the model before the user's first F8.

Both are configurable via `config.yaml`; set `warmup_on_start: false`
on a low-VRAM box if you'd rather pay first-press latency than hold
the model resident.

## Restart workflow (editable install)

The Windows venv is an `uv`-created editable install — no `pip` is
available, but a `.pth` file in `site-packages` points at the WSL
source directory:

```
C:\Users\<user>\kira-venv\Lib\site-packages\_editable_impl_kira.pth
  -> \\wsl.localhost\Ubuntu\home\<user>\claude_kira
```

So source edits take effect on the **next process start** without any
reinstall. Restart sequence from WSL bash:

```bash
# Find the running Kira launcher PID. CommandLine-Filter statt Name-
# Filter, sonst trifft man auf Multi-Python-Boxen alle pythonw.exe-
# Prozesse — das CommandLine matcht nur kira-spezifische:
cd /tmp && powershell.exe -NoProfile -Command \
  "Get-CimInstance Win32_Process | Where-Object { \$_.CommandLine -like '*kira-venv*kira*' } \
   | Select-Object ProcessId,Name,@{n='MB';e={[math]::Round(\$_.WorkingSetSize/1MB,1)}}"

# Kill the launcher root with /T (children die with it):
cd /tmp && cmd.exe /c "taskkill /PID <kira.exe-PID> /T /F"

# Detached relaunch (cmd 'start' fails with 'Zugriff verweigert' from
# WSL bash — Start-Process works):
cd /tmp && powershell.exe -NoProfile -Command \
  "Start-Process -FilePath 'C:\\Users\\<user>\\kira-venv\\Scripts\\kira.exe' -WindowStyle Hidden"
```

Verify success by tailing `kira.log` for `Styler warmup complete` and
the first `heartbeat: uptime=60s` line.

## Audio device tolerance

`Recorder.__init__` doesn't resolve the configured `audio.input_device`
spec eagerly — it stores the spec and lets `prewarm()` resolve lazily.
If the device isn't currently enumerated (USB headset off, hardware
mute, audio service mid-disconnect), `_resolve_device()` returns `None`,
`prewarm()` becomes a no-op, and the app starts normally.

The first F8 press hits `start()`'s retry path: it resets the cached
`_input_device`, re-runs `prewarm()`, and if the device is *still*
absent raises `DeviceUnavailable`. `KiraApp.on_hotkey_press` catches
that and surfaces `State.ERROR` (yellow tray icon for 3 s,
auto-reset to IDLE).

Robust against three failure modes:
- Substring miss (`'ROG Theta'` not in any device name)
- `sd.query_devices()` itself throws (PortAudioError during USB hot-plug
  race) — caught, treated as "not available"
- `sd.InputStream(...)` throws between resolve and open (TOCTOU) —
  `_recording` flag stays `False` so the state machine doesn't hang

When debugging `Hotkey press but input device unavailable` warnings:
the same log line includes the list of currently-visible input devices,
so you can see whether the substring spec is wrong or the device is
genuinely off.

## Branded icon workflow

Two ICO files in `assets/`:

- `icon.ico` — source-of-truth, schwarzes Logo auf transparentem Hintergrund.
  Wird vom Tray-Runtime-Code als Logo-Quelle gelesen.
- `icon-branded.ico` — Build-Artefakt: gelbes Rounded-Square als Hintergrund
  + das Logo aus `icon.ico` zentriert. Wird in `kira.exe` / `kira-once.exe`
  embedded und in den Inno-Installer gebundelt.

Wenn das Source-Logo getauscht wird (`assets/icon.ico` durch eine andere
PNG/ICO ersetzen), in dieser Reihenfolge:

```powershell
# 1. Branded-Variante neu generieren (gelb-bg + logo, multi-size 16..256)
py -3.12 scripts\regenerate_branded_icon.py

# 2. EXE-Wrapper neu mit dem branded ICO embedden (stoppt Kira selbst)
powershell -ExecutionPolicy Bypass -File scripts\embed_icon.ps1

# 3. Kira manuell relaunch (s. Restart workflow oben)
```

Tray-Icon-Generation läuft zur Laufzeit aus `icon.ico` heraus mit
demselben Look. Modul-Level-Caches in `kira/ui/tray_win.py`
(`_LOGO_CACHE`, `_ICON_CACHE`) eliminieren UNC-IO nach dem ersten
Render — wichtig weil `assets/` auf dem WSL-Tree liegt und jedes
`Image.open()` sonst `\\wsl.localhost\…` mehrfach pro F8-Zyklus
trifft.

## Test policy

- Windows tests (`tests/test_*_win.py`) skip on non-Windows via
  `pytest.skip(..., allow_module_level=True)`.
- Mac tests (`tests/test_hotkey.py`, `tests/test_injector.py`, etc.)
  fail to *collect* in the Windows WSL venv because they import Mac-only
  modules at the top. Run the Windows test subset from WSL with:

  ```bash
  cd /tmp && cmd.exe /c 'pushd \\wsl.localhost\Ubuntu\home\<user>\claude_kira && C:\Users\<user>\kira-venv\Scripts\python.exe -m pytest tests/test_transcriber_fw.py tests/test_hotkey_win.py tests/test_injector_win.py tests/test_context_win.py tests/test_permissions_win.py tests/test_config.py tests/test_recorder.py tests/test_state_machine.py tests/test_tray_icon.py -v && popd'
  ```

## WSL shell quoting reminder

Windows Python from WSL bash needs **single quotes** and `pushd` for
UNC paths:

```bash
cd /tmp && cmd.exe /c 'pushd \\wsl.localhost\Ubuntu\home\<user>\claude_kira && C:\Users\<user>\kira-venv\Scripts\python.exe -m pytest <file> -v && popd'
```

`cd /tmp` first because bash's CWD is UNC and cmd.exe refuses it.
Double-quotes eat the backslashes — always use single quotes around the
`cmd /c` arg.

## uv on Windows

`uv` may not be on the Windows PATH after `winget install astral-sh.uv`.
Fallback that always works:

```
py -3.12 -m uv <subcommand>
```

The Windows venv was created with this fallback form.

## Build / Distribution

The Windows installer (`installer/kira.iss`, Inno Setup 6) bundles an
embedded Python 3.12, pinned wheels, the Whisper model files, the
Ollama setup, and a Gemma model — total ~13 GB compressed across one
2 MB stub + several `.bin` splits (Inno DiskSpanning).

Build orchestrator: `scripts/build_installer.ps1`. Pre-flights for
Inno Setup, WSL Ollama, and the local Whisper model. Output lands in
`%USERPROFILE%\OneDrive\Desktop\Kira\`.

GitHub release-asset limit is 2 GB per file vs. 8 split files —
distribute the bundle via OneDrive / direct share, not GitHub Releases,
until `kira.updater` learns manifest-based multi-asset pulls.

## License

Personal use. See `LICENSE` (EN + DE) and `installer/license.de.txt`
(installer-displayed copy).
