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

[Registry]
; «Открыть с помощью → Notetaker» для аудио и видео: файл уйдёт на расшифровку
Root: HKCU; Subkey: "Software\Classes\Applications\Notetaker.exe"; ValueType: string; ValueName: "FriendlyAppName"; ValueData: "Notetaker — расшифровать"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\Applications\Notetaker.exe\shell\open\command"; ValueType: string; ValueName: ""; ValueData: """{app}\Notetaker.exe"" ""%1"""
Root: HKCU; Subkey: "Software\Classes\Applications\Notetaker.exe\SupportedTypes"; ValueType: string; ValueName: ".m4a"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\Applications\Notetaker.exe\SupportedTypes"; ValueType: string; ValueName: ".mp3"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\Applications\Notetaker.exe\SupportedTypes"; ValueType: string; ValueName: ".wav"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\Applications\Notetaker.exe\SupportedTypes"; ValueType: string; ValueName: ".ogg"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\Applications\Notetaker.exe\SupportedTypes"; ValueType: string; ValueName: ".opus"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\Applications\Notetaker.exe\SupportedTypes"; ValueType: string; ValueName: ".oga"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\Applications\Notetaker.exe\SupportedTypes"; ValueType: string; ValueName: ".flac"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\Applications\Notetaker.exe\SupportedTypes"; ValueType: string; ValueName: ".aac"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\Applications\Notetaker.exe\SupportedTypes"; ValueType: string; ValueName: ".wma"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\Applications\Notetaker.exe\SupportedTypes"; ValueType: string; ValueName: ".amr"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\Applications\Notetaker.exe\SupportedTypes"; ValueType: string; ValueName: ".3gp"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\Applications\Notetaker.exe\SupportedTypes"; ValueType: string; ValueName: ".mp4"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\Applications\Notetaker.exe\SupportedTypes"; ValueType: string; ValueName: ".mov"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\Applications\Notetaker.exe\SupportedTypes"; ValueType: string; ValueName: ".mkv"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\Applications\Notetaker.exe\SupportedTypes"; ValueType: string; ValueName: ".webm"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\Applications\Notetaker.exe\SupportedTypes"; ValueType: string; ValueName: ".avi"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\Applications\Notetaker.exe\SupportedTypes"; ValueType: string; ValueName: ".wmv"; ValueData: ""
Root: HKCU; Subkey: "Software\Classes\.m4a\OpenWithList\Notetaker.exe"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\.mp3\OpenWithList\Notetaker.exe"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\.wav\OpenWithList\Notetaker.exe"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\.ogg\OpenWithList\Notetaker.exe"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\.opus\OpenWithList\Notetaker.exe"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\.oga\OpenWithList\Notetaker.exe"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\.flac\OpenWithList\Notetaker.exe"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\.aac\OpenWithList\Notetaker.exe"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\.wma\OpenWithList\Notetaker.exe"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\.amr\OpenWithList\Notetaker.exe"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\.3gp\OpenWithList\Notetaker.exe"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\.mp4\OpenWithList\Notetaker.exe"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\.mov\OpenWithList\Notetaker.exe"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\.mkv\OpenWithList\Notetaker.exe"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\.webm\OpenWithList\Notetaker.exe"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\.avi\OpenWithList\Notetaker.exe"; Flags: uninsdeletekey
Root: HKCU; Subkey: "Software\Classes\.wmv\OpenWithList\Notetaker.exe"; Flags: uninsdeletekey

[Run]
Filename: "{app}\Notetaker.exe"; Description: "Запустить Notetaker"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{cmd}"; Parameters: "/C taskkill /IM Notetaker.exe /F"; Flags: runhidden; RunOnceId: "StopNotetaker"

[UninstallDelete]
Type: files; Name: "{userstartup}\Notetaker.lnk"
