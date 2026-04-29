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
- Log: `%LOCALAPPDATA%\Kira\kira.log`
- Config: `%APPDATA%\Kira\config.yaml`
- Whisper model cache: `%USERPROFILE%\.cache\faster-whisper\` (or pinned
  to a local dir via `whisper.model: C:/Users/<user>/models/...`)

### macOS
- Source: project dir on local filesystem
- Venv: project-local `.venv/`
- Log: `~/Library/Logs/kira.log`
- Config: `~/.config/kira/config.yaml`

## Test policy

- Windows tests (`tests/test_*_win.py`) skip on non-Windows via
  `pytest.skip(..., allow_module_level=True)`.
- Mac tests (`tests/test_hotkey.py`, `tests/test_injector.py`, etc.)
  fail to *collect* in the Windows WSL venv because they import Mac-only
  modules at the top. Run the Windows test subset from WSL with:

  ```bash
  cd /tmp && cmd.exe /c 'pushd \\wsl.localhost\Ubuntu\home\<user>\claude_kira && C:\Users\<user>\kira-venv\Scripts\python.exe -m pytest tests/test_transcriber_fw.py tests/test_hotkey_win.py tests/test_injector_win.py tests/test_context_win.py tests/test_permissions_win.py tests/test_config.py -v && popd'
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
