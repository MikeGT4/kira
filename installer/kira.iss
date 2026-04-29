; Kira Windows installer -- Inno Setup script.
; Compile via:
;   iscc /DVersion=0.1.0 /DBuildDir=<abs> /DOutputDir=<abs> installer/kira.iss
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
DiskSpanning=yes
DiskSliceSize=2147483647
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
WizardStyle=modern
SetupIconFile={#BuildDir}\..\assets\icon.ico
UninstallDisplayIcon={app}\assets\icon.ico
UninstallDisplayName=Kira {#Version}
Uninstallable=yes

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

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

; OllamaSetup is run via [Run] -- keep it in tmp.
Source: "{#BuildDir}\OllamaSetup.exe"; DestDir: "{tmp}"; Flags: deleteafterinstall

; Whisper model -- copied via [Run] robocopy into %USERPROFILE%, NOT {app}.
Source: "{#BuildDir}\whisper\*"; DestDir: "{tmp}\kira-whisper"; Flags: recursesubdirs deleteafterinstall

; Ollama storage (gemma3:12b manifests + blobs).
Source: "{#BuildDir}\ollama-models\*"; DestDir: "{tmp}\kira-ollama-models"; Flags: recursesubdirs deleteafterinstall

; Asset & config template.
Source: "{#BuildDir}\..\assets\icon.ico"; DestDir: "{app}\assets"; Flags: ignoreversion
Source: "{#BuildDir}\..\installer\config.yaml.template"; DestDir: "{tmp}"; Flags: deleteafterinstall

[Dirs]
Name: "{app}\venv"
Name: "{app}\tools"
Name: "{userappdata}\Kira"
Name: "{%USERPROFILE}\.ollama\models"
Name: "{%USERPROFILE}\models\faster-whisper-large-v3"

[InstallDelete]
Type: filesandordirs; Name: "{app}\venv"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Icons]
Name: "{userdesktop}\Kira"; Filename: "{app}\venv\Scripts\kira.exe"; \
    WorkingDir: "{app}"; IconFilename: "{app}\assets\icon.ico"; \
    Tasks: desktopicon

Name: "{userprograms}\Kira"; Filename: "{app}\venv\Scripts\kira.exe"; \
    WorkingDir: "{app}"; IconFilename: "{app}\assets\icon.ico"; \
    Tasks: startmenuicon

Name: "{userstartup}\Kira"; Filename: "{app}\venv\Scripts\kira.exe"; \
    WorkingDir: "{app}"; IconFilename: "{app}\assets\icon.ico"; \
    Tasks: autostart

[Run]
; Step 1-4 -- bootstrap venv from embedded Python and bundled wheels.
Filename: "{app}\python\python.exe"; \
    Parameters: "-m venv ""{app}\venv"""; \
    StatusMsg: "Erstelle virtuelle Python-Umgebung..."; \
    Flags: runhidden waituntilterminated

Filename: "{app}\venv\Scripts\python.exe"; \
    Parameters: "-m pip install --no-index --find-links ""{tmp}\kira-wheels"" --no-warn-script-location ""{app}\app[windows]"""; \
    StatusMsg: "Installiere Kira-Python-Pakete..."; \
    Flags: runhidden waituntilterminated

; Step 5 -- Ollama silent install. /SILENT skips the wizard; OllamaSetup ships a
; service installer that registers itself on boot.
Filename: "{tmp}\OllamaSetup.exe"; \
    Parameters: "/SILENT /NORESTART"; \
    StatusMsg: "Installiere Ollama..."; \
    Flags: waituntilterminated; \
    Check: NeedsOllamaInstall

; Step 6 -- wait for Ollama service is implemented in [Code] (Task 10) via
; CurStepChanged; not a [Run] entry.

; Step 7 -- copy Ollama model storage. Robocopy keeps perms friendly.
Filename: "robocopy.exe"; \
    Parameters: """{tmp}\kira-ollama-models"" ""{%USERPROFILE}\.ollama\models"" /E /NFL /NDL /NJH /NJS /NP"; \
    StatusMsg: "Kopiere Sprachmodell (Gemma 3 12B, ca. 7 GB)..."; \
    Flags: runhidden; \
    Check: NeedsOllamaModelsCopy

; Step 8 -- copy faster-whisper model.
Filename: "robocopy.exe"; \
    Parameters: """{tmp}\kira-whisper"" ""{%USERPROFILE}\models\faster-whisper-large-v3"" /E /NFL /NDL /NJH /NJS /NP"; \
    StatusMsg: "Kopiere Whisper-Modell (large-v3, ca. 3 GB)..."; \
    Flags: runhidden; \
    Check: NeedsWhisperModelCopy

; Step 9 -- embed icon into kira.exe / kira-once.exe via rcedit.
Filename: "{app}\tools\rcedit-x64.exe"; \
    Parameters: """{app}\venv\Scripts\kira.exe"" --set-icon ""{app}\assets\icon.ico"" --set-version-string ""FileDescription"" ""Kira voice-to-text"" --set-version-string ""ProductName"" ""Kira"" --set-version-string ""CompanyName"" ""Mike Pollow"" --set-version-string ""OriginalFilename"" ""kira.exe"""; \
    StatusMsg: "Bette Icon in kira.exe ein..."; \
    Flags: runhidden waituntilterminated

Filename: "{app}\tools\rcedit-x64.exe"; \
    Parameters: """{app}\venv\Scripts\kira-once.exe"" --set-icon ""{app}\assets\icon.ico"" --set-version-string ""FileDescription"" ""Kira CLI helper"" --set-version-string ""ProductName"" ""Kira"" --set-version-string ""CompanyName"" ""Mike Pollow"" --set-version-string ""OriginalFilename"" ""kira-once.exe"""; \
    StatusMsg: "Bette Icon in kira-once.exe ein..."; \
    Flags: runhidden waituntilterminated

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
  TempFile, TrimmedText: String;
  FileTextA: AnsiString;
  GpuMem: Integer;
  ExecOk: Boolean;
begin
  Result := True;
  TempFile := ExpandConstant('{tmp}\nvidia-smi.txt');
  ForceDirectories(ExpandConstant('{tmp}'));

  ExecOk := Exec('cmd.exe',
    '/c "nvidia-smi --query-gpu=memory.total --format=csv,noheader,nounits > """ + TempFile + """ 2>NUL"',
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

function NeedsOllamaInstall: Boolean;
begin
  // Ollama for Windows installs per-user into %LOCALAPPDATA%\Programs\Ollama\.
  // {userpf} maps to that directory. Skip the install step if present.
  Result := not FileExists(ExpandConstant('{userpf}\Ollama\ollama.exe'));
end;

function NeedsWhisperModelCopy: Boolean;
var
  ModelBin: String;
begin
  // Skip the 3 GB copy if the model.bin already exists at the target.
  ModelBin := ExpandConstant('{%USERPROFILE}\models\faster-whisper-large-v3\model.bin');
  Result := not FileExists(ModelBin);
end;

function NeedsOllamaModelsCopy: Boolean;
var
  ManifestDir: String;
begin
  // Skip the 7 GB copy if the gemma3:12b manifest is already present.
  ManifestDir := ExpandConstant('{%USERPROFILE}\.ollama\models\manifests\registry.ollama.ai\library\gemma3\12b');
  Result := not FileExists(ManifestDir);
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

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if CurStep = ssPostInstall then
    WriteConfigIfMissing();
end;
