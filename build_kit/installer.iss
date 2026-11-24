; Inno Setup script - turns dist\DAW Export Fixer\ into one Setup.exe.
; build.bat runs this automatically if Inno Setup 6 is installed.

#ifndef AppVersion
  #define AppVersion "1.1.0"
#endif
#define AppName "DAW Export Fixer"
#define AppExe  "DAW Export Fixer.exe"
; Before 1.5.0 the app was called FL Export Namer. Same AppId, so Setup upgrades that install.
#define OldName "FL Export Namer"

[Setup]
AppId={{7E3C2A51-4F0B-4D6E-9C1A-FE5E0A1B2C33}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Jay
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Install under the new name even when upgrading an FL Export Namer install (the old folder is removed below).
UsePreviousAppDir=no
UsePreviousGroup=no
; Per-user install: no admin prompt needed.
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=DAW Export Fixer Setup {#AppVersion}
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "startup"; Description: "Start the export watcher with Windows (recommended)"; GroupDescription: "Options:"
Name: "sorterdesktop"; Description: "Beat Sorter shortcut on the desktop (drop old beats onto it)"; GroupDescription: "Options:"

[InstallDelete]
; Leftovers of the FL Export Namer install (the old app is closed first, see [Code]).
Type: filesandordirs; Name: "{localappdata}\Programs\{#OldName}"
Type: filesandordirs; Name: "{userprograms}\{#OldName}"

[Files]
Source: "..\dist\{#AppName}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\{#AppName}"; Filename: "{app}\{#AppExe}"
Name: "{group}\Beat Sorter"; Filename: "{app}\{#AppExe}"; Parameters: "--sorter"
Name: "{group}\Uninstall {#AppName}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\Beat Sorter"; Filename: "{app}\{#AppExe}"; Parameters: "--sorter"; Tasks: sorterdesktop

[Registry]
; Same value the app's own "Start with Windows" toggle uses.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "{#AppName}"; ValueData: """{app}\{#AppExe}"""; Flags: uninsdeletevalue; Tasks: startup
; The old name's startup entry points at an exe that no longer exists.
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: none; ValueName: "{#OldName}"; Flags: deletevalue

[Run]
Filename: "{app}\{#AppExe}"; Description: "Start the export watcher now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/f /im ""{#AppExe}"""; Flags: runhidden; RunOnceId: "KillApp"

[UninstallDelete]
; Settings/history in %APPDATA%\DAW Export Fixer are kept on purpose (reinstalls keep your setup).

[Code]
// Close a running FL Export Namer (pre-1.5.0) so its folder can be removed.
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  RC: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/f /im "{#OldName}.exe"', '', SW_HIDE, ewWaitUntilTerminated, RC);
  Result := '';
end;
