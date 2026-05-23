# Changelog

## v0.2.6 — 2026-05-23

### Polish-Latenz-Detection + Auto-Fallback auf fast_model

Wenn Ollama das Polish-Modell auf CPU statt GPU lädt (bekannter
Ollama-on-Win11-Bug, siehe v0.2.5-Notiz), stieg die Polish-Latenz
in v0.2.5 stillschweigend auf 10–15 s und blieb dort, bis der User
Ollama oder den Rechner neu startete. v0.2.6 detected das selbst:

- **`kira/styler.py`:** Jeder `polish()`-Roundtrip wird wallclock-
  gemessen. Bei drei Calls in Folge > 3 s greift ein temporärer
  Auto-Switch auf `styler.fast_model` (Default `gemma3:4b`) für
  5 Minuten — das Modell passt auch unter VRAM-Druck in die GPU,
  Polish wieder < 1 s.
- **Tray-Toast:** Pystray-Notification „Polish auf CPU —
  temporär auf schnelles Modell umgeschaltet. Settings → GPU-Check".
  Re-Trigger wird unterdrückt, solange der Override aktiv ist, damit
  der User keinen Toast-Spam bekommt.
- **Per-Mode-Overrides** (`styler.modes[mode].model`) bleiben Vorrang
  — wer translate_en explizit auf `qwen3:8b` gepinnt hat, behält das
  Modell auch während des Auto-Switches.
- **Manueller `fast_mode=True`:** Auto-Switch wird übersprungen
  (wäre no-op), Toast feuert trotzdem — wenn das schnelle Modell
  selbst schlapp macht, ist Ollama/GPU komplett am Boden und der
  Hinweis wichtig.
- 11 neue Tests in `tests/test_styler.py`.

### Konstanten

`SLOW_POLISH_THRESHOLD_SEC = 3.0`, `SLOW_POLISH_TRIGGER_COUNT = 3`,
`FORCE_FAST_DURATION_SEC = 300`. Hartkodiert, nicht via config.yaml —
das sind Heuristik-Werte, kein User-Setting. Wer das tunen will,
editiert `kira/styler.py` direkt.

## v0.2.5 — 2026-05-22

### Einstellungen-Dialog: Rendering-Bug endlich behoben

Der seit v0.2.3 „nicht öffnende" Einstellungen-Dialog rendert wieder
korrekt. v0.2.4 hatte den Bug fälschlich als behoben gemeldet.

- **Kern-Ursache (`kira/ui/settings_dialog.py`):** Ein `QScrollArea`
  um die Section-Cards bricht unter Qt 6.11 die Theme-Vererbung — die
  Cards rendern mit dunklem Hintergrund, der `QLabel`-Text wird
  dunkel-auf-dunkel und damit unsichtbar. Isoliert verifiziert (eine
  Section-Card ohne QScrollArea rendert sauber, mit QScrollArea
  kaputt). Der QScrollArea ist entfernt.
- **2-Spalten-Layout:** Die sechs Section-Cards liegen jetzt in zwei
  Spalten (links Audio/Whisper/Polish-LLM, rechts Hotkeys/Inject/Über
  Kira) statt gestapelt. Dialog ~770 statt ~1270 px hoch.

### Einstellungen-Dialog: Checkbox-Kästchen sichtbar

Die Checkboxen („AI-Editing-Befehle aktiv", „Schneller Modus") zeigten
nur Text, kein Kästchen. `kira/ui/_dialog_style.py`: das Theme-QSS
stylt `QCheckBox`, aber ohne `QCheckBox::indicator`-Regel rendert Qt
das Kästchen transparent → unsichtbar auf der hellen Card. `_QSS`
buchstabiert das Kästchen jetzt aus (weiß umrandet, blau gefüllt wenn
aktiv).

### Styler: Qwen-3-Modelle als Polish-LLM nutzbar

`kira/styler.py`: Qwen-3 sind Hybrid-Reasoning-Modelle und geben per
Default `<think>`-Blöcke aus — für eine treue Polish-/Edit-Task
falsch. Neuer `_thinking_kwargs()`-Helper setzt `think=False` an den
Ollama-Chat-Aufrufen, aber nur für `qwen3*`-Modelle (Gemma & Co.
bleiben unberührt). `scripts/probes/probe_terminal_prompt.py` nimmt
jetzt optional ein Modell-Argument; 0/6 buggy gegen `qwen3:8b`.

### Settings-Dialog: kein doppeltes Modal-Setup beim Öffnen

`kira/ui/tray_win.py`: `_show_settings_dialog` ruft nur noch die
modale Event-Loop-Methode des Dialogs direkt auf. Der v0.2.4-Versuch
rief davor zusätzlich `show()` + `raise_()` + `activateWindow()` — das
löste ein doppeltes Modal-Setup aus. Test
`tests/test_tray_settings_guard.py` angepasst.

## v0.2.4 — 2026-05-21

### Settings-Dialog kommt zuverlässig in den Vordergrund

Der „Einstellungen…"-Eintrag im Tray-Menü öffnete den Dialog
manchmal **hinter** dem gerade aktiven Fenster — für den Nutzer sah
es aus, als „passiere nichts". Das Log bestätigte: Der Dialog wurde
korrekt erzeugt (`isVisible=True`), kam aber nicht in den Vordergrund
(`active=False`).

**Ursache:** Kira ist eine Tray-App (Hintergrund-Prozess) ohne
Hauptfenster. Windows' Fokus-Stealing-Prevention lässt so einen
Prozess ein neu geöffnetes Fenster nicht zuverlässig nach vorn
bringen — mal landete der modale Dialog vorne, mal verdeckt.

**Fix (`kira/ui/tray_win.py`):** `_show_settings_dialog` ruft vor
dem modalen Loop explizit `show()` + `raise_()` + `activateWindow()`
auf und holt den Dialog so aktiv in den Vordergrund. Test
`tests/test_tray_settings_guard.py` entsprechend erweitert.

## v0.2.3 — 2026-05-21

### AI-Editing als Ein/Aus-Schalter (Settings-Dialog)

Die AI-Editing-Befehle (F9: Text markieren, Hotkey halten, Sprach-
befehl sprechen, das LLM überarbeitet die Selektion) ließen sich
bisher nur abschalten, indem man das Edit-Command-Textfeld in den
Einstellungen leerte — versteckt im Tooltip. Jetzt gibt es dafür
eine explizite Checkbox.

- **Settings-Dialog (`kira/ui/settings_dialog.py`):** Neue Checkbox
  „AI-Editing-Befehle aktiv" in der Hotkeys-Section. Checkbox aus →
  gespeichert wird `hotkey.edit_combo: null`. Das Edit-Command-Feld
  wird ausgegraut, wenn die Checkbox aus ist, und beim Wieder-
  Einschalten mit „f9" vorbefüllt. Eine Warnung beim Speichern
  verhindert den widersprüchlichen Zustand „Checkbox an, Feld leer".
- Keine Config-Schema-Änderung — `hotkey.edit_combo: str | None`
  existierte bereits; die Checkbox ist reine UI darüber.
- Resolve-Logik als testbare Staticmethod `_resolve_edit_combo`
  herausgezogen; 4 neue Tests in `tests/test_settings_dialog.py`.

### idna 3.15 — Dependabot-Security-Fix

`installer/requirements-bundle.txt`: `idna` von `3.13` auf `3.15`
gebumpt (CVE-2026-45409 / GHSA-65pc-fj4g-8rjx, medium — ein DoS-
Bypass in `idna.encode()` bei präparierten Eingaben). Für Kira
praktisch nicht ausnutzbar — Kira spricht nur mit festen, ver-
trauenswürdigen Hosts (`localhost`, `github.com`) —, aber `idna`
3.15 ist ein reiner Security-Patch-Release: risikoloser Bump, der
den Dependabot-Alert schließt. `kira-venv` mitgezogen.

### Prompt-Härtung für `clean.md` und `email_formal.md`

Nachdem `prompts/terminal.md` in v0.2.2 für 4B-Few-Shot-Schwäche
gehärtet wurde, Audit aller Mode-Prompts — zwei weitere Files hatten
das gleiche Inline-Beispiel-Pattern:

- **`clean.md`**: hatte `Stotter-Wiederholungen ("ich, ich, ich denke"
  -> "ich denke")` inline. Beispiele in separaten Block ausgelagert
  (3 Varianten ohne Verb-Anker), plus explizite "NIEMALS umformulieren"-
  Regel am Ende. Ohne den extra-Disclaimer halluzinierte 4B aus dem
  ersten Test-Beispiel "Schau mal kurz" → "Schau mal jetzt machen" für
  unverwandte Inputs.
- **`email_formal.md`**: hatte das Du-zu-Sie-Beispiel `("kannst du mir
  das schicken" -> "koennten Sie mir das zusenden")` inline. 3 Beispiele
  in eigenem Block. **Bleibt fragile**: bei Statement-Inputs ("Der
  Termin passt mir gut") kann 4B in Frage-Form halluzinieren
  ("Koennten Sie den Termin bestaetigen"). Empfehlung für Praxis-
  Workflows: Per-Mode-Override in `config.yaml` setzen, damit
  `email_formal` immer mit 12B läuft auch wenn `fast_mode: true`:

  ```yaml
  styler:
    fast_mode: true
    modes:
      email_formal:
        model: gemma3:12b
  ```

- **`scripts/probes/probe_prompts_4b.py`**: neues Probe-Script, läuft
  13 realistische Inputs durch gemma3:4b gegen alle drei Prompts.
  Floort Halluzinationen via Regex. Aktuell 0/13 buggy.

Nicht im v0.2.2-Bundle (Tag `v0.2.2 → 65e6cfc` ging vor diesen Fixes
raus). Source-only, wirkt auf Editable-Installs. Wird mit dem
nächsten Release-Bundle aktiv.

### Automatischer Update-Check beim App-Start

Kira prüft beim Start selbst, ob auf GitHub eine neuere Version
vorliegt, und fragt proaktiv nach („Neue Version vX.Y.Z verfügbar —
herunterladen?"). Bei Zustimmung läuft der bestehende Update-Flow
(Download + SHA256-Verifikation + Setup-Start).

- Der Check läuft auf einem eigenen Daemon-Thread
  (`kira-update-check`), analog zum Setup-Probe — der Boot bleibt
  unblockiert.
- Nur eine echte neuere Version löst die Abfrage aus. Netz- und
  Parse-Fehler scheitern still (nur Log-Eintrag, kein Dialog).
- „Nicht erneut nerven": Lehnt der Nutzer eine Version ab, wird sie
  in `%APPDATA%\Kira\.update-declined` gemerkt — dieselbe Version
  fragt beim nächsten Start nicht erneut, eine neuere schon. Neues
  Modul `kira/_update_marker.py` mit demselben Resolve-Muster wie
  `kira/firstrun.py`.
- Neues optionales Config-Feld `updates.check_on_start` (Default
  `true`) schaltet den Start-Check ab. Der manuelle „Updates
  suchen…"-Eintrag im Tray bleibt davon unberührt.
- 10 neue Tests (`test_update_marker.py` plus Ergänzungen in
  `test_config.py` und `test_tray_update_handler.py`).

### Unzensiertes Polish-LLM optional ladbar

Neuer Button „Unzensiertes Modell laden…" in der Polish-LLM-Section-
Card der Einstellungen. Lädt das abliterierte Qwen3.6 27B
(`huihui_ai/Qwen3.6-abliterated:27b`, ~17 GB) per `ollama pull` und
trägt es als Qualitätsmodell ein.

- Vor dem Pull ein GPU-Check gegen das 27B-Modell. Bei knappem oder
  unzureichendem VRAM erscheint ein Ja/Nein-Dialog mit dem Trade-off
  (27B braucht ~16 GB und passt auf 16-GB-Karten nicht neben Whisper
  → CPU-Offload, langsamerer Polish); der Nutzer kann abbrechen.
- Liegt das Modell schon im Ollama-Cache, wird der Pull übersprungen.
- Roter Klartext-Hinweis in der Card („Unzensiert — die Inhaltsfilter
  des Modells sind entfernt …").
- `fast_mode`-Falle: Ist der Schnelle Modus aktiv, überschreibt
  `styler.fast_model` das eingetragene Qualitätsmodell — der Dialog
  weist darauf hin.
- 5 neue Tests in `test_settings_dialog.py`.

### Neuer Boot-Splash

Der Start-Splash hat ein neues dunkles Design: dunkles Panel mit
gerundeten, transparenten Ecken, gelbes Icon mit Glow, „KIRA" als
Pinsel-Kalligrafie-Schriftzug, technische Mono-Tagline „VOICE TO
TEXT", rotes „UNCENSORED"-Label und ein feiner Amber-Rahmen.
`splash.py` setzt `WA_TranslucentBackground`, damit die gerundeten
Ecken durchsichtig sind.

### GPU-Prüfung repariert + animierte Statusanzeige

Der GPU-Check (Einstellungen → „Über Kira" → „GPU prüfen") meldete auf
einer RTX 5090 hartnäckig „keine NVIDIA-GPU". Ursache: `detect_gpu`
rief `nvidia-smi` mit `subprocess.run(timeout=5.0)` auf — unter GPU-Last
(aktive CUDA-Kontexte von Whisper + Ollama) braucht `nvidia-smi` aber
regelmäßig länger als 5 s, der Aufruf lief in `TimeoutExpired` und wurde
als „keine GPU" gewertet.

- `detect_gpu`-Timeout von 5 s auf 30 s erhöht, dazu `stdin=DEVNULL`
  (Best Practice für subprocess in GUI-Prozessen ohne Konsole).
- Per-Kandidat-Logging: jeder nvidia-smi-Pfad loggt nun Existenz und
  exakten Fehler einzeln. Die alte Sammel-Logzeile zeigte nur den
  zuletzt probierten Pfad und verschleierte die eigentliche Ursache.
- Der GPU-Check läuft jetzt auf einem `QThread` — ein bis zu 30 s
  langer Aufruf im Qt-Main-Thread würde das Settings-Fenster einfrieren.
- Neuer animierter Wartedialog (`kira/ui/_gpu_scan_dialog.py`):
  scrollende Neon-Sinuswelle auf dunklem Panel, pixel-scharf im Stil
  des HUD-Oszilloskops.

### Settings-Dialog: kein doppeltes Fenster

„Einstellungen…" ist die Default-Aktion beim Tray-Links-/Doppelklick.
Ein erneuter Klick bei bereits offenem Settings-Fenster öffnete einen
zweiten, modal darübergestapelten Dialog. `KiraTray._show_settings_dialog`
hat jetzt einen Single-Instance-Guard: ist ein Fenster offen, wird es
nach vorn geholt (`raise_` + `activateWindow`) statt ein zweites zu
erzeugen. 3 neue Tests in `test_tray_settings_guard.py`.

### Uncensored-Hinweis: 🔞-Kennzeichnung

Der rote Hinweis zum unzensierten Polish-Modell trägt jetzt ein 🔞-
Symbol (in Section-Card-Emoji-Größe) und ist fett sowie zentriert
gesetzt — eine deutlichere Kennzeichnung für 18+-Inhalte.

## v0.2.2 — 2026-05-17

### Schneller Polish-Modus (Settings-Toggle)

Speed-Toggle in den Einstellungen fuer die Polish-Pipeline. Standard-
LLM `gemma3:12b` rutscht bei VRAM-Druck (Chrome + Outlook + RDP +
EdgeWebView gleichzeitig offen) in den CPU-Offload-Split und Polish-
Latenz steigt von ~0,3 s auf 2–4 s. Toggle schaltet auf `gemma3:4b`
(`styler.fast_model`), das auch bei vollem Desktop 100 % in GPU passt.

- **`StylerConfig` (`kira/config.py`):** Neue Felder `fast_mode: bool`
  (Default `False` — kein Verhaltens-Change beim Upgrade) und
  `fast_model: str` (Default `gemma3:4b`). Power-User koennen das
  Speed-Modell ueber `config.yaml` ueberschreiben.
- **`Styler` (`kira/styler.py`):** Neuer `_resolve_model()`-Helper
  zentralisiert die Modell-Auswahl-Hierarchie:
  1. `ModeConfig.model` (Per-Mode-Override, hoechste Prioritaet)
  2. `fast_model` wenn `fast_mode=True`
  3. `model` als Default.
  `warmup()`, `polish()` und `edit_command()` nutzen den Helper —
  einheitliches Verhalten ueber alle Pfade.
- **Settings-Dialog (`kira/ui/settings_dialog.py`):** Neue Checkbox
  in der bestehenden "Polish-LLM"-Card. Tooltip listet die Trade-offs
  (F9-Editing schwaecher, lange Briefings leicht inkonsistent).
  Beim ersten Aktivieren: `_ollama_model_installed()`-Pre-Check, falls
  Modell fehlt — Progress-Dialog `_pull_blocking()` mit QEventLoop
  fuer synchrone Wartezeit + sauberer Cancel-Pfad. Bei Pull-Fehler
  oder Abbruch: Toggle springt zurueck auf `False`, Save abgebrochen.
- **Tests (`tests/test_styler.py`, `tests/test_config.py`):** 7 neue
  Test-Cases: Defaults, YAML-Override, fast_mode-an/aus Branching,
  Per-Mode-Override-Hierarchie, Warmup + Edit-Command-Pfade. Alle
  33 styler/config-Tests gruen.
- **`prompts/terminal.md` gehaertet:** Der Original-Prompt hatte
  "get status -> git status" als einziges Beispiel inline. 12B
  parst das korrekt als Illustration; 4B fixiert sich darauf (Few-
  Shot-Schwaeche) und gibt fuer ALLE Inputs "git status" zurueck.
  Im Live-Test mit Mike's PBX-Briefings repro'd vor Release. Fix:
  separater "Beispiele"-Block mit explizitem Disclaimer
  ("NICHT als Output-Vorlage verwenden"), 4 statt 1 Beispiel
  (Konversation + Shell-Befehle gemischt), plus expliziter
  Output-Regel "kein Kommentar, keine Erklaerung, kein Beispiel".
  Verifiziert mit `scripts/probes/probe_terminal_prompt.py` (0/6
  buggy outputs gegen gemma3:4b).

## v0.2.1 — 2026-05-12

### Pixel-Oszilloskop-HUD (2026-05-12)

Recording-HUD-Look überarbeitet: statt der gelben Bar-Anzeige zeigt
das HUD jetzt eine pixel-scharfe 2-px-Wellenform in digitalroots-Grün
(Neon-Variante des Brand-Greens `#006F32`). Antialiasing für die
Welle deaktiviert, damit die Linie auf nativer Auflösung scharf bleibt
(SquareCap + MiterJoin). Status-Text + Hintergrund bleiben antialiased
für Lesbarkeit.

- **Recorder-API erweitert:** Neuer `set_samples_callback(cb)` neben
  dem bestehenden `set_level_callback()`. Liefert pro Audio-Block den
  rohen Mono-Sample-Array (np.ndarray, float32) statt nur RMS. Mac-
  Pfad (popup.py + push_level) komplett unangetastet.
- **HUD-Pipeline (`kira/ui/hud_qt.py`):** Peak-Downsampling auf 30
  Punkte pro Audio-Block (Envelope bleibt erhalten, kein Stride-
  Aliasing). Ringbuffer von 240 Punkten = ein Sample pro Pixel-Spalte
  bei voller Belegung. `paintEvent` rendert eine `QPolygonF` mit
  width=2 in `WAVE_COLOR = QColor(60, 220, 110)`.
- **Win-Verdrahtung (`kira/main.py:504`):** `set_level_callback(...)`
  → `set_samples_callback(...)`. Mac-Verdrahtung (line 190) bleibt
  identisch.

## v0.2.0 — 2026-05-10

### WSL-Decoupling + Slim-Installer (2026-05-10)

Mike's Dev-PC entkoppelt von WSL-Bindungen, plus Distri-Format auf
Slim-Installer mit First-Run-Wizard umgestellt. End-User-Erlebnis: eine
Setup-EXE (~1.5 GB) statt 8-File-Bundle (13 GB), Modelle werden beim
ersten Start gepullt.

- **Source-Tree auf NTFS:** Kira's Editable-Install zeigt nicht mehr
  auf `\\wsl.localhost\…`. WSL kann jetzt heruntergefahren werden ohne
  dass Kira ausfällt. Phase-A-Migration auf Mike's PC: alter
  WSL-Tree → Backup, neuer Tree unter `C:\Users\mike\dev\kira\` mit
  Symlink `~/claude_kira` für unveränderten WSL-Bash-Workflow.
  Ollama läuft jetzt nativ auf Windows (`winget install Ollama.Ollama`,
  v0.23.x), nicht mehr in WSL-Ubuntu via systemd + wslrelay.
- **Setup-Scripts mit `-Source`-Param:** `install_win.ps1`,
  `install_autostart.ps1`, `embed_icon.ps1` arbeiten ohne
  UNC-Hardcode — Default `$PSScriptRoot\..` macht sie repo-relativ.
  PR-Material für Public-Repo.
- **First-Run-Wizard (`kira/setup_wizard.py`):** Qt-`QWizard` mit
  3 Pages (Welcome, Download, Finished). 3 Worker-Threads pullen
  parallel: `WhisperDownloadWorker` via `huggingface_hub.snapshot_download`
  (`Systran/faster-whisper-large-v3`, ~3 GB), `OllamaSetupWorker` führt
  embedded `OllamaSetup.exe /S /NORESTART` aus wenn Ollama nicht da,
  `GemmaPullWorker` `ollama pull gemma3:12b` (~8 GB). Cancel via
  `threading.Event` + Subprocess-`terminate()` (Critical-Fix —
  `QThread.quit()` hatte keinen Effekt auf die blockierenden run()s).
  Cross-Worker-Abort: Whisper-Error stoppt Ollama+Gemma sofort statt
  8 GB unnötig zu pullen.
- **First-Run-Detection (`kira/firstrun.py`):** Marker-File
  `%APPDATA%\Kira\.first-run-complete` wird NUR bei Total-Erfolg in
  `SetupWizard.accept()` geschrieben. Bei Crash/Cancel kein Marker →
  Wizard erscheint beim nächsten Start wieder. Bei Marker-Write-Fail
  zeigt Wizard `QMessageBox.warning` mit Klartext-Hint.
- **127.0.0.1 statt `localhost`:** Win11 24H2+ resolvt `localhost` zu
  IPv6 `::1`, Ollama bindet IPv4. Kira's Polish-Endpoint hart-codiert
  auf `http://127.0.0.1:11434/api/tags`.
- **Inno-Wizard-Branding:** `WizardStyle=modern`, Side-Image
  (164×314 BMP24, gelb-branded Kira-Glyph + Wordmark + digitalroots-
  Footer auf dunkelgrauem `#1c1c1c`-BG), Top-Image (55×58),
  `LicenseFile`. Custom Welcome/Finished Pages mit deutschem Wording
  via `[Messages]`-Section. Asset-Generator
  `scripts/build_wizard_images.py` (Pillow-basiert).
- **Slim-Bundle-Build:** `scripts/build_installer.ps1` zieht Whisper +
  Gemma raus, embedded `OllamaSetup.exe` rein (~600 MB,
  `installer/embedded/`). `DiskSpanning=yes` mit 1.998 GiB Slice → in der
  Praxis Single-File-EXE bei <2 GiB Source, sonst Auto-Split in 1-2 .bin-Files
  je <2 GiB
  (passt unter GitHub-Release-2-GiB-Limit). Sub-Installer-`[Run]` mit
  `Check: NeedsOllama` Pascal-Function (testet
  `%LOCALAPPDATA%\Programs\Ollama\ollama.exe`).
- **31 neue Tests** in `tests/test_firstrun.py` (4) +
  `tests/test_setup_wizard.py` (27, davon 5 Cancel/Abort/Marker-Fixup-
  Tests).

### Build- und Install-Fixes Phase F2 (2026-05-10 nachmittags–abends)

23-Sub-Phase-Iteration auf dem Slim-Installer bis Bundle-kira.exe + Bundle-
pythonw.exe sauber laufen. Die fünf folgenreichsten Cluster:

- **F2-19 (`24aae92`) — Embedded Python ohne venv-Layer.** Embedded
  Python-Distri enthält `venv` nicht (per Design — Distri-Ziel ist eine
  bereits-portable Python). `python -m venv` failt mit „No module named
  venv". Setup nutzt jetzt das embedded Python direkt als Kira-Runtime,
  pip-Installs in `{app}\python\Lib\site-packages\`, Entry-Points unter
  `{app}\python\Scripts\`.
- **F2-20 (`0f6d34f`) — Ultrareview-Welle.** 9 Findings durch:
  HF-Hub `allow_patterns`-Whitelist für Whisper-Pull (defense gegen
  HF-Hub-Mirror-Hijack), `_resource_path` Path-Traversal-Defense,
  `firstrun.py` `EnvironmentError`-Hardening + USERPROFILE-Whitelist,
  Cancel-Race-Lock in `SetupWizard._abort_pipeline`, CREATE_NO_WINDOW-Flag
  für `OllamaSetup.exe`-Popen, Cancel-Bypass-Override (`closeEvent` +
  `reject` zusammen), Build-Deps-Cleanup nach Wheel-Build, hatchling-
  `==`-Pinning in `requirements-bundle.txt`, CHANGELOG/README-Drift-
  Fixes.
- **F2-22 (`1a67d81`) — Wheel-aware Asset-Pfade.** Neues
  `kira/_resources.py` mit `assets_dir()` + `prompts_dir()`-Helpern. Alle
  7 UI-Module + `styler.py` umgestellt. Wheel-Install resolvt zu
  `kira/_assets/` (force-include in `pyproject.toml`), Source-Tree
  weiter auf `<repo>/assets/`. Sonst hätte das Bundle auf den
  Build-Tree-Pfad gezeigt, der auf End-User-Boxen nicht existiert.
- **F2-23 (`a8c7dd2`) — rcedit-x64 `[Run]`-Steps DEAKTIVIERT.**
  Root-Cause der ganzen „kira.exe Exit -1 silent"-Welle. rcedit-x64.exe
  v2.0.0 modifiziert PE-Resources (Icon + Version-Strings) per
  Section-Rewrite. Pip/distlib-generierte gui_scripts-Wrapper
  (`kira.exe`, `kira-once.exe`) sind aber PE-Loader + APPENDED ZIP-Stream
  am EXE-Ende — rcedit zerschneidet diesen ZIP beim Rewrite. PE-Loader
  lädt EXE, pip-Stub findet sein script-payload nicht, exit -1 ohne
  stdout, stderr, MsgBox, faulthandler-Log oder kira-Log. Exakt Mike's
  „unable to find an appended archive"-Symptom. TRADE-OFF: kira.exe +
  kira-once.exe haben jetzt das pip-default-Icon (Python-Logo) im
  Datei-Explorer. Tray-Icon (via runtime `tray_win.py`), Lnk-Icons
  (`{app}\assets\icon-branded.ico` via Inno `[Icons]`-IconFilename) +
  Setup-Wizard-UI bleiben branded.

**Validierung Mike's Box 2026-05-10 20:00:** kira.exe + pythonw.exe
beide aus `C:\Users\mike\AppData\Local\Kira\python\` aktiv, Boot-
Sequenz 7 s (Tray + F8/F9 + Whisper-Warmup auf CUDA + gemma3:12b-
Polish-Warmup). Autostart-Lnk zeigt korrekt auf Bundle-kira.exe.

### Late-Day Review-Welle (commit `30dd02c`, 2026-05-09)

4-Subagenten-Review (code-reviewer, security-auditor, silent-failure-
hunter, best-practice-checker) parallel dispatched. 13+ Findings,
gefixt in einer Sammelung:

- **F9-Edit-Command Silent-Failure-Cluster:** `read_selection()`
  raised jetzt `ClipboardUnavailable` statt return None bei Fehlern,
  Sentinel-String entfernt (pollutierte Clipboard-Watcher), `on_edit_press`
  flasht ERROR (1.5 s gelb) bei No-Selection/Clipboard-Fehler statt
  silent No-Op, `edit_command` raised RuntimeError statt re-injectet
  Original-Selection.
- **Async-Blocking transcribe:** `_run_pipeline` nutzt jetzt
  `asyncio.to_thread()` für Whisper — Tray-Updates + Hotkey bleiben
  responsive während des 5-10 s CUDA-Cold-Starts.
- **Updater Resume + Whitelist:** `download_bundle` skippt Files mit
  matchender size, ermöglicht Retry ohne 13 GB neu zu pullen. Asset-
  Name-Regex `^Kira-Setup-vX.Y.Z(-N.bin|.exe)$` schützt vor Path-
  Traversal in kompromittierten GitHub-Releases.
- **transcribe_file:** respektiert jetzt `condition_on_previous_text`
  aus config (war hardcoded True), per-Segment-Hallucination-Filter
  statt only-on-full-text-equality.
- **Polish empty-response:** symmetric mit Timeout-Pfad — raised wenn
  `fallback_to_raw=False`, statt silent empty-string return.
- **Settings-Dialog `closeEvent`:** terminiert laufenden Polish-Pull-
  Worker → kein Segfault wenn User Settings während Pull schließt.
- **notepad.exe-Launch:** try/except + Fallback-Dialog (Win11 N-Edition
  / Kiosk hat kein notepad).
- **Edit-Command-Prompt:** anti-Prompt-Injection-Hinweis, 4-Backtick-
  Fences statt 3.
- **GPU-Check:** bare `nvidia-smi` aus PATH-Search-Kandidaten —
  schützt vor User-folder `nvidia-smi.exe` Hijack. Nur absolute Pfade
  (System32, Program Files).
- **`ModeConfig.temperature`:** None-able für konsistente None-
  Semantik (Karpathy: keine Felder mit zwei verschiedenen Semantiken).
- **`config_writer`:** Section-Existenz-Check liest Source-YAML (statt
  mutated out_lines) — defensiv gegen künftige Refactors.
- **Tray-Menü:** Branded Disabled-Item „✨ Kira ✨" oben (Win32-Native
  hat keine Custom-Widget-API für richtigen Logo-Header — pragmatic
  Mittelweg).

Pending (separate Wellen, zu groß für diese Sammlung): Ollama-Missing-
permanenter-Tray-Indicator, projekt-weite Logging-Konsistenz, gemein-
sames F8/F9-Listener-Lock für simultane-Press-Race.

### Earlier am 2026-05-09

Personal-use voice-to-text app, Windows 11 + WSL2 (`windows-port` branch).

### Neue Features

#### Custom Dictionary / Phrase-Replacement
Whisper transkribiert Eigennamen, Praxis-Begriffe und Patientenvornamen
oft falsch. Eine neue `whisper.replacements`-Map in `config.yaml` erlaubt
deterministische Find/Replace-Korrekturen NACH Whisper und VOR dem Polish.
Match ist case-insensitive Substring; Insertion-Order wird respektiert.

```yaml
whisper:
  replacements:
    "im mediku": "im medicum"
    "frau schmid": "Frau Schmidt"
```

#### AI-Modes (User-konfigurierbar)
`StylerConfig.modes` erlaubt pro Mode (z.B. `email`, `chat`, `code`)
einen eigenen Polish-Prompt PLUS optional eigenes Modell, eigenen
Timeout, eigene Temperature. Drei neue eingebaute Modi:

- **`clean`** — minimaler Filler-Filter ohne Inhalts-Modifikation
  (für „äh", „ähm", „also", „halt", „quasi" und Stotter-Wiederholungen)
- **`translate_en`** — Deutsch → Englisch on-the-fly
- **`email_formal`** — Sie-Form, Praxis-Stil

Eigene Modi: einfach `prompts/<modename>.md` anlegen — `load_prompt()`
findet sie automatisch. Mapping in `context_modes` ändern oder über
`StylerConfig.modes` mit Override-Modell hinterlegen.

#### AI-Editing-Commands (F9 Hold)
Zweite Hotkey-Combo für Selection-Editing. Workflow:

1. Text in beliebiger App selektieren
2. F9 halten, sprechen: „mach das förmlich" / „übersetz ins Englische" /
   „fass das in 3 Bullets zusammen"
3. F9 loslassen
4. Whisper transkribiert den Voice-Command, das LLM rewriteset die
   Selektion mit `prompts/edit_command.md`, Strg+V ersetzt sie

Sentinel-basierte Selection-Detection: ohne aktive Selection ist der
Hotkey ein No-Op (kein Recording-Feedback). Bei Fehlern fällt der
Editor auf die Original-Selektion zurück, damit Strg+V niemals Garbage
über die Selektion schreibt.

Konfigurierbar via `hotkey.edit_combo` (Default `f9`, leer = aus).

#### File-Transcription (Tray-Menü)
Neuer Eintrag „Datei transkribieren…" im Tray-Kontextmenü:

- QFileDialog für Audio/Video (.wav, .mp3, .m4a, .flac, .ogg, .opus,
  .mp4, .mov, .mkv, .webm)
- Worker-Thread mit Progress-Dialog (faster-whisper läuft Minuten lang
  bei Stunden-Files, Qt-Mainthread bleibt responsiv)
- File-Mode-Settings (`beam_size=5`, `vad_filter=True`,
  `condition_on_previous_text=True`) statt der aggressiven PTT-Anti-
  Halluzinations-Settings — quality-optimiert für lange Files
- Output: `.txt` neben der Eingabe-Datei
- Replacements werden auch hier angewendet

Faster-whisper nutzt PyAV/ffmpeg intern — Video-Files funktionieren ohne
externe Tools.

#### Mikrofon-Auswahl als Dropdown (war v0.2-Pre-Release Polish)
Settings-Dialog: ehemaliges Substring-Textfeld ersetzt durch QComboBox
mit allen aktuellen Inputs aus `sd.query_devices()`. „Aktualisieren"-
Button re-queryt während der Dialog offen ist. Speichert weiterhin den
Namen (Substring-resilient gegen PortAudio-Index-Shuffles nach USB-
Hot-Plug).

### Settings-Dialog Modern Design
Refactor des bisherigen Single-Form-Layouts in fünf Section-Cards
(Audio · Whisper · Polish-LLM · Hotkeys · Inject) im Win11-Settings-
Stil: Section-Header mit Emoji-Icon, dünne Trennlinie, weißer Card-
Hintergrund mit subtle Border, mehr Vertical-Spacing.

Neue Felder:
- Edit-Command-Hotkey (für AI-Editing-Commands)

### Tests
- 17 neue Unit-Tests (replacements, styler-modes, edit-command pipeline,
  state-machine edit-flag-handling, transcribe_file file-mode-settings)
- 77 Tests grün (vorher 60)

### Sonstiges
- `kira.hotkey_win.SUPPORTED_COMBOS` erweitert um `f9`
- `KiraTray` erhält optionales `transcriber=`-Argument für File-
  Transcription. Ohne Transcriber blendet sich der Menü-Eintrag aus.
- `KiraApp` erweitert um `_edit_mode` und `_captured_selection` Flags
  + `on_edit_press()` Methode. State-Machine bleibt unverändert (kein
  neuer State), Pipeline-Verzweigung im `_run_pipeline` via Flag-Check.

### Known issues / Configuration tips

**USB-Mikrofone + ASUS AI Noise-Canceling Filter** (Diagnose 2026-05-11):
Bei Autostart-Boot kann es vorkommen, dass das USB-Mikrofon noch nicht
enumeriert ist und Windows den `AI Noise-Canceling Microphone (Intelligo
VAC / ASUS Utility)` als Default aktiv hält. Dessen Filter killt
gesprochenes Audio als Noise → `Recorder.stop` loggt `peak=0.0002 rms=0.0001`
→ Whisper halluziniert „Vielen Dank." → Hallucination-Filter abort →
kein Text injiziert. Aus User-Sicht: Kira reagiert nicht. Workaround
in `%APPDATA%\Kira\config.yaml`:

```yaml
audio:
  input_device: "Shure MV7+"   # Substring-Match, case-insensitive
  # oder: "ROG Theta", "Headset Microphone", "Realtek" etc.
```

Bei Cold-Boot, wenn der USB-Mic noch nicht da ist, wirft der Recorder
`DeviceUnavailable` → gelbes Tray-Icon 3 s. 5-10 s warten + nochmal
Hotkey löst's dann sauber. `scripts/audio_diagnose.py` enumeriert
verfügbare Devices.

### Release-Info

- **Tag:** `v0.2.0` auf Commit `a69e776` (Docs)
- **Bundle-Source-Commit:** `a8c7dd2` (Phase F2-23)
- **Release-Date:** 2026-05-11
- **Bundle-Assets:** `Kira-Setup-v0.2.0.exe` (2 MB Stub) +
  `Kira-Setup-v0.2.0-1.bin` (2.0 GiB) + `Kira-Setup-v0.2.0-2.bin`
  (1.4 GiB) + `SHA256SUMS.txt`. Alle drei Setup-Files müssen in
  denselben Ordner.

## v0.1.0 — 2026-04-29

- Erste Public-Release auf [github.com/MikeGT4/kira](https://github.com/MikeGT4/kira)
- Multi-Asset Inno-Bundle (1 stub + 7 .bin splits, ~13 GB) als GitHub-
  Release-Assets
- F8-Push-to-Talk mit pre-roll buffer, faster-whisper CUDA, Ollama-
  Polish, Tray-only UI, USB-Hot-Plug-Recovery, WSL-Auto-Kick
