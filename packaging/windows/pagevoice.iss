; Inno Setup script for the Windows installer (SPEC §9). Wraps the PyInstaller
; one-folder build in dist\PageVoice\ into PageVoice-<version>-setup.exe.
;
;   iscc /DAppVersion=1.0.0 packaging\windows\pagevoice.iss
;
; Installs per user by default (no administrator prompt); "Install for all users" is
; offered in a dialog. The voice model, render cache, saved reviews and pronunciation
; lists live in the user's own folders and are never removed by the uninstaller.

#ifndef AppVersion
  #define AppVersion "0.0.0-dev"
#endif
#define Root "..\.."

[Setup]
; Never change AppId: Windows uses it to find the installed copy for upgrades.
AppId={{B6E1C3A2-5D7F-4E8B-9A41-7C2D90F3E615}
AppName=PageVoice
AppVersion={#AppVersion}
AppVerName=PageVoice {#AppVersion}
AppPublisher=N-Shovel
AppPublisherURL=https://github.com/N-Shovel/pagevoice
AppSupportURL=https://github.com/N-Shovel/pagevoice/issues
DefaultDirName={autopf}\PageVoice
DefaultGroupName=PageVoice
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0
LicenseFile={#Root}\LICENSE
OutputDir={#Root}\dist
OutputBaseFilename=PageVoice-{#AppVersion}-setup
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
UninstallDisplayIcon={app}\PageVoice.exe
SetupIconFile={#Root}\packaging\icons\pagevoice.ico
UninstallDisplayName=PageVoice

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#Root}\dist\PageVoice\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[InstallDelete]
; An upgrade replaces the program files completely, so an older version's libraries can't
; linger next to the new ones. User data lives elsewhere and is untouched.
Type: filesandordirs; Name: "{app}\_internal"

[Icons]
Name: "{group}\PageVoice"; Filename: "{app}\PageVoice.exe"
Name: "{group}\Uninstall PageVoice"; Filename: "{uninstallexe}"
Name: "{autodesktop}\PageVoice"; Filename: "{app}\PageVoice.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\PageVoice.exe"; Description: "{cm:LaunchProgram,PageVoice}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Only what the installer itself put in {app} (Python's bytecode caches).
Type: filesandordirs; Name: "{app}\_internal\__pycache__"
