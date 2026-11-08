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
AppId=Shinar.Desktop{code:ValidationSuffix}
UsePreviousLanguage=no
AppName=Shinar
AppVersion={#AppVersion}
AppPublisher=Shinar
DefaultDirName={localappdata}\Programs\Shinar
DefaultGroupName=Shinar
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir={#OutputDir}
OutputBaseFilename=Shinar-{#AppVersion}-windows-x64-setup
SetupIconFile={#SourceDir}\app-icon.ico
UninstallDisplayIcon={app}\Shinar.exe
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
Name: "{autoprograms}\Shinar"; Filename: "{app}\Shinar.exe"; WorkingDir: "{app}"; AppUserModelID: "Shinar.Desktop"; Check: not IsValidationInstall
Name: "{autodesktop}\Shinar"; Filename: "{app}\Shinar.exe"; WorkingDir: "{app}"; AppUserModelID: "Shinar.Desktop"; Tasks: desktopicon; Check: not IsValidationInstall

[Run]
Filename: "{app}\Shinar.exe"; Description: "{cm:LaunchShinar}"; Flags: nowait postinstall skipifsilent

[CustomMessages]
english.CreateDesktopShortcut=Create a desktop shortcut
english.LaunchShinar=Launch Shinar

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
