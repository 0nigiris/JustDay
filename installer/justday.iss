; Установщик JustDay для Windows (Inno Setup 6). Собирается в CI: .github/workflows/windows.yml.
; Ставится в профиль без прав администратора: другу не нужен пароль админа, а обновление поверх
; старой версии не требует UAC. Данные и ключи (Диспетчер учётных данных) при удалении остаются,
; чтобы переустановка не стирала знакомство и память.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{6F1E3C2A-8B7D-4C55-9E1F-4A2B7C9D0E31}
AppName=JustDay
AppVersion={#AppVersion}
AppPublisher=0nigiris
AppPublisherURL=https://github.com/0nigiris/JustDay
DefaultDirName={localappdata}\Programs\JustDay
DefaultGroupName=JustDay
; П31: установка не задаёт вопросов. Двойной щелчок — короткая полоска копирования, и сразу
; островок со знакомством (имя, ключи, место, автозапуск) с его анимациями. Серый мастер
; «Далее → Далее» был первым, что видел друг, и выглядел чужим.
DisableWelcomePage=yes
DisableDirPage=yes
DisableProgramGroupPage=yes
DisableReadyPage=yes
DisableFinishedPage=yes
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=JustDay-Setup-{#AppVersion}
SetupIconFile=..\brand\justday.ico
UninstallDisplayIcon={app}\JustDay.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Островок и демон — один и тот же JustDay.exe; без этого обновление упиралось бы в занятый файл.
CloseApplications=force
RestartApplications=no

[Languages]
Name: "ru"; MessagesFile: "compiler:Languages\Russian.isl"
Name: "en"; MessagesFile: "compiler:Default.isl"

[Files]
Source: "..\dist\JustDay\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\JustDay"; Filename: "{app}\JustDay.exe"
Name: "{group}\{cm:UninstallProgram,JustDay}"; Filename: "{uninstallexe}"
Name: "{userdesktop}\JustDay"; Filename: "{app}\JustDay.exe"

[Run]
Filename: "{app}\JustDay.exe"; Flags: nowait skipifsilent

[UninstallRun]
; Демон живёт в фоне без окна: не остановив его, удаление оставило бы занятые файлы.
Filename: "{sys}\taskkill.exe"; Parameters: "/F /T /IM JustDay.exe"; Flags: runhidden; RunOnceId: "StopJustDay"
; Автозапуск включается из островка (manage._autostart_windows) — убираем его вместе с программой.
Filename: "{sys}\reg.exe"; Parameters: "delete HKCU\Software\Microsoft\Windows\CurrentVersion\Run /v JustDay /f"; Flags: runhidden; RunOnceId: "DropAutostart"
