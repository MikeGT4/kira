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
; Slim bundle (~1.5 GB): single-file Setup.exe, no .bin splits. Comfortably
; under GitHub's 2 GiB per-asset limit. The fat bundle (v0.1.0) needed
; OllamaSetup.exe (1.98 GB) + Embedded Python + Wheels = ~3.5 GB total —
; ueber GitHub-Release-Asset-Limit (2 GiB). DiskSpanning=yes mit 1.99 GiB
; Slices → Inno produziert 1 EXE + 1-2 .bin-Splits, alle unter 2 GiB.
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
Source: "{#BuildDir}\..\installer\embedded\OllamaSetup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall
Source: "{#BuildDir}\..\installer\embedded\OllamaSetup.exe"; DestDir: "{app}\app\installer\embedded"; Flags: ignoreversion

; Asset & config template. icon-branded.ico landet doppelt:
;  - {app}\assets fuer Inno's eigene Lnk-IconLocation + UninstallDisplayIcon
;  - {app}\app\assets damit der Code beim _resource_path-Lookup
;    (relative to kira/-Modul) das Icon findet (Phase E2 fixup #2 hinted).
Source: "{#BuildDir}\..\assets\icon-branded.ico"; DestDir: "{app}\assets"; Flags: ignoreversion
Source: "{#BuildDir}\..\assets\icon-branded.ico"; DestDir: "{app}\app\assets"; Flags: ignoreversion
Source: "{#BuildDir}\..\installer\config.yaml.template"; DestDir: "{tmp}"; Flags: deleteafterinstall

[Dirs]
Name: "{app}\venv"
Name: "{app}\tools"
Name: "{userappdata}\Kira"
; Note: %USERPROFILE%\.ollama\models and %USERPROFILE%\models\faster-whisper-*
; were here for the old fat-bundle robocopy steps. Slim bundle delegates that
; to the first-run setup wizard (kira/setup_wizard.py).

[InstallDelete]
Type: filesandordirs; Name: "{app}\venv"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Icons]
Name: "{userdesktop}\Kira"; Filename: "{app}\venv\Scripts\kira.exe"; \
    WorkingDir: "{app}"; IconFilename: "{app}\assets\icon-branded.ico"; \
    Tasks: desktopicon

Name: "{userprograms}\Kira"; Filename: "{app}\venv\Scripts\kira.exe"; \
    WorkingDir: "{app}"; IconFilename: "{app}\assets\icon-branded.ico"; \
    Tasks: startmenuicon

Name: "{userstartup}\Kira"; Filename: "{app}\venv\Scripts\kira.exe"; \
    WorkingDir: "{app}"; IconFilename: "{app}\assets\icon-branded.ico"; \
    Tasks: autostart

[Run]
; Step 1-4 -- bootstrap venv from embedded Python and bundled wheels.
; runhidden bewusst RAUS damit Errors im Setup-Window sichtbar sind. Vorher
; wurde der Pip-Install-Fail (hatchling fehlte) silent geschluckt und
; kira.exe kam nicht ans Ziel.
Filename: "{app}\python\python.exe"; \
    Parameters: "-m venv ""{app}\venv"""; \
    StatusMsg: "Erstelle virtuelle Python-Umgebung..."; \
    Flags: waituntilterminated

; F2-1: Statt {app}\app[windows] (PEP-517-Build aus Sdist) jetzt das
; vorgebaute Wheel via kira[windows]. --no-build-isolation erlaubt pip
; explizit nicht, einen Build-Backend zu requesten falls's doch eine Sdist
; greift. Defense gegen erneuten hatchling-Drift.
Filename: "{app}\venv\Scripts\python.exe"; \
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
    Parameters: """{app}\venv\Scripts\kira.exe"" --set-icon ""{app}\assets\icon-branded.ico"" --set-version-string ""FileDescription"" ""Kira voice-to-text"" --set-version-string ""ProductName"" ""Kira"" --set-version-string ""CompanyName"" ""Mike Pollow"" --set-version-string ""OriginalFilename"" ""kira.exe"""; \
    StatusMsg: "Bette Icon in kira.exe ein..."; \
    Flags: waituntilterminated

Filename: "{app}\tools\rcedit-x64.exe"; \
    Parameters: """{app}\venv\Scripts\kira-once.exe"" --set-icon ""{app}\assets\icon-branded.ico"" --set-version-string ""FileDescription"" ""Kira CLI helper"" --set-version-string ""ProductName"" ""Kira"" --set-version-string ""CompanyName"" ""Mike Pollow"" --set-version-string ""OriginalFilename"" ""kira-once.exe"""; \
    StatusMsg: "Bette Icon in kira-once.exe ein..."; \
    Flags: waituntilterminated

; Step 11 -- config.yaml: write only if missing. Implemented in [Code] (Task 10).
; Step 12 -- Lnks via [Icons]; already handled.

; Final step -- start Kira (gated by the finish-page checkbox).
Filename: "{app}\venv\Scripts\kira.exe"; \
    Description: "Kira jetzt starten"; \
    Flags: postinstall nowait skipifsilent

[Code]
function InitializeSetup: Boolean;
var
  ResultCode: Integer;
  TempFile, TrimmedText, NvidiaSmi, CmdExe: String;
  FileTextA: AnsiString;
  GpuMem: Integer;
  ExecOk: Boolean;
begin
  Result := True;
  TempFile := ExpandConstant('{tmp}\nvidia-smi.txt');
  ForceDirectories(ExpandConstant('{tmp}'));

  // F2-5: PATH-Hijack-Fix. Vorher 'cmd.exe' ohne Pfad → der erste cmd.exe
  // im PATH wird ausgefuehrt; ein Angreifer mit einer eigenen cmd.exe im
  // %DOWNLOADS% (also dem Folder, in dem das Setup-Exe oft liegt) kriegt
  // RCE noch BEVOR der User klickt. Genauso bei nvidia-smi: ohne
  // absoluten Pfad triggert man jeden nvidia-smi.exe-Trojan im PATH.
  // Loesung: cmd.exe aus {sys} (System32) + nvidia-smi mit absolutem
  // {win}\System32-Pfad. Output-Redirect via cmd ist nur OK weil der
  // cmd-Pfad jetzt auch fix ist.
  CmdExe := ExpandConstant('{sys}\cmd.exe');
  // Inno's InitializeSetup laeuft IMMER 32-bit (vor ArchitecturesInstallIn64BitMode-Switch).
  // Auf x64-Win redirected dann {win}\System32 via WOW64-Filesystem-Redirector zu
  // SysWOW64, wo nvidia-smi.exe NICHT liegt (es ist 64-bit-only in System32).
  // {sysnative} ist Inno's Magic-Constant fuer den NICHT-redirected System32-Pfad.
  NvidiaSmi := ExpandConstant('{sysnative}\nvidia-smi.exe');
  if not FileExists(NvidiaSmi) then
    NvidiaSmi := ExpandConstant('{win}\System32\nvidia-smi.exe');
  if not FileExists(NvidiaSmi) then
    NvidiaSmi := ExpandConstant('{sys}\nvidia-smi.exe');

  if not FileExists(NvidiaSmi) then begin
    Result := MsgBox(
      'Keine NVIDIA-Treiber-Tools (nvidia-smi.exe) auf dieser Box gefunden.' + #13#10 +
      'Kira braucht CUDA fuer sinnvolle Performance.' + #13#10#13#10 +
      'Trotzdem installieren?',
      mbConfirmation, MB_YESNO) = IDYES;
    exit;
  end;

  ExecOk := Exec(CmdExe,
    '/c "' + NvidiaSmi + '" --query-gpu=memory.total --format=csv,noheader,nounits > "' + TempFile + '" 2>NUL',
    '', SW_HIDE, ewWaitUntilTerminated, ResultCode);

  if ExecOk and (ResultCode = 0) and LoadStringFromFile(TempFile, FileTextA) then begin
    TrimmedText := Trim(String(FileTextA));
    GpuMem := StrToIntDef(TrimmedText, 0);
    if GpuMem < 10240 then begin
      Result := MsgBox(
        'Dieses Bundle ist fuer NVIDIA-GPUs ab 12 GB VRAM optimiert.' + #13#10 +
        'Auf deiner Hardware sind nur ' + IntToStr(GpuMem) + ' MB verfuegbar.' + #13#10 +
        'Die Performance wird stark eingeschraenkt sein.' + #13#10#13#10 +
        'Trotzdem installieren?',
        mbConfirmation, MB_YESNO) = IDYES;
    end;
  end else begin
    Result := MsgBox(
      'Keine NVIDIA-GPU mit nvidia-smi gefunden.' + #13#10 +
      'Kira braucht CUDA fuer sinnvolle Performance.' + #13#10#13#10 +
      'Trotzdem installieren?',
      mbConfirmation, MB_YESNO) = IDYES;
  end;
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
  KiraExe := ExpandConstant('{app}\venv\Scripts\kira.exe');
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
