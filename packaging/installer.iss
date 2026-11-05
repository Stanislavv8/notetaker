; Установщик Notetaker (Inno Setup 6). Собирает scripts\build.py: ISCC /DVersion=1.0.0 /DSource=<папка сборки> installer.iss
; Ставится в профиль пользователя, права администратора не нужны.

#ifndef Version
  #define Version "0.0.0"
#endif

[Setup]
AppId={{6E4F7C2A-3B1D-4C8E-9A57-2F1E0D9B8C41}
AppName=Notetaker
AppVersion={#Version}
AppPublisher=Notetaker
AppPublisherURL=https://github.com/Stanislavv8/notetaker
DefaultDirName={localappdata}\Programs\Notetaker
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
OutputBaseFilename=Notetaker-{#Version}-setup
SetupIconFile=notetaker.ico
UninstallDisplayIcon={app}\Notetaker.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
LicenseFile=..\LICENSE

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"

[Tasks]
Name: "desktopicon"; Description: "Ярлык на рабочем столе"
Name: "startup"; Description: "Запускать при входе в Windows (рекомендуется: тогда звонки запишутся сами)"

[Files]
Source: "{#Source}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\Notetaker"; Filename: "{app}\Notetaker.exe"; AppUserModelID: "Notetaker.Desktop"
Name: "{userdesktop}\Notetaker"; Filename: "{app}\Notetaker.exe"; AppUserModelID: "Notetaker.Desktop"; Tasks: desktopicon
Name: "{userstartup}\Notetaker"; Filename: "{app}\Notetaker.exe"; Parameters: "--hidden"; AppUserModelID: "Notetaker.Desktop"; Tasks: startup

[Run]
Filename: "{app}\Notetaker.exe"; Description: "Запустить Notetaker"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{cmd}"; Parameters: "/C taskkill /IM Notetaker.exe /F"; Flags: runhidden; RunOnceId: "StopNotetaker"

[UninstallDelete]
Type: files; Name: "{userstartup}\Notetaker.lnk"
