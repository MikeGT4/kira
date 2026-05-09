# Changelog

## v0.2.0 — 2026-05-09

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

## v0.1.0 — 2026-04-29

- Erste Public-Release auf [github.com/MikeGT4/kira](https://github.com/MikeGT4/kira)
- Multi-Asset Inno-Bundle (1 stub + 7 .bin splits, ~13 GB) als GitHub-
  Release-Assets
- F8-Push-to-Talk mit pre-roll buffer, faster-whisper CUDA, Ollama-
  Polish, Tray-only UI, USB-Hot-Plug-Recovery, WSL-Auto-Kick
