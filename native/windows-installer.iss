#ifndef SourceRoot
  #error SourceRoot is required
#endif
[Setup]
AppId=ShasMaster.Reader
AppName=Shas Master
AppVersion=0.1.1
DefaultDirName={localappdata}\Programs\Shas Master
DefaultGroupName=Shas Master
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.19041
OutputDir={#SourceRoot}\release
#ifdef SignRelease
OutputBaseFilename=Shas-Master-Native-Windows-x64
#else
OutputBaseFilename=Shas-Master-Native-Windows-x64-unsigned
#endif
Compression=lzma2/ultra64
SolidCompression=yes
WizardStyle=modern
#ifdef SignRelease
SignTool=shasmaster
SignedUninstaller=yes
#endif
UninstallDisplayIcon={app}\ShasMaster.exe
CloseApplications=yes
RestartApplications=no
[Files]
Source: "{#SourceRoot}\.desktop-build\windows-launcher\ShasMaster.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceRoot}\.desktop-build\windows-launcher\ShasMaster.exe.config"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#SourceRoot}\.desktop-build\runtime\shas-backend\*"; DestDir: "{app}\shas-backend"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#SourceRoot}\data\prepared\*"; DestDir: "{app}\prepared"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "{#SourceRoot}\dist\*"; DestDir: "{app}\dist"; Flags: ignoreversion recursesubdirs createallsubdirs
[Icons]
Name: "{group}\Shas Master"; Filename: "{app}\ShasMaster.exe"
Name: "{autodesktop}\Shas Master"; Filename: "{app}\ShasMaster.exe"
[Run]
Filename: "{app}\ShasMaster.exe"; Description: "Open Shas Master"; Flags: nowait postinstall skipifsilent
; Personal data is in {localappdata}\Shas Master, outside {app}.
; Deliberately no deletion instruction for that folder, including on uninstall.
