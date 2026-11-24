; Inno Setup script - turns dist\FL Export Namer\ into one Setup.exe.
; build.bat runs this automatically if Inno Setup 6 is installed.

#ifndef AppVersion
  #define AppVersion "1.1.0"
#endif
#define AppName "FL Export Namer"
#define AppExe  "FL Export Namer.exe"

[Setup]
AppId={{7E3C2A51-4F0B-4D6E-9C1A-FE5E0A1B2C33}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Jay
DefaultDirName={localappdata}\Programs\{#AppName}
DefaultGroupName={#AppName}
DisableProgramGroupPage=yes
; Per-user install: no admin prompt needed.
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=FL Export Namer Setup {#AppVersion}
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

[Run]
Filename: "{app}\{#AppExe}"; Description: "Start the export watcher now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{sys}\taskkill.exe"; Parameters: "/f /im ""{#AppExe}"""; Flags: runhidden; RunOnceId: "KillApp"

[UninstallDelete]
; Settings/history in %APPDATA%\FL Export Namer are kept on purpose (reinstalls keep your setup).
