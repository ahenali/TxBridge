; Inno Setup script.  Build with:   iscc /DAppVersion=1.1.0 packaging\installer.iss
; Run from the repository root after `pyinstaller packaging/TxBridge.spec`.
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{B3C8E3E5-4099-4854-9D74-35678484EEAA}
AppName=TxBridge
AppVersion={#AppVersion}
AppPublisher=TxBridge
DefaultDirName={autopf}\TxBridge
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\dist
OutputBaseFilename=TxBridge-Setup-{#AppVersion}
SetupIconFile=TxBridge.ico
UninstallDisplayIcon={app}\TxBridge.exe
Compression=lzma2
SolidCompression=yes
WizardStyle=modern

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "..\dist\TxBridge\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\TxBridge"; Filename: "{app}\TxBridge.exe"
Name: "{autodesktop}\TxBridge"; Filename: "{app}\TxBridge.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\TxBridge.exe"; Description: "Start TxBridge"; Flags: nowait postinstall skipifsilent
