#ifndef AppVersion
  #error AppVersion is required
#endif
#ifndef SourceDir
  #error SourceDir is required
#endif
#ifndef OutputDir
  #error OutputDir is required
#endif

[Setup]
AppId=LinguaLoop.Desktop{code:ValidationSuffix}
UsePreviousLanguage=no
AppName=LinguaLoop
AppVersion={#AppVersion}
AppPublisher=LinguaLoop
DefaultDirName={localappdata}\Programs\LinguaLoop
DefaultGroupName=LinguaLoop
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir={#OutputDir}
OutputBaseFilename=LinguaLoop-{#AppVersion}-windows-x64-setup
SetupIconFile={#SourceDir}\app-icon.ico
UninstallDisplayIcon={app}\LinguaLoop.exe
Compression=lzma2/normal
SolidCompression=yes
WizardStyle=modern
CloseApplications=no
RestartApplications=no
SetupLogging=yes

[Languages]
Name: "chinesesimp"; MessagesFile: "compiler:Default.isl,ChineseSimplified.isl"
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopShortcut}"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\LinguaLoop"; Filename: "{app}\LinguaLoop.exe"; WorkingDir: "{app}"; AppUserModelID: "LinguaLoop.Desktop"; Check: not IsValidationInstall
Name: "{autodesktop}\LinguaLoop"; Filename: "{app}\LinguaLoop.exe"; WorkingDir: "{app}"; AppUserModelID: "LinguaLoop.Desktop"; Tasks: desktopicon; Check: not IsValidationInstall

[Run]
Filename: "{app}\LinguaLoop.exe"; Description: "{cm:LaunchLinguaLoop}"; Flags: nowait postinstall skipifsilent

[CustomMessages]
english.CreateDesktopShortcut=Create a desktop shortcut
english.LaunchLinguaLoop=Launch LinguaLoop

[Code]
function IsValidationInstall: Boolean;
begin
  Result := ExpandConstant('{param:VALIDATE|0}') = '1';
end;

function ValidationSuffix(Param: String): String;
begin
  if IsValidationInstall then
    Result := '.Validation'
  else
    Result := '';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
  ExitCode: Integer;
begin
  if CurStep = ssPostInstall then begin
    { Copy succeeds before cleanup. Never remove a whole runtime or a user directory. }
    if not Exec(ExpandConstant('{app}\runtime\python.exe'),
      ExpandConstant('-I -B "{app}\cleanup_runtime.py" "{app}"'),
      ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ExitCode) then
      Log('Runtime cleanup could not start')
    else
      Log('Runtime cleanup exit code: ' + IntToStr(ExitCode));
  end;
end;
