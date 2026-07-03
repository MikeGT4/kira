# Kira — developer notes

Personal-use voice-to-text app. macOS menubar (`main` branch) + Windows 11
tray (`windows-port` branch). Hold a hotkey, speak, release — polished
text appears at the cursor.

**Version:** v0.3.3 (`windows-port`) — released 2026-07-03 (Latest auf
GitHub; Tag auf Build-Commit `fe23780` = GPU-Diagnose `6f89513` +
Toast-Längen-Fix `de015d1` + gemma4-Defaults; 4 Assets: Setup-exe +
2 bin-Splits + SHA256SUMS — lokale Artefakte nach Upload gelöscht,
GitHub ist die alleinige Ablage; build/_cache absichtlich behalten).
Neu-Installs polieren mit gemma4:12b (braucht Ollama ≥ 0.30, Installer
bundlet aktuelle Version), fast_model-Default gemma4:e4b (Probe 0/6
buggy auf Mike's Box). Mike's Box bleibt auf styler.model gemma3:12b +
Ollama-0.24.0-Pin (bewusst, ollama#16610 offen; gemma4:12b-Pull braucht
dort erst ein Ollama-Update — OllamaSetup-0.31.1.exe liegt in
Downloads). Vorher: v0.3.1 + v0.3.2 am selben Tag (2026-06-28)
released, v0.3.0 released 2026-06-12 (Tag `78e0f66`).

v0.3.3 entlarvt Fremd-Ollamas auf Port 11434 („Polish auf CPU trotz
26,5 GB freiem VRAM" nach Win-Start). **Root Cause war NICHT der
Windows-Ollama:** Der Docker-Container `mirofish-ollama` (anderes
Projekt, `0.0.0.0:11434->11434`, `restart: unless-stopped`) band beim
WSL2-Boot den Port vor der Ollama-Tray-App — auf der Win-Seite hält dann
`wslrelay.exe` den Port, die Tray-App spammt Bind-Errors, und Kira redete
wochenlang mit dem Container-Server (eigener Modell-Store, sieht das
HKCU-VRAM-Tuning aus v0.3.0 NIE; Details in „Ollama-Port-Besitz" unten).
Kira-seitig: neues `kira/ollama_diag.py` (Port-Inhaber via
`GetExtendedTcpTable`, klassifiziert win-ollama/wsl/docker/other, Toast
trägt die zum Inhaber passende Abhilfe), `verify_gpu_placement` erkennt
jetzt auch Partial-Offload (`size_vram < 0.95×size` → „partial", das
49/51-Split-Muster) + matcht untagged Modellnamen (`gemma3` ↔
`gemma3:latest`), und der Setup-Re-Probe holt einen gescheiterten
Boot-Warmup nach (`Styler.warmup_succeeded`). Dazu Review-Welle mit 6
verifizierten Findings gefixt: `context_modes`-YAML ersetzte statt zu
mergen (kritisch — ein Custom-Eintrag warf alle Built-in-Mappings weg),
`vad_threshold` war tote Config, `prewarm()` warf rohe PortAudio-Fehler
am DeviceUnavailable-Contract vorbei, Injector-Restore-Timer kollidierten
bei schnellen Diktaten (Generation-Guard), File-Transkription hatte einen
toten Abbrechen-Knopf + GC-gefährdeten QThread (Anker jetzt auf der
Tray-Instanz + Doppel-Start-Guard). 33 neue Tests, Suite 411 grün.
Voller Eintrag in `CHANGELOG.md`.

v0.3.2 fixt den Modell-Pull-Dialog-Hänger bei großen Modellen. `on_progress`
in `kira/ui/settings_dialog.py` rief `progress.setMaximum(int(total))` mit
`total` in Bytes — `QProgressDialog` nimmt aber C int32 (max ~2.1 GiB); ein
17.4-GB-Blob (unzensiertes Qwen3.6-27B) warf `OverflowError` bei JEDEM
Stream-Tick (Endlos-Animation + in einem Log 12651 Einträge = Mike's
„Endlosschleife beim Updaten"). Der v0.2.8-qint64-Fix korrigierte nur das
`_PullWorker`-**Signal**, nicht den `setMaximum`-Call — die andere Hälfte
desselben Bugs. Fix: neue Helper `_progress_scale` mappt Bytes auf eine feste
0..1000-Promille-Skala (immer int32-sicher); echte MB/% kommen weiter aus den
rohen Byte-Werten. 3 neue Tests. Voller Eintrag in `CHANGELOG.md`.

v0.3.1 released 2026-06-28 (`windows-port`). Anlass: „Kira versteht manchmal
Müll". Log-Forensik (~6500 Aufnahmen) entlastet das Polish-LLM (86 %
`Whisper out`==`Polish out`, 0 % starke Kürzung) — der Müll entsteht schon
bei Whisper. Der 16.06.-Clipping-Fix (`input_gain` 2.0→1.0) beseitigte das
Clipping (35 %→0 % hart geclippt, über kira.log verifiziert), halbierte aber
das Nutzsignal (`rms` 0.120→0.059, unter Whispers Komfortzone). Fix:
PTT-`transcribe()` nutzt `beam_size=5` statt 1 (breitere Decoder-Suche fängt
undeutlich gesprochene Wörter besser ab, auf der 5090 latenzneutral;
`transcribe_file()` hatte 5 schon). Plus Log-Rotation: `kira.log` auf 30 MB
gedeckelt (`RotatingFileHandler`, 15 MB × 1 Backup) + `encoding="utf-8"`
(vorher cp1252-Mojibake bei Umlauten). 3 neue Tests in `tests/test_main.py`.
**Wurzel-Lösung fürs zu leise Signal ist Hardware-seitig (Shure-Gain in der
MOTIV-App) und steht noch aus** — s. `~/.claude/reminders/shure-mic-kalibrierung.md`
und Abschnitt „Audio gain & clipping". Vorher: v0.2.8 released 2026-05-28.

v0.3.0 bringt das Polish-Modell zuverlässig auf die GPU. Persistentes
VRAM-Tuning (`kira/ollama_env.py`) setzt beim Start
`OLLAMA_FLASH_ATTENTION=1` + `OLLAMA_KV_CACHE_TYPE=q8_0` in
`HKCU\Environment` — der q8-KV-Cache halbiert den KV-Speicher, das senkt
den realen VRAM-Bedarf, statt die Platzierung mit `num_gpu=999` zu
erzwingen (ab Ollama 0.30.x wirkungslos, GitHub #16610). Auf einer
32-GB-Karte landet damit auch das große unzensierte Qwen3.6-27B neben
Whisper komplett im VRAM. Das sind Server-Env-Vars (nicht per-request) →
greifen nach Ollama-Neustart; Kira startet den geteilten Server bewusst
nicht selbst neu. Dazu deterministische CPU-Fallback-Detection
(`styler.verify_gpu_placement` via `ollama.ps()` → `size_vram`), die bei
CPU-Load einen actionablen Tray-Toast feuert. 12 + 11 neue Tests. Voller
Eintrag in `CHANGELOG.md`.

v0.2.8 fixt den Modell-Pull-Dialog im Settings (unzensiertes Polish-
Modell „Trotzdem laden"). Drei zusammenhängende Bugs, alle in
`kira/ui/settings_dialog.py`:

1. **Minusprozente:** `_PullWorker.progress = pyqtSignal(str, int, int)`
   marshalled C int (32-bit signed). Das unzensierte Qwen3.6-27B
   hat einen 17.4-GB-Blob — sobald `completed` zwischen 2 und 4 GiB
   lag, wrappte der Wert negativ. `_update_runner` zeigt das gleiche
   Pattern, dort fällt's nie auf weil Inno's DiskSlice exakt INT32_MAX
   ist und kein einzelnes Bundle-File die Grenze sprengt. Fix:
   `pyqtSignal(str, 'qint64', 'qint64')`.
2. **Toter Abbrechen-Knopf:** `_PullWorker` hatte keine `cancel()`-
   Methode und `progress.canceled` war nie an irgendwas verbunden.
   Fix: `_cancelled`-Flag + `cancel()`-Method + `progress.canceled.connect(worker.cancel)`,
   Loop-Check beim nächsten yield.
3. **Programm-Hänger beim Settings-Close während Pull:** `closeEvent`
   rief `thread.terminate()` nach 3 s — Qt-Doku markiert das explizit
   als unsafe (kann Mutexe halten / Heap kaputtmachen). Fix: kein
   terminate mehr, stattdessen Worker cancel-flaggen, UI-Signals
   trennen, und falls der Worker noch im `ollama.pull()`-Socket
   hängt: in Modul-Level `_orphan_pull_threads` parken.

Bonus-Fix: `_pull_blocking` (auf Line 880 vom `_save`-Pfad gerufen)
war nirgends definiert — AttributeError beim Aktivieren von „Schneller
Modus" wenn `fast_model` fehlte. Jetzt als QEventLoop-Wrapper über
`_start_model_pull(..., on_done=...)`. 8 neue `_PullWorker`-Tests
in `tests/test_settings_dialog.py`. Voller Eintrag in `CHANGELOG.md`.

v0.2.7 released 2026-05-23 (`windows-port`). Polish-Latenz-Fix
(`num_gpu=999`); Doku in CHANGELOG.

v0.2.6 baut eine Selbst-Detection für den in v0.2.5 dokumentierten
Polish-CPU-Fallback ein. Wenn drei `polish()`-Calls in Folge > 3 s
brauchen (`SLOW_POLISH_THRESHOLD_SEC`, `SLOW_POLISH_TRIGGER_COUNT`
in `kira/styler.py`), feuert der Styler einen Tray-Toast und
switcht für 5 Min (`FORCE_FAST_DURATION_SEC`) temporär auf
`styler.fast_model` (Default `gemma3:4b`). Per-Mode-Overrides
behalten Vorrang, manueller `fast_mode=True` überspringt den Switch
aber feuert trotzdem den Toast. Wiring: `Styler.__init__` nimmt
optional einen `on_slow_polish_detected`-Callback, `set_on_slow_polish_detected()`
ist die Late-Binding-Setter-Methode (Styler wird in `run()` vor dem
Tray erzeugt). `KiraTray.notify(title, msg)` in `kira/ui/tray_win.py`
ruft `pystray.Icon.notify` und schluckt Exceptions, damit ein
kaputtes Notification-Subsystem den Polish-Pfad nicht umhaut. 11
neue Tests in `tests/test_styler.py`.

**HwSchMode-Verlust-Pattern (Anlass für v0.2.6):** Mike's
2026-05-22-Fix `HwSchMode=1` (HAGS aus) ist nach der v0.2.5-
Installation am 2026-05-23 wieder verschwunden — der Reg-Wert
existierte nicht mehr in `HKLM\SYSTEM\CurrentControlSet\Control\GraphicsDrivers`,
HAGS war wieder default = on. Wahrscheinliche Ursache:
Treiber/Windows-Update überschreibt den Wert. Konsequenz: GPU-
Discovery-Race-Bug schlug wieder zu, gemma3:12b landete auf
CPU. Diagnose-Befund klar: `ollama ps` zeigte 100% CPU, Server-Log
zeigte `available="9.9 GiB"` beim Boot um 11:15 (zu wenig für
11 GB Modell), Polish-Roundtrip 10–15 s. `ollama stop` + Reload
hat NICHT geholfen, das Modell blieb auch mit 19 GB freiem VRAM
auf CPU — das ist nicht „knapper VRAM beim Boot", das ist ein
tieferes 0.24.0-Verhalten, das Mike manuell mit HwSchMode-Reset
+ Reboot fixen muss. v0.2.6 mitigiert für den User: Kira merkt
selbst und switcht.

v0.2.5 released 2026-05-22 (`windows-port`).
v0.2.5 behebt den seit v0.2.3 kaputten Einstellungen-Dialog:
Kern-Ursache war ein `QScrollArea` um die Section-Cards, der unter
Qt 6.11 die Theme-Vererbung bricht (Cards dunkel, `QLabel`-Text
unsichtbar) — entfernt. Dazu 2-Spalten-Layout (Dialog ~770 statt
~1270 px hoch), sichtbares `QCheckBox::indicator`-Kästchen im
`_dialog_style`-QSS und Qwen-3-Thinking-Mode-Support im Styler
(`_thinking_kwargs()` → `think=False` nur für `qwen3*`). Details:
`CHANGELOG.md`.

**Polish-Latenz (echte Root Cause 2026-05-23, Fix in Code):**
Lange als „GPU-Discovery-Race" + „HwSchMode" diagnostiziert
(s. Verlauf weiter unten); **echte Root Cause war Ollama's Auto-Layer-
Allocator**, der bei `gemma3:12b` (Q4_K_M, 12 GB) auf der RTX 5090 mit
28 GiB freiem VRAM gelegentlich entschied, ~787 MiB Weights (Embedding-
Tensor) auf CPU zu lassen. `ollama ps` zeigte dann `49%/51% CPU/GPU`
statt `100% GPU`. Folge: jeder Token-Generate griff via PCIe zum
CPU-Speicher → **14 tok/s statt 114 tok/s** = 8× Slowdown. Auto-
Allocator-Entscheidung ist nicht-deterministisch — Reboot würfelte
neu, manchmal traf er es richtig (= „früher war's schnell"), oft nicht.

**Fix (commit, styler.py):** `num_gpu=999` als Option in ALLE drei
`ollama.chat()`-Calls (`warmup`, `polish`, `edit_command`). Forciert
Ollama, alle Layer auf GPU zu legen. Konstante `FORCE_ALL_LAYERS_ON_GPU
= 999` oben im Modul. Muss konsistent überall stehen, sonst reloadet
Ollama das Modell bei jedem Options-Wechsel (~7 s pro Reload). Sicher
für alle Default-Polish-Modelle (≤16 GB) auf 32-GB-Karten; für User
mit größeren Modellen / kleineren GPUs würde ein OOM-Fail statt
graceful CPU-Fallback resultieren. Verifiziert 2026-05-23: identischer
Direct-Call mit num_gpu=999 → 100% GPU, Polish-Roundtrip <1 s wieder
Standard. Tests: `tests/test_styler.py::test_*_forces_num_gpu_999`.

**Frühere Diagnose (überholt):** HAGS aus (`HwSchMode=1`), Windows-
Defender-Ausnahmen für Ollama-Binaries und `CUDA_VISIBLE_DEVICES=0`
bleiben sinnvoll als Hygiene, sind aber NICHT der eigentliche Fix.
Reboots, die das Problem „lösten", haben es nicht behoben — sie haben
nur die Auto-Allocator-Entscheidung neu gewürfelt. Mit dem Code-Fix
ist Reboot-Würfeln raus. Polish-Modell bleibt `gemma3:12b` (Mike's
`config.yaml`).
v0.2.3 released 2026-05-21 (F9-AI-Editing als Settings-
Toggle, idna 3.15 (CVE-2026-45409), Prompt-Härtung clean.md/
email_formal.md, automatischer Update-Check beim Start
(`updates.check_on_start`, `kira/_update_marker.py`), optionales
unzensiertes Polish-LLM (abliteriertes Qwen3.6 27B, 🔞-gekennzeichnet),
neuer dunkler Splash, Settings-Dialog Single-Instance-Guard gegen
Doppel-Fenster beim Tray-Klick. **GPU-Check-Fix:** `detect_gpu`s
`nvidia-smi`-Aufruf lief in Kiras pythonw-Prozess unter GPU-Last
(aktive CUDA-Kontexte von Whisper + Ollama) regelmäßig in
`TimeoutExpired` — `timeout=5.0` war zu knapp, der Check meldete
fälschlich `no_gpu`. Fix: 30 s Timeout + `stdin=DEVNULL` + Per-
Kandidat-Logging; `_run_gpu_check` läuft jetzt auf einem QThread mit
animiertem Scan-Dialog (`kira/ui/_gpu_scan_dialog.py`, Neon-Welle im
HUD-Oszilloskop-Stil). 327 Tests gruen). v0.2.2 released 2026-05-17
(Schneller Polish-Modus als
Settings-Toggle. `StylerConfig.fast_mode: bool` + `fast_model: str`
(Default `gemma3:4b`); `Styler._resolve_model()`-Helper zentralisiert
Modell-Hierarchie Per-Mode > fast_mode > Default. Toggle in der
Polish-LLM-Section-Card; bei Neu-Aktivierung `_pull_blocking()` mit
QEventLoop falls Modell fehlt. Hintergrund: gemma3:12b rutschte bei
vollem Desktop (Chrome + Outlook + RDP + EdgeWebView) in 49/51 CPU/
GPU-Split → Polish 2–4 s; 4b passt 100 % GPU → 0,3–0,5 s. 7 neue
Tests, 33 styler/config-Tests gruen). v0.2.1 released 2026-05-12
(HUD-Pixel-Oszilloskop in digitalroots-Neon-Grün — gelbe Bars ersetzt
durch 2-px Polyline auf Roh-Sample-Peaks, no-AA für pixel-scharfen
Look. Recorder-API um `set_samples_callback` erweitert, Mac-Pfad
unangetastet). v0.2.0 released 2026-05-11 (Tag auf commit `a69e776`,
Bundle-Source `a8c7dd2`, `windows-port`). v0.1.0 ist die vorige Release. v0.2 fuegt:
Custom Dictionary (`whisper.replacements`), AI-Modes (per-Mode Override),
F9 AI-Editing-Commands mit Silent-Failure-Haertung, File-Transcription,
Multi-Asset In-App-Updater (SHA256-Verify + Resume + Path-Traversal-
Schutz), GPU-Check-Button, async-Whisper-Pipeline, Anleitung-Dialog
mit Apple-Look, version-aware Welcome-Marker, Settings-Dialog Win11-
Section-Cards mit "Ueber Kira"-Card (Anleitung + GPU + Updates),
config_writer mit auto-append fuer fehlende Sections/Keys, **WSL-
Decoupling** (Source auf NTFS unter `C:\Users\<user>\dev\kira`, Ollama
nativ statt WSL-systemd), **Slim-Installer mit First-Run-Wizard**
(`kira/setup_wizard.py`, 3 Worker-Threads pullen Whisper + Ollama +
Gemma parallel), **wheel-aware Asset-Pfade** (`kira/_resources.py`).
Siehe `CHANGELOG.md`. ~135 Tests gruen.

**Review-Welle 2026-05-09:** 4 Subagenten (code-reviewer, security-
auditor, silent-failure-hunter, best-practice-checker) parallel
dispatched. Findings (commit `30dd02c`): F9-Path-Silent-Failure-
Cluster, async-Blocking transcribe, updater-Resume, asset-name-
Whitelist, prompt-injection-Schutz, GPU-PATH-Hijack, QThread-
Cleanup, notepad-Launch-Hardening. Volles Findings-Detail in
[`~/.claude/projects/-home-mikepollow-claude-kira/memory/best_practice_audit_v02.md`](../.claude/projects/-home-mikepollow-claude-kira/memory/best_practice_audit_v02.md).

**Bundle-Welle Phase F2 2026-05-10:** 23 Sub-Phasen. Schluessel-Fix
F2-23 (`a8c7dd2`): rcedit-x64 `[Run]`-Steps in `installer/kira.iss`
deaktiviert. Pip/distlib gui_scripts-Wrapper (kira.exe, kira-once.exe)
sind PE-Loader + appended ZIP — rcedit's PE-Section-Rewrite trimmt
diesen ZIP-Stream, der Wrapper crasht silent mit Exit -1 (kein log,
kein stderr, keine MsgBox). Trade-off: kira.exe-EXEs zeigen jetzt
das pip-default Python-Logo im Datei-Explorer, alle anderen
Branding-Surfaces (Tray, Lnks, Setup-Wizard) bleiben gelb. Bundle
verifiziert auf Mike's Box `C:\Users\mike\AppData\Local\Kira\`,
Boot 7 s inkl. Tray + F8/F9 + Whisper-CUDA + Polish-Warmup.
Volle Phasen-Liste in [`TODO.md`](TODO.md).

**Prompt-Härtung für 4B-Modelle 2026-05-17:** Beim Build von v0.2.2
(fast_mode-Toggle) gemma3:4b gegen `prompts/terminal.md` live-getestet.
Mike's PBX-Konversationen ("Heißt das, wir schauen zuerst mal, ob die
880 irgendwo vergeben ist…", "Hallo?", "Okay, ich meine, wenn nichts
Destruktives dabei ist…") wurden ALLE zu `git status` polished. Whisper
korrekt, aber Polish gibt 10 chars `"git status"` aus statt 100+ chars
Input. Pipeline unbrauchbar. Symptom in `kira.log`: jede `Polish out
(mode=terminal, 10 chars): 'git status'`-Zeile direkt nach einer
viel längeren Whisper-out-Zeile (siehe Commit `4daf74c` → `65e6cfc`).

**Root Cause:** Der Original-`prompts/terminal.md` hatte das einzige
konkrete Beispiel inline in der Regel-Liste:
`Korrigiere NUR offensichtliche Transkriptionsfehler ("get status" -> "git status")`.
12B parst das als reine Illustration. 4B (Few-Shot-Schwäche) fixiert
sich darauf und gibt für ALLE Inputs `git status` zurück. Selbes
Pattern erwartbar mit anderen kleinen Modellen (Q4-quantisierte
3B–7B-Klasse).

**Fix-Pattern für alle prompts/*.md die mit 4B/Speed-Modus laufen
sollen:** Beispiele NIE inline in einer Regel-Bullet, sondern in einem
separaten Block mit explizitem Disclaimer ("NICHT als Output-Vorlage
verwenden — nur als Illustration"). Plus mehrere Beispiele die
verschiedene Output-Typen abdecken (Konversation + Shell-Befehl
gemischt für `terminal.md`), damit das Modell keinen einzelnen
Anker hat. Plus explizite negative Output-Regel am Ende ("kein
Kommentar, keine Erklärung, kein Beispiel").

**Verifikation:** `scripts/probes/probe_terminal_prompt.py` läuft 6
realistische Inputs durch gemma3:4b mit dem aktuellen `prompts/
terminal.md` und floort Output != `"git status"` bei nicht-Befehl-
Inputs. Nach Härten 0/6 buggy. Bei Änderungen an `terminal.md` oder
neuen Mode-Prompts mit Inline-Beispielen erneut laufen.

**Mic-Pinning bei Cold-Boot 2026-05-11:** Mike hat heute einen Shure
MV7+ als neues USB-Mikro bekommen. Beim Autostart nach Reboot lieferte
das Mic stille Samples (peak=0.0002, rms=0.0001), Whisper halluzinierte
"Vielen Dank.", Hallucination-Filter killte die Pipeline → kein Text.
Manueller Kira-Restart nach ~90 s funktionierte. Root-Cause: USB-Mics
enumerieren beim Cold-Boot später als die internen Devices, der
Windows-Default zeigt transient auf die `AI Noise-Canceling Microphone
(Intelligo VAC / ASUS Utility)`, deren Filter Mike's Speech als Noise
killt. Selbe Falle wie 2026-04-28. Fix: `audio.input_device` per
Substring auf den physischen Mic-Namen pinnen (`Shure MV7+` o.ä.).
Wenn der USB-Mic beim Cold-Boot-Press noch nicht enumeriert ist,
wirft Recorder `DeviceUnavailable` → gelbes Tray-Icon 3 s (klares
Symptom statt stiller Aufnahme), 5-10 s warten + nochmal Fn löst's.
Beispiele im README-Config-Abschnitt + `installer/config.yaml.template`.

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
  `kira/ui/_dialog_style.py` (Win — PyQt6 light-theme helper),
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
- Source: NTFS `C:\Users\<user>\dev\kira` (= `/mnt/c/Users/<user>/dev/kira`
  aus WSL; seit dem WSL-Decoupling v0.2.0. Der alte WSL-Tree
  `/home/<user>/claude_kira/` existiert als Zweit-Checkout, ist aber NICHT
  mehr das editable-Install-Ziel — Edits dort erreichen die laufende
  Dev-Instanz nicht.)
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

## Dialog light theme

Win11's dark mode propagates into PyQt6 as a system-wide dark palette,
which broke two things: the digital-roots logo (black artwork on a
transparent canvas) became invisible against the dark dialog
background, and Win11's Fluent button style rendered the buttons as
transparent rectangles whose text was white-on-light once we forced
the BG light. `kira/ui/_dialog_style.py` centralises the override:

- `apply_light_theme(dialog)` sets a light `QPalette` AND a QSS
  stylesheet covering `QLabel`, `QCheckBox`, `QPushButton`, `QLineEdit`,
  `QSpinBox`, `QDoubleSpinBox`, `QComboBox`. Both are needed: palette
  alone is ignored by Fluent for several widgets; QSS alone breaks the
  parts the palette did handle. Settings/Welcome/SetupHint/About all
  call `apply_light_theme(self)` immediately after `super().__init__()`.
- `light_information / light_warning / light_critical` replace the
  static `QMessageBox.information/.warning/.critical`. Those statics
  spawn an unparented box that re-inherits Win11's dark palette, so
  the body text rendered invisible-on-dark right after `Speichern`.
- `QProgressDialog` is a `QDialog` subclass, so `apply_light_theme(progress)`
  works on it too — done for the Polish-Modell update pull.

Branded header (yellow 煌 glyph left, title centre, digitalroots
right) lives in parallel in `settings_dialog._build_header()` and
`about_dialog._build_header()`. Pillow loads the largest frame from
`assets/icon-branded.ico` and downscales once with LANCZOS —
`QPixmap`'s native ICO loader otherwise picks an arbitrary (often
16 px) frame and upscales, producing a blurry header glyph.

The pre-Qt single-instance `MessageBoxW` in `kira/main.py` is
intentionally NOT routed through `_dialog_style` — it fires before any
QApplication exists, so we have nothing to render through.

## Boot sequence + parallel warmup

`_run_windows()` in `kira/main.py` is structured so the tray + hotkey
come up in <1 s, then the slow checks race in the background:

1. Splash + first-run welcome (local-only, fast)
2. KiraTray construction + asyncio loop thread
3. **Background warmups in parallel:**
   - `styler.warmup()` on the asyncio loop (1-token Ollama chat,
     forces gemma3:12b into VRAM, ~7 s)
   - `transcriber.warmup()` on a daemon thread (CTranslate2 +
     cuBLAS + cuDNN load, float16 weights to VRAM, ~5 s)
4. `hotkey.start()` + `tray.run_detached()` — F8 is now armed
5. `splash.close()` and the Qt event loop starts
6. **WSL2 warm-up kick** (`kira/_wsl_warmup.py::kick_wsl_distro`) —
   non-blocking `wsl.exe --exec /bin/true`. Forces the WSL2 VM to boot
   in parallel with the rest of Kira's init so backend services
   (e.g. systemd-managed `ollama.service` on Mike's box) come up in
   time for the setup probe. No-op on boxes without WSL installed
   (FileNotFoundError swallowed).
7. **Background setup probe** (mic permission + Ollama reachability +
   model presence) on its own daemon thread.
   - **Mic missing** → SetupHintDialog marshalled onto the Qt main
     thread via `MainThreadMarshal.run_on_main_thread`.
   - **Ollama missing (mic OK)** → no dialog. Polish falls back to
     raw Whisper text on errors anyway, and re-firing the dialog at
     every cold boot only nags. Instead, the daemon keeps probing
     every 30 s for 10 min so `ensure_ollama_model` runs once the
     backend finishes booting.
   - **Both missing** → SetupHintDialog (mic forces user action, so
     surface both items at once).

Old flow before 2026-05-04 ran step 7 synchronously (modal block on
the main thread BEFORE step 4). On a cold WSL2 boot
`_ollama_reachable()` needed up to 90 s of retries — splash froze
("Reagiert nicht" in Win11), tray + hotkey didn't appear, and Mike
killed the process thinking it was stuck. Symptom in `kira.log`:
`Starting Kira` then `Recorder pinned`, then a 60 s `heartbeat` with
no `HotkeyListener running` in between. The fix was purely sequencing —
move the probe to the background. `_ollama_reachable` itself keeps
the long retry budget for the rare case where Ollama is slower than
the WSL kick can pre-empt.

The follow-up on 2026-05-06 added the `kick_wsl_distro()` step + the
mic-only dialog policy: WSL2 doesn't auto-start at Win-login, so
Kira's autostart raced WSL2 cold-boot every reboot — the 90 s probe
budget timed out and the SetupHintDialog fired every morning even
though Ollama was about to come up minutes later (visible in
`kira.log` as `Setup hint: mic_ok=True ollama_ok=False` followed by
a successful `HTTP 200 OK` on the user's first F8 ~30 min later).
Pre-pinging WSL closes the race for the warm path; the dialog
suppression is defense-in-depth for the rare case where the kick
doesn't help (genuinely-broken Ollama, the user reads the
forensic log line anyway).

**Whisper had no warmup before this change.**
`Transcriber._ensure_model()` loads lazily inside the asyncio loop's
first `transcribe()` call — visible in `kira.log` as a multi-second
gap between `Loading faster-whisper model` and `Processing audio`.
Without `warmup()` running at boot, every first F8 after launch ate
that ~5 s. CUDA contexts in CTranslate2 are managed internally (not
bound to the calling thread), so loading on a daemon thread and
reusing from the asyncio loop is safe.

### Ollama keep_alive

`StylerConfig.keep_alive` (default `"24h"`) is passed to every
`ollama.chat()` call. Ollama's own default is 5 min, after which
the model is unloaded and the next request pays cold-start again.
Combined with `Styler.warmup()` this keeps gemma3:12b resident from
boot to quit.

`StylerConfig.warmup_on_start` (default `True`) gates the boot-time
warmup. Set to `false` in `config.yaml` on a low-VRAM box if you'd
rather pay first-press latency than hold the model resident.

## Ollama-Port-Besitz (11434) — Fremd-Server-Falle

Kiras gesamte Ollama-Heilung (HKCU-VRAM-Tuning v0.3.0, „Ollama neu
starten"-Toasts) setzt voraus, dass auf `127.0.0.1:11434` der
**Windows-native** Ollama antwortet. Der Port ist aber
first-come-first-served, und auf Mike's Box konkurrieren drei Kandidaten:

1. **Windows-Ollama-Tray-App** (Startup-Ordner `Ollama.lnk`) — der
   gewollte Server. Verliert er das Bind-Race, spammt sein
   `%LOCALAPPDATA%\Ollama\server.log` endlos `bind: Only one usage of
   each socket address` — dieses Log ist dann NICHT das Log des
   antwortenden Servers.
2. **WSL-systemd `ollama.service`** — seit dem D:-Umzug disabled/tot
   (verifiziert 2026-07-03), aber als Muster dokumentiert.
3. **Docker-Container mit `0.0.0.0:11434`-Mapping** — der Täter vom
   2026-07-03: `mirofish-ollama` (`ollama/ollama:latest`,
   `restart: unless-stopped` im Compose von
   `~/claude_mirofish/code/mirofish-offline/`) startet mit jedem
   WSL-Boot. Auf der Win-Seite hält dann `wslrelay.exe` den Port.
   Der Container-Server hat einen EIGENEN Modell-Store
   (`/root/.ollama`, 31 GB Duplikate!), sieht HKCU-Env-Vars nie, und
   lief nach frühem Boot ohne CUDA (Race in der VM) → Polish komplett
   auf CPU trotz 26,5 GB freiem VRAM.

**Diagnose-Reihenfolge** (alles ohne Interop möglich):
`curl -s localhost:11434/api/version` + `/api/ps` (size vs `size_vram`),
dann `netstat -ano | findstr :11434` → PID → Prozessname. `wslrelay.exe`
als Inhaber = der echte Server läuft in der WSL-VM (systemd ODER
Docker; `docker ps` in WSL checken). Seit v0.3.3 macht
`kira/ollama_diag.py` genau das automatisch beim CPU-/Partial-Fallback
und der Tray-Toast nennt die passende Abhilfe.

**Wurzel-Abhilfe:** kein zweiter Ollama auf `0.0.0.0:11434`. Das
Mirofish-Compose mappt seit 2026-07-03 auf `127.0.0.1:11435:11434`
(Mirofish-intern läuft alles über Compose-DNS `ollama:11434`, das
Host-Mapping ist nur Debug-Zugriff). Kiras `kick_wsl_distro()` bleibt —
er ist für WSL-Ollama-Setups da — aber er weckt eben auch Docker-
Autostarts; das ist dokumentierte Kehrseite, kein Bug.

## Ollama-Versions-Pin 0.24.0 (Mike's Box) — Historie + Update-Kriterien

**Warum der Pin existiert:** In der Woche vom 2026-06-09 lief der
Win-Ollama (Auto-Update) auf **0.30.6** und Polish brach ein — Ursache
war die Regression [ollama#16610](https://github.com/ollama/ollama/issues/16610):
Der Server evicted das Modell trotz `keep_alive` zwischen Requests und
laedt es jedes Mal neu; jeder Polish zahlte ~1 min Load statt <1 s
(„es ging nichts mehr"). Downgrade auf **0.24.0** am 2026-06-09 hat es
behoben; Kira v0.3.0 bekam deshalb die GPU-/Placement-Detection.
(Nicht verwechseln mit den zwei ANDEREN Ollama-Probleme-Klassen:
Auto-Layer-Split 2026-05-23 → num_gpu=999, und Fremd-Server auf Port
11434 2026-07-03 → ollama_diag.)

**Stand 2026-07-03:** #16610 ist OFFEN, kein Fix im Changelog bis
v0.31.1. Bestaetigte Betroffene: Shared-Memory-Systeme (GB10, Jetson
Thor) mit grossen BF16-MoE-Modellen und wechselnden GGUF-Hashes —
NICHT das Profil der 5090 (ein residentes Q4-Modell, keep_alive 24h).

**Update-Abwaegung:** `gemma4:12b` braucht Ollama ≥ 0.30 (Registry-412
auf 0.24.0). Wer updatet: `OllamaSetup-0.31.1.exe` liegt in Mike's
Downloads. Danach 1 Tag beobachten — die v0.3.3-Detection macht eine
zurueckkehrende Eviction sofort sichtbar (Slow-Polish-Toast nach 3
langsamen Polishes in Folge + `verify_gpu_placement`-Log beim Boot;
Gegencheck `ollama ps` nach 10 min Idle: Modell muss noch geladen
sein). Rollback = alten Installer von
https://github.com/ollama/ollama/releases/tag/v0.24.0 erneut
installieren. Ohne gemma4-Bedarf: Pin behalten — never touch a
running system.

## Restart workflow (editable install)

The Windows venv is an `uv`-created editable install — no `pip` is
available, but a `.pth` file in `site-packages` points at the source
directory (seit dem WSL-Decoupling der NTFS-Tree, verifiziert
2026-07-03):

```
C:\Users\<user>\kira-venv\Lib\site-packages\__editable__*.pth
  -> C:\Users\<user>\dev\kira
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

### Hot-unplug recovery (mid-stream USB disconnect)

The above handles "device absent at boot/start." A separate failure
class is "stream was open, then the user pulls the USB cable":
`prewarm()` ran successfully, `self._stream` is non-None, but the
underlying PortAudio handle is now bound to a vanished device. The
next sounddevice callback either reports `status.input_underflow` (the
soft-fail mode) or the C audio thread dereferences a dead handle and
the process disappears with no Python trace and no faulthandler entry
(the hard-fail mode that ate the 17:48 session on 2026-05-01).

Mitigations live in `kira/recorder.py`:

- `_callback` upgrades a non-empty `status` from DEBUG to WARNING so
  `kira.log` actually records the underflow signal. On
  `status.input_underflow` it sets `self._stream_dirty = True`.
  `input_overflow` is logged but does NOT flag dirty — it fires
  spuriously right after stream-open while PortAudio sizes its
  buffers, and cycling on every overflow would discard the pre-roll
  on each F8.
- `_is_device_still_present()` re-runs `sd.query_devices()` and checks
  whether the pinned `_input_device` index still resolves to a device
  with `max_input_channels > 0`. ASIO/MME re-enumerate in-place
  occasionally without freeing the slot, so the channel count is the
  authoritative signal, not just the index existing.
- `_cycle_stream_if_unhealthy()` runs at the top of `start()`. If the
  stream is dirty, inactive, or the device is gone, it `close()`s the
  stale stream and resets `_input_device = None`. The rest of `start()`
  then falls through to the existing re-resolve / DeviceUnavailable
  path. With `_device_spec is None` (system default, no pinning),
  `_is_device_still_present()` short-circuits to True — there's nothing
  to re-resolve and the stream is healthy as long as it's active.

If a user reports "Kira stirbt still nach Mikro abziehen": the new
WARNING line `sounddevice callback status: input underflow` should
appear in `kira.log` shortly before any unhealthy behaviour. Followed
by `Cycling input stream (dirty=True ...)` on the next F8 press if the
flag-based path triggered before a native crash could.

## Audio gain & clipping

Der Recorder multipliziert Rohsamples mit `audio.input_gain` und clippt
hart auf ±1.0 (`kira/recorder.py:187`, `np.clip(indata * gain, -1.0, 1.0)`).
Der Block ist in `if self._input_gain != 1.0:` gekapselt — bei exakt `1.0`
wird weder multipliziert noch geclippt, das Rohsignal geht 1:1 durch.

**Clipping ist der wahrscheinlichste Grund für „Kira versteht Mist".**
Diagnose-Schnitt: `kira.log` loggt pro Aufnahme `Whisper out` UND
`Polish out`. Sind beide (fast) identisch, ist das Polish-LLM unschuldig
und der Fehler steckt schon im Whisper-Output → also im Audio. Dann auf
die `Recorder.stop`-Zeile schauen: **`peak` verrät Übersteuerung, `rms`
nicht.** Der rms-Mittelwert kann in der „Target-Zone" (~0.12) liegen,
während die lauten Transienten (Satzanfänge, Plosive) bei `peak=1.0000`
hart clippen. Geclipptes Audio = abgeschnittene Wellenform = harmonische
Verzerrung → Whisper halluziniert phonetisch (z. B. „temporärer Chat" →
„Turbentempo-Rere-Chat").

**Befund 2026-06-16:** Mit `input_gain: 2.0` waren **33 % aller Aufnahmen
hart geclippt** (`peak=1.0000` über 4900 Log-Einträge), weitere 8 % fast.
Root Cause: gain=2.0 wurde am 28.04. fürs damalige Mic kalibriert; der
**Shure MV7+ (seit 11.05.)** liefert einen heißeren Pegel und wurde nie
nachgezogen — der config-Kommentar „expected peak ~0.4" gilt für den
Shure nicht. Gegenmaßnahme: `input_gain` auf `1.0` gesenkt (Software-
Clipping damit ganz aus dem Pfad). **Verifiziert 2026-06-28** über
kira.log: mit gain=1.0 sind **0 % der Aufnahmen hart geclippt** (vorher
35 %, avg_peak 0.44). ABER der Software-gain ist ein Nullsummen-Hebel —
gain=1.0 halbierte auch das Nutzsignal (`avg_rms` 0.120→0.059, unter
Whispers Komfortzone), wodurch undeutlich gesprochene Wörter falsch erkannt
werden („nuschele"→„nur schließe" bei sauberem, NICHT geclipptem
`peak=0.36`). v0.3.1 mildert per `beam_size=5` (breitere Decoder-Suche).
**Kalibriert 2026-06-28 (Weg A, Software-gain, keine MOTIV-App):**
`input_gain` auf **1.8** — bei Mike's STANDARD-Sprechabstand trifft das die
Zielzone (gemessen: `peak 0.62`, `rms 0.099`). Trade-off: Mike's Rohpegel
schwankt ~2× mit dem Abstand, ganz nah ans Mikro clippt auch bei 1.8
(`peak 1.0`) — es gibt mathematisch keinen festen gain, der beides kann
(1.4 = nie Clipping aber rms 0.08 zu leise; 1.8 = rms gut aber Nah-Rangehen
clippt). Konsequenz: beim Diktieren KONSISTENTEN Abstand halten. Wert auch
im Repo-Template (`installer/config.yaml.template`) für künftige Installs.
**Weg B als Fallback** (falls der Abstand nicht haltbar ist): ShurePlus-
MOTIV-App + Compressor gleicht die Abstands-Schwankung automatisch aus.

Kleinere Hebel, falls die Genauigkeit danach noch nicht reicht:
`whisper.replacements` ist leer (Map für wiederkehrende Eigenbegriffe).
Der PTT-Pfad nutzt seit v0.3.1 `beam_size=5` (war 1; auf der 5090
latenzneutral) — dieser Hebel ist also schon gezogen.

## Branded icon workflow

Two ICO files in `assets/`:

- `icon.ico` — source-of-truth, schwarzes Logo auf transparentem Hintergrund.
  Wird vom Tray-Runtime-Code als Logo-Quelle gelesen (der gelbe Tray-Background
  wird zur Laufzeit aus diesem Glyph plus `ICON_PADDING` generiert).
- `icon-branded.ico` — Build-Artefakt: gelbes Rounded-Square als Hintergrund
  + das Logo aus `icon.ico` zentriert. Drei Verwendungen:
  1. Embedded in `kira.exe` / `kira-once.exe` (über `embed_icon.ps1`),
     so dass Datei-Explorer / Alt-Tab / Taskbar das gelbe Icon zeigen.
  2. Im Inno-Installer (`installer/kira.iss`) gebundelt + Setup-Icon.
  3. Als `setWindowIcon(...)` in jedem Qt-Dialog (`AboutDialog`,
     `SettingsDialog`, `WelcomeDialog`, `SetupHintDialog`) und als
     `qt_app.setWindowIcon(...)` global in `_run_windows()`. Vorher
     zeigten die Dialog-Title-Bars das schwarze `icon.ico`, was im
     Win11-Dark-Title-Bar-Stil als schwarz-auf-dunkelgrau verschwand.

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
demselben Look. `ICON_PADDING = 10` (~16 % Innenabstand) — bei
weniger Padding schrumpft der gelbe Rand auf der 16×16-Tray-Größe auf
~1 px und das Icon liest sich als schwarz-auf-schwarz im Win11-Dark-
Tray. Modul-Level-Caches in `kira/ui/tray_win.py` (`_LOGO_CACHE`,
`_ICON_CACHE`) eliminieren UNC-IO nach dem ersten Render — wichtig
weil `assets/` auf dem WSL-Tree liegt und jedes `Image.open()` sonst
`\\wsl.localhost\…` mehrfach pro F8-Zyklus trifft.

## Tray identity (Win11 notification area)

Pystray's default Win32 class name is
`'%s%dSystemTrayIcon' % (name, id(self))` — `id(self)` is randomised
per process. Win11's notification-area settings key "Show always" on
(window class, window title), so a fresh class on each launch
silently dropped the user's visibility choice every restart. Plus
pystray creates the window with `lpWindowName=None`, so Win11 falls
back to the process FileDescription (`pythonw.exe` → "Python") for
the display name.

`_KiraPystrayIcon` in `kira/ui/tray_win.py` patches both:

- `_register_class()` overrides the class name to a fixed
  `KiraDigitalrootsTrayIcon`.
- `WM_SETTEXT` / `WM_GETTEXT` / `WM_GETTEXTLENGTH` are wired through
  `DefWindowProc` via `_message_handlers`. Pystray's default
  `_dispatcher` returns `0` for any message not in the handler dict,
  which silently swallows `WM_SETTEXT` — `SetWindowTextW` *appears* to
  succeed but the title never gets stored. Without these passthroughs
  the patch looks fine in `kira.log` ("Tray window labelled 'Kira'")
  while `GetWindowTextW` still returns empty.
- A small daemon thread polls `icon._hwnd` and runs
  `SetWindowTextW(hwnd, 'Kira')` once. `_hwnd` is set inside pystray's
  own `_run` thread, so the patch can't happen synchronously after
  `pystray.Icon(...)`.

Verify from the Win-venv Python:
```python
import ctypes
hwnd = ctypes.windll.user32.FindWindowW("KiraDigitalrootsTrayIcon", None)
buf = ctypes.create_unicode_buffer(64)
ctypes.windll.user32.GetWindowTextW(hwnd, buf, 64)
print(hex(hwnd), buf.value)  # → 0x... 'Kira'
```

If the class atom is left registered after a native crash (Kira
didn't reach `_unregister_class`), the next launch's
`RegisterClassEx` returns 0 and pystray's daemon thread silently
dies — Qt main loop runs, hotkey works, but no tray icon ever
appears. From the user's side this looks like "Boot hängt komplett"
because they're waiting for the tray indicator. `_register_class`
recovers automatically: on `RegisterClassEx == 0` it calls
`UnregisterClassW(_KIRA_TRAY_CLASS, hInstance)` and retries once,
logging `Recovered stale tray window class …`. Reboot is no longer
required.

The tray menu's `Einstellungen…` entry is marked `default=True` so
left- and double-click on the tray icon open Settings directly instead
of just dropping the context menu.

## Test policy

- Windows tests (`tests/test_*_win.py`) skip on non-Windows via
  `pytest.skip(..., allow_module_level=True)`.
- Mac tests (`tests/test_hotkey.py`, `tests/test_injector.py`, etc.)
  fail to *collect* in the Windows WSL venv because they import Mac-only
  modules at the top.
- **Die Suite in GRUPPEN fahren, nie alle Dateien in einem Lauf:** Ein
  Kollektiv-Lauf über alle Win-Testdateien crasht nativ (0xc000001d,
  illegal instruction) beim Übergang test_tray_icon → test_styler —
  PIL/pystray-Zustand beißt sich mit den asyncio-Tests (vorbestehend,
  reproduziert 2026-07-03). Etablierte grüne Gruppen: (1) das Subset
  unten, (2) styler/ollama*/main/utilities + tray_*_guard/handler,
  (3) Qt-Dialoge (settings_dialog, setup_wizard, welcome_dialog).
- Run the Windows test subset from WSL with:

  ```bash
  cd /tmp && cmd.exe /c 'cd /d C:\Users\<user>\dev\kira && C:\Users\<user>\kira-venv\Scripts\python.exe -m pytest tests/test_transcriber_fw.py tests/test_hotkey_win.py tests/test_injector_win.py tests/test_context_win.py tests/test_permissions_win.py tests/test_config.py tests/test_recorder.py tests/test_state_machine.py tests/test_tray_icon.py -v'
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

The Windows installer (`installer/kira.iss`, Inno Setup 6) is the
Slim-Bundle (since v0.2.0): an embedded Python 3.12, pinned wheels
and the Ollama setup — total ~3.5 GB compressed as one 2 MB `.exe`
stub + 2 `.bin` splits (Inno DiskSpanning, `DiskSliceSize=2147483647`
→ 1.998 GiB per slice). The Whisper + Gemma models are NOT bundled;
the first-run wizard (`kira/setup_wizard.py`) pulls them at runtime.

Build orchestrator: `scripts/build_installer.ps1`. Pre-flights for
Inno Setup, WSL Ollama, and the local Whisper model. Build output
currently lands in `C:\Users\mike\OneDrive\Digitalroots\Kira\` (the
script's hardcoded `$OutputDir` says `Desktop\Kira` — Mike moves the
files manually after the build for OneDrive sync; if that gets
automated, fix the script and this note).

### Distribution via GitHub Releases (since v0.1.0)

GitHub's per-asset limit is 2 GiB and Inno's 1.998 GiB slices fit
under it with ~0.002 GiB to spare. The whole bundle goes up as 4
release assets (`.exe` stub + 2 `.bin` splits + `SHA256SUMS.txt`),
the user downloads them all into the same folder and double-clicks
the `.exe` — Inno picks up the splits by name.

```bash
# from the WSL shell with `gh` authenticated as MikeGT4.
# --target needs the FULL 40-char commit SHA — an abbreviated SHA is
# rejected with "HTTP 422: target_commitish is invalid".
gh release create v0.2.5 \
  --target "$(git rev-parse HEAD)" \
  --title "Kira v0.2.5 — Windows 11" \
  --notes-file <release-notes.md> \
  /mnt/c/Users/mike/OneDrive/Digitalroots/Kira/Kira-Setup-v0.2.5.exe \
  /mnt/c/Users/mike/OneDrive/Digitalroots/Kira/Kira-Setup-v0.2.5-{1,2}.bin \
  /mnt/c/Users/mike/OneDrive/Digitalroots/Kira/SHA256SUMS.txt
```

Tag-Strategie: tags point at the source commit that matched the
build, NOT always at HEAD. v0.1.0 → `c7f6748` (initial release
commit, Apr 29) because the bundle was actually built from a
pre-Git snapshot earlier that day. Subsequent fixes on
`windows-port` HEAD (boot-hang, USB hot-unplug, branded icons)
will land in v0.1.1 as a rebuilt bundle. Make this explicit in
the release notes so users know what's *not* in the binary they
just downloaded.

Upload speed is bottlenecked by Mike's home uplink (~1.3 MB/s
observed) — the ~3.5 GB Slim-Bundle takes roughly 30–45 min. `gh
release create` / `gh release upload` parallelise asset uploads; the
GitHub API only lists assets after their individual upload finishes,
so don't read "1 of 4 visible" as "stuck" — it's just that one
asset crossed the line first while the others race.

### Why GitHub Releases instead of the old OneDrive share

The previous `2 GB per file` reading of GitHub's limit was wrong —
the actual limit is `2 GiB` and Inno already produces sub-GiB slices.
With GitHub-hosted assets the user clicks one URL, gets bandwidth
quota that doesn't depend on Mike's home upload, and there's a
canonical install instruction in the release notes (no Slack/Email
back-and-forth). `kira.updater`'s manifest-based multi-asset pull
is still on the v0.2 roadmap; until it lands, the in-app
"Updates suchen…" entry stays a hint dialog (see
`KiraTray._show_update_hint`).

## Frontend/UI/UX-Pipeline (PFLICHT)

Bei jedem UI-/Design-/Frontend-Task in diesem Projekt automatisch die passenden Skills + Plugins aktivieren — ohne dass Mike erinnern muss. Volle Mapping-Tabelle: [`~/CLAUDE.md`](../CLAUDE.md) und [`~/.claude/projects/-home-mikepollow/memory/feedback_frontend_skills_auto.md`](../.claude/projects/-home-mikepollow/memory/feedback_frontend_skills_auto.md).

**Standard-Pipeline:**
1. **Direction:** `frontend-design` (Anthropic) + `ui-ux-pro-max` (50 Styles, 21 Paletten, 50 Font-Pairings)
2. **Implementierung:** `senior-frontend` (React/Next/TS/Tailwind) — Subagent `webdesigner` mit obigen Skills bewaffnet
3. **Quality-Gate:** `web-design-guidelines` Skill (Vercel: 100+ A11y/Perf/UX-Regeln)
4. **Usability-Audit:** `frontend-design-audit` Plugin (15 Prinzipien, fixt direkt im Code)
5. **A11y (PFLICHT — DSGVO/Healthcare-Site):** `accesslint` Plugin (WCAG 2.2 audit→fix→verify) + `pa11y` + `axe` CLI
6. **Performance:** `lighthouse` lokal
7. **Bilder:** `nano-banana` (Gemini 3.1 Flash Image)
8. **Figma:** `figma` MCP + `figma-use` CLI + `figma-export` CLI
9. **Schnelle Mockups:** `playground` Plugin (interactive HTML-Artifacts) oder `flint` Plugin

## Karpathy-Prinzipien (PFLICHT)

Bei jedem Code-Edit, jeder Implementierung und jedem Refactor in diesem Projekt automatisch die 4 Karpathy-Prinzipien anwenden:
1. **Think Before Coding** — Annahmen explizit machen BEVOR Code geschrieben wird
2. **Simplicity First** — keine Over-Engineering, keine erfundenen Abstraktionen
3. **Surgical Changes** — nur ändern was nötig ist (kein "while-I'm-here"-Refactor)
4. **Goal-Driven Execution** — messbare Success-Kriterien VOR der Implementierung

Volle Doku: [`~/CLAUDE.md`](../CLAUDE.md) und [`~/.claude/projects/-home-mikepollow/memory/feedback_karpathy_principles.md`](../.claude/projects/-home-mikepollow/memory/feedback_karpathy_principles.md). Plugin: `andrej-karpathy-skills@karpathy-skills`, Skill: `karpathy-guidelines`.

## License

Personal use. See `LICENSE` (EN + DE) and `installer/license.de.txt`
(installer-displayed copy).
