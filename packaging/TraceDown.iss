; TraceDown Windows installer (Inno Setup).
;
; Wraps the PyInstaller output folder (dist\TraceDown\) into a single
; TraceDown-Windows-Setup.exe. Installing (rather than unzipping) is what
; clears the "downloaded from the internet" Mark-of-the-Web flag, so the
; bundled pythonnet Python.Runtime.dll loads instead of being blocked.
;
; Per-user install (PrivilegesRequired=lowest): no admin password, no UAC
; prompt. Installs into the user's own AppData\Local\Programs\TraceDown.
;
; CI passes the version:  ISCC /DMyAppVersion=1.3.11 packaging\TraceDown.iss
; Paths are relative to this script's directory (packaging\).

#ifndef MyAppVersion
  #define MyAppVersion "0.0.0"
#endif

#define MyAppName "TraceDown"
#define MyAppExeName "TraceDown.exe"
#define MyAppPublisher "TraceDown"

[Setup]
; AppId uniquely identifies the app for upgrades/uninstall. Never change it.
AppId={{B7E4B0F2-3C9A-4E7D-9A1E-2F6C8D5A4B10}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..
OutputBaseFilename=TraceDown-Windows-Setup
SetupIconFile=..\assets\icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"

[Files]
Source: "..\dist\TraceDown\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
; Shortcuts are named "TraceDown" and draw their icon from the exe, which
; PyInstaller embeds from assets\icon.ico — the same file as SetupIconFile,
; so the shortcut icon matches the installer icon. IconFilename is explicit
; so this stays true regardless of shell icon caching.
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
; An in-app update runs this installer with /SILENT (no wizard, so no "launch"
; tick-box): reopen the app automatically once the new version is in place.
Filename: "{app}\{#MyAppExeName}"; Flags: nowait skipifnotsilent

[Code]
// Upgrading over a running copy fails with "DeleteFile failed; code 5/32"
// because Windows locks TraceDown.exe and _internal\ while they are in use.
// The scheduled background run (TraceDown.exe --run) has no window, so the
// user can't see or close it and Setup's own close-applications prompt can't
// either. Stop every running copy (and its ffmpeg/browser children) first.
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Exec(ExpandConstant('{sys}\taskkill.exe'), '/F /T /IM {#MyAppExeName}', '',
       SW_HIDE, ewWaitUntilTerminated, ResultCode);
  // Give Windows a moment to release the file handles.
  Sleep(500);
  Result := '';
end;
