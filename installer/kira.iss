; Kira Windows installer -- Inno Setup script.
; Compile via:
;   iscc /DVersion=0.2.0 /DBuildDir=<abs> /DOutputDir=<abs> installer/kira.iss
; (the build_installer.ps1 wrapper supplies the /D defines)

#ifndef Version
  #error "Version not defined. Pass /DVersion=x.y.z to ISCC."
#endif

#ifndef BuildDir
  #error "BuildDir not defined. Pass /DBuildDir=<absolute path>."
#endif

#ifndef OutputDir
  #error "OutputDir not defined. Pass /DOutputDir=<absolute path>."
#endif

[Setup]
; Fixed AppId so future installers detect existing installs as upgrades.
AppId={{8A2C6A14-3B3D-4E2C-8A0E-7C9D1A0B2E33}
AppName=Kira
AppVersion={#Version}
AppPublisher=Mike Pollow
AppPublisherURL=https://github.com/MikeGT4/kira
DefaultDirName={localappdata}\Kira
DefaultGroupName=Kira
DisableProgramGroupPage=yes
LicenseFile={#BuildDir}\..\installer\license.de.txt
OutputDir={#OutputDir}
OutputBaseFilename=Kira-Setup-v{#Version}
Compression=lzma2/max
SolidCompression=yes
; Slim-Bundle ~1.5 GB Source aber Embedded Python + 56 Wheels + bundled
; OllamaSetup.exe (1.98 GB) summiert sich unter LZMA2-Compression auf ~3.5 GB
; Output. DiskSpanning=yes + DiskSliceSize=1.998 GiB ist als Safety-Net da:
; bei <2 GiB Output bleibt's Single-File-EXE, sonst auto-split in 1-2 .bin-
; Files je <2 GiB (jeder unter GitHub-Release-Asset-Limit).
DiskSpanning=yes
DiskSliceSize=2147483647
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
WizardImageFile={#BuildDir}\..\assets\wizard-side.bmp
WizardSmallImageFile={#BuildDir}\..\assets\wizard-small.bmp
WizardImageStretch=no
WizardImageBackColor=$1c1c1c
SetupIconFile={#BuildDir}\..\assets\icon-branded.ico
UninstallDisplayIcon={app}\assets\icon-branded.ico
UninstallDisplayName=Kira {#Version}
Uninstallable=yes

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Messages]
; Override the default Inno wording on the Welcome and Finished pages so the
; deutsche Version reflects Kira's first-run model-pull. %n is Inno's newline
; token; double-quotes in [Messages] strings would need escaping as "" but we
; stay in single-line clear text here.
WelcomeLabel1=Willkommen bei Kira v{#Version}
WelcomeLabel2=Diese Anwendung installiert Kira auf Deinem Computer.%n%nNach der Installation laedt Kira beim ersten Start ~10 GB Modelle (Whisper + Gemma) - Internet erforderlich. Das passiert nur einmal.%n%nKlicke auf "Weiter", um fortzufahren.

FinishedHeadingLabel=Kira wurde installiert.
FinishedLabel=Kira wurde erfolgreich installiert.%n%nBeim ersten Start oeffnet sich automatisch der Setup-Wizard fuer die Modelle.
ClickFinish=Klicke auf "Fertigstellen", um Kira zu starten.

[Tasks]
Name: "autostart"; Description: "Beim Windows-Start automatisch ausfuehren"; GroupDescription: "Zusaetzliche Optionen:"
Name: "desktopicon"; Description: "Desktop-Verknuepfung erstellen"; GroupDescription: "Zusaetzliche Optionen:"
Name: "startmenuicon"; Description: "Im Startmenue ablegen"; GroupDescription: "Zusaetzliche Optionen:"

[Files]
; Embedded Python 3.12 -- extracted to {app}\python at install time.
Source: "{#BuildDir}\python\*"; DestDir: "{app}\python"; Flags: recursesubdirs ignoreversion

; Kira source tree -- kept under {app}\app so venv stays separate.
Source: "{#BuildDir}\kira-source\*"; DestDir: "{app}\app"; Flags: recursesubdirs ignoreversion

; Wheels -- extracted to %TEMP% just for the pip-install step, then [InstallDelete] removes them.
Source: "{#BuildDir}\wheels\*.whl"; DestDir: "{tmp}\kira-wheels"; Flags: deleteafterinstall

; Static helper -- rcedit for icon-embed step.
Source: "{#BuildDir}\rcedit-x64.exe"; DestDir: "{app}\tools"; DestName: "rcedit-x64.exe"; Flags: ignoreversion

; OllamaSetup is run via [Run]. Slim-Bundle pulls the latest OllamaSetup.exe
; into installer\embedded\ via build_installer.ps1, so the source path is
; repo-local. Zwei DestDirs:
;  - {tmp} (deleteafterinstall) damit Inno's [Run]-Step die EXE findet
;  - {app}\app\installer\embedded permanent damit der First-Run-Wizard sie
;    spaeter erneut starten kann (Re-Install bei broken Ollama-Service,
;    etc.). _resource_path() in kira/main.py resolved relativ zu
;    Path(__file__).parent.parent = {app}\app\ — also muss die EXE auch
;    unter {app}\app\installer\embedded\ liegen, NICHT unter
;    {app}\installer\embedded\.
; OllamaSetup.exe DOPPELT deployed mit unterschiedlichem Lifecycle:
;  - {tmp}: fuer den Inno [Run]-Step (delete-after-install). Ein-Use.
;  - {app}\installer\embedded: persistent als Fallback fuer den First-
;    Run-Wizard. Wenn der User spaeter Ollama uninstalled (oder Service-
;    Crash) und Wizard-Re-Run, kann OllamaSetupWorker den lokalen Pfad
;    nutzen statt erneuten ~600 MB Online-Pull. Resolved via
;    kira/main.py:_resource_path() mit sys.executable-Bundle-Detection.
Source: "{#BuildDir}\..\installer\embedded\OllamaSetup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall
Source: "{#BuildDir}\..\installer\embedded\OllamaSetup.exe"; DestDir: "{app}\installer\embedded"; Flags: ignoreversion

; Asset fuer Inno's eigene Lnk-IconLocation + UninstallDisplayIcon. Der
; Python-Runtime-Code findet sein icon-branded.ico nicht hier sondern im
; Wheel (kira/_assets/icon-branded.ico via pyproject.toml force-include).
Source: "{#BuildDir}\..\assets\icon-branded.ico"; DestDir: "{app}\assets"; Flags: ignoreversion
Source: "{#BuildDir}\..\installer\config.yaml.template"; DestDir: "{tmp}"; Flags: deleteafterinstall

[Dirs]
Name: "{app}\tools"
Name: "{userappdata}\Kira"
; Note: %USERPROFILE%\.ollama\models and %USERPROFILE%\models\faster-whisper-*
; were here for the old fat-bundle robocopy steps. Slim bundle delegates that
; to the first-run setup wizard (kira/setup_wizard.py).

[InstallDelete]
; Embedded Python ohne venv (venv-Modul nicht in python embed-Distri).
; Kira wird direkt ins {app}\python\Lib\site-packages\ pip-installed,
; Entry-Points in {app}\python\Scripts\. Bei Update saubermachen damit
; alte Wheel-Reste nicht mit neuen kollidieren.
Type: filesandordirs; Name: "{app}\python\Lib\site-packages\kira"
Type: filesandordirs; Name: "{app}\python\Lib\site-packages\kira-*"
; Upgrade-Path v0.1.x -> v0.2.x: Slim-Installer schreibt nicht mehr in
; {app}\venv\, daher wuerde der ~500 MB-1 GB venv-Tree als Cruft
; ueberleben bis Full-Uninstall. Mindestens fuer 2 Releases entry
; behalten, damit alle v0.1.x-Updater sauber rueberkommen.
Type: filesandordirs; Name: "{app}\venv"
; Genauso obsolete Trees aus Phase F2-15..18 (assets unter {app}\app):
Type: filesandordirs; Name: "{app}\app\assets"
Type: filesandordirs; Name: "{app}\app\installer"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Icons]
Name: "{userdesktop}\Kira"; Filename: "{app}\python\Scripts\kira.exe"; \
    WorkingDir: "{app}"; IconFilename: "{app}\assets\icon-branded.ico"; \
    Tasks: desktopicon

Name: "{userprograms}\Kira"; Filename: "{app}\python\Scripts\kira.exe"; \
    WorkingDir: "{app}"; IconFilename: "{app}\assets\icon-branded.ico"; \
    Tasks: startmenuicon

Name: "{userstartup}\Kira"; Filename: "{app}\python\Scripts\kira.exe"; \
    WorkingDir: "{app}"; IconFilename: "{app}\assets\icon-branded.ico"; \
    Tasks: autostart

[Run]
; Phase F2-19: KEIN venv mehr. Embedded Python ohne `venv`-Modul →
; `python -m venv` failt mit "No module named venv", kira.exe wurde nie
; erstellt, Setup zeigte Code 2. Stattdessen embedded Python direkt als
; Kira-Runtime: pip install in {app}\python\Lib\site-packages\, Entry-
; Points landen in {app}\python\Scripts\.
;
; runhidden bewusst RAUS damit Errors im Setup-Window sichtbar sind.
;
; --no-build-isolation: pip nutzt embedded Python's site-packages fuer
; build-deps (hatchling ist da via build-pipeline). Defense gegen
; erneuten Drift falls eine sdist trotz Pre-built-Wheel reinkommt.
Filename: "{app}\python\python.exe"; \
    Parameters: "-m pip install --no-index --no-build-isolation --find-links ""{tmp}\kira-wheels"" --no-warn-script-location ""kira[windows]"""; \
    StatusMsg: "Installiere Kira-Python-Pakete..."; \
    Flags: waituntilterminated

; Step 5 -- Ollama silent install. /S is Inno-Setup-Standard for OllamaSetup.exe
; (a NSIS installer); /NORESTART skips the post-install reboot prompt. Skipped
; if Ollama is already on disk (NeedsOllama returns False).
Filename: "{tmp}\OllamaSetup.exe"; \
    Parameters: "/S /NORESTART"; \
    StatusMsg: "Installiere Ollama..."; \
    Flags: waituntilterminated; \
    Check: NeedsOllama

; Note: the old fat-bundle had robocopy steps here for the Gemma 3 12B model
; (~7 GB) and faster-whisper large-v3 (~3 GB). Slim bundle delegates both to
; kira/setup_wizard.py, which downloads them on first run via huggingface_hub
; + ollama pull.

; Step 9 -- embed icon into kira.exe / kira-once.exe via rcedit.
Filename: "{app}\tools\rcedit-x64.exe"; \
    Parameters: """{app}\python\Scripts\kira.exe"" --set-icon ""{app}\assets\icon-branded.ico"" --set-version-string ""FileDescription"" ""Kira voice-to-text"" --set-version-string ""ProductName"" ""Kira"" --set-version-string ""CompanyName"" ""Mike Pollow"" --set-version-string ""OriginalFilename"" ""kira.exe"""; \
    StatusMsg: "Bette Icon in kira.exe ein..."; \
    Flags: waituntilterminated

Filename: "{app}\tools\rcedit-x64.exe"; \
    Parameters: """{app}\python\Scripts\kira-once.exe"" --set-icon ""{app}\assets\icon-branded.ico"" --set-version-string ""FileDescription"" ""Kira CLI helper"" --set-version-string ""ProductName"" ""Kira"" --set-version-string ""CompanyName"" ""Mike Pollow"" --set-version-string ""OriginalFilename"" ""kira-once.exe"""; \
    StatusMsg: "Bette Icon in kira-once.exe ein..."; \
    Flags: waituntilterminated

; Step 11 -- config.yaml: write only if missing. Implemented in [Code] (Task 10).
; Step 12 -- Lnks via [Icons]; already handled.

; Final step -- start Kira (gated by the finish-page checkbox).
Filename: "{app}\python\Scripts\kira.exe"; \
    Description: "Kira jetzt starten"; \
    Flags: postinstall nowait skipifsilent

[Code]
function InitializeSetup: Boolean;
begin
  // F2-21: nvidia-smi-Pre-Check ENTFERNT.
  //
  // Inno's [Code] laeuft 32-bit auf x64-Win (vor Architectures-Switch).
  // Mehrere {sysnative}/{sys}/cmd-Quoting-Varianten verifiziert via
  // PowerShell und alle gepatcht -- der Pascal-Setup-Wizard hat trotzdem
  // konsistent "Keine NVIDIA-GPU"-MsgBox gezeigt. WOW64-Redirector +
  // CreateProcess-Argv-Quoting in 32-bit-Pascal ist ein bottomless rabbit
  // hole, der echten Wert haette: NULL. Selbst auf einer RTX 5090 sah
  // Mike den False-Negative.
  //
  // Ersatzstrategie: NVIDIA-Detection erfolgt zur Laufzeit waehrend des
  // First-Run-Wizards (kira/setup_wizard.py via faster-whisper-Loader,
  // der CUDA-DLLs probiert -- 100 % zuverlaessig weil im echten 64-bit-
  // Python-Prozess). User mit fehlender CUDA bekommt dort einen sauberen
  // Hinweis statt einer pre-Setup-MsgBox die false-negate-t.
  Result := True;
end;

function NeedsOllama: Boolean;
begin
  // F2-14: Ollama for Windows installs per-user into
  // %LOCALAPPDATA%\Programs\Ollama\. {localappdata} ist Inno's nativer
  // Constant fuer %LOCALAPPDATA% und robuster als der vorherige
  // {userappdata}\..\Local-Walk (der bei APPDATA-Junctions oder
  // OneDrive-Personal-Folders bricht).
  Result := not FileExists(ExpandConstant('{localappdata}\Programs\Ollama\ollama.exe'));
end;

procedure WriteConfigIfMissing();
var
  ConfigPath, TemplatePath: String;
  TemplateBytes: AnsiString;
  UnicodeText: String;
  Username: String;
begin
  ConfigPath := ExpandConstant('{userappdata}\Kira\config.yaml');
  if FileExists(ConfigPath) then
    Exit;

  TemplatePath := ExpandConstant('{tmp}\config.yaml.template');
  if not LoadStringFromFile(TemplatePath, TemplateBytes) then begin
    Log('config.yaml.template not found -- skipping config write');
    Exit;
  end;

  // The template ships as UTF-8. LoadStringFromFile gives us raw bytes in
  // an AnsiString; casting via String() would re-interpret them through
  // the system ANSI codepage (CP1252 on a German Windows, CP1250/CP437/...
  // elsewhere) and turn umlauts in initial_prompt into mojibake.
  // Decode UTF-8 explicitly, then re-encode UTF-8 on save so the result
  // is locale-independent and PyYAML's safe_load (UTF-8 default) reads it
  // cleanly on every machine. UTF8Decode is the Inno Setup name; the
  // free-pascal alias UTF8ToString does NOT exist in ISCC.
  UnicodeText := UTF8Decode(TemplateBytes);

  Username := ExpandConstant('{username}');
  StringChangeEx(UnicodeText, '${USERNAME}', Username, True);

  ForceDirectories(ExpandConstant('{userappdata}\Kira'));
  if not SaveStringToFile(ConfigPath, Utf8Encode(UnicodeText), False) then
    Log('failed to write ' + ConfigPath);
end;

procedure VerifyKiraExeOrError();
var
  KiraExe: String;
begin
  // F2-2: Pip-Install-Failure-Detector. Wenn die Pip-[Run]-Section silent
  // failed (z.B. weil hatchling fehlt → der naechste Start-Setup-Bug),
  // existiert kira.exe nicht und der User hat eine kaputte Installation
  // ohne klare Fehlermeldung. Frueh und laut crashen ist hier
  // die richtige Loesung.
  KiraExe := ExpandConstant('{app}\python\Scripts\kira.exe');
  if not FileExists(KiraExe) then begin
    MsgBox(
      'Setup-Fehler: kira.exe wurde nicht erstellt unter' + #13#10 +
      KiraExe + '.' + #13#10#13#10 +
      'Pip-Install ist vermutlich silent fehlgeschlagen.' + #13#10 +
      'Bitte das Setup-Log anhaengen, wenn du das Issue meldest:' + #13#10 +
      '  %TEMP%\Setup Log <DATUM>.txt' + #13#10#13#10 +
      'Issue-Tracker: https://github.com/MikeGT4/kira/issues',
      mbCriticalError, MB_OK);
  end;
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then begin
    WriteConfigIfMissing();
    VerifyKiraExeOrError();
  end;
end;
