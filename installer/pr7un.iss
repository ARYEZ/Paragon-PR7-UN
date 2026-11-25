; Paragon PR7-UN installer (Inno Setup 6): uninstalls programs and their leftovers, the way Revo Uninstaller does.
;   iscc /DAppVersion=0.1.0 installer\pr7un.iss      (after pyinstaller pr7un.spec has made dist\PR7-UN)
;
; Per-user (no admin rights) into %LOCALAPPDATA%\Programs\PR7-UN, with a Start menu entry. Uninstalling programs for
; every user needs administrator rights: their uninstallers ask Windows, and PR7-UN can restart itself elevated.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
; AppId is permanent: it's how a new version finds and upgrades the installed one. Never change it.
AppId={{C4873B67-280D-4B07-AFB2-CB581298FE4F}
AppName=Paragon PR7-UN
AppVersion={#AppVersion}
AppVerName=Paragon PR7-UN {#AppVersion}
AppPublisher=Paragon
VersionInfoVersion={#AppVersion}
PrivilegesRequired=lowest
DefaultDirName={autopf}\PR7-UN
DefaultGroupName=Paragon PR7-UN
DisableProgramGroupPage=yes
UsePreviousAppDir=yes
UsePreviousTasks=yes
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
OutputDir=..\dist
OutputBaseFilename=PR7-UN-Setup-{#AppVersion}
SetupIconFile=..\pr7un\icons\app.ico
UninstallDisplayIcon={app}\PR7-UN.exe
UninstallDisplayName=Paragon PR7-UN
WizardStyle=modern
WizardImageFile=wizard-large-1x.bmp,wizard-large-2x.bmp
WizardSmallImageFile=wizard-small-1x.bmp,wizard-small-2x.bmp
Compression=lzma2/max
SolidCompression=yes
CloseApplications=yes
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "..\dist\PR7-UN\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "..\NOTICE.md"; DestDir: "{app}"; Flags: ignoreversion

[InstallDelete]
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{autoprograms}\Paragon PR7-UN"; Filename: "{app}\PR7-UN.exe"; Comment: "Uninstaller"
Name: "{autodesktop}\Paragon PR7-UN"; Filename: "{app}\PR7-UN.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\PR7-UN.exe"; Description: "{cm:LaunchProgram,Paragon PR7-UN}"; Flags: nowait postinstall skipifsilent
; Updates (Check for updates runs this installer with /SILENT /relaunch=1): start PR7-UN again when done.
Filename: "{app}\PR7-UN.exe"; Flags: nowait runasoriginaluser; Check: Relaunch

[Code]
// True only when the updater asked for it (/relaunch=1): normal and CI installs behave as before.
function Relaunch: Boolean;
begin
  Result := ExpandConstant('{param:relaunch|0}') = '1';
end;
