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
ShowLanguageDialog=no
PrivilegesRequired=lowest
OutputDir=..\dist
OutputBaseFilename=JustDaySetup
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

[CustomMessages]
ru.Installing=JustDay ставится…
en.Installing=Installing JustDay…

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
; Потом вернуть панель задач: taskkill /F не даёт островку сделать это самому, а живой
; островок спрятал бы её снова за 2 с, и без этой строки
; человек оставался бы без панели задач и без дока.
Filename: "{app}\JustDay.exe"; Parameters: "taskbar-show"; Flags: runhidden waituntilterminated; RunOnceId: "TaskbarBack"
; Автозапуск включается из островка (manage._autostart_windows) — убираем его вместе с программой.
Filename: "{sys}\reg.exe"; Parameters: "delete HKCU\Software\Microsoft\Windows\CurrentVersion\Run /v JustDay /f"; Flags: runhidden; RunOnceId: "DropAutostart"

[Code]
// Вместо окна мастера — чёрная капсула сверху по центру, как сам островок, с тонкой дорожкой.
// Человек щёлкает по установщику и сразу видит «наше», а через несколько секунд на этом же месте
// появляется настоящий островок (шарик-маскот и знакомство). Окно — это всё ещё WizardForm Inno:
// у него только убраны рамка и содержимое, так что отмена, ошибки и откат работают как у Inno.
const
  SM_CXSCREEN = 0;

var
  Track, Fill: TPanel;

function GetSystemMetrics(nIndex: Integer): Integer;
  external 'GetSystemMetrics@user32.dll stdcall';
function CreateRoundRectRgn(x1, y1, x2, y2, w, h: Integer): LongWord;
  external 'CreateRoundRectRgn@gdi32.dll stdcall';
function SetWindowRgn(hWnd: HWND; hRgn: LongWord; bRedraw: BOOL): Integer;
  external 'SetWindowRgn@user32.dll stdcall';

procedure InitializeWizard;
var
  W, H, I: Integer;
  Dot: TPanel;
  Lbl: TNewStaticText;
begin
  W := ScaleX(340);
  H := ScaleY(44);
  for I := 0 to WizardForm.ControlCount - 1 do
    WizardForm.Controls[I].Visible := False;
  WizardForm.BorderStyle := bsNone;
  WizardForm.Color := clBlack;
  WizardForm.ClientWidth := W;
  WizardForm.ClientHeight := H;
  WizardForm.Position := poDesigned;
  WizardForm.Left := (GetSystemMetrics(SM_CXSCREEN) - W) div 2;
  WizardForm.Top := ScaleY(8);

  Dot := TPanel.Create(WizardForm);
  Dot.Parent := WizardForm;
  Dot.BevelOuter := bvNone;
  Dot.ParentBackground := False;
  Dot.Color := $00F0F0F0;
  Dot.SetBounds(ScaleX(18), (H - ScaleY(8)) div 2, ScaleX(8), ScaleY(8));

  Lbl := TNewStaticText.Create(WizardForm);
  Lbl.Parent := WizardForm;
  Lbl.Caption := CustomMessage('Installing');
  Lbl.Font.Color := clWhite;
  Lbl.Font.Size := 10;
  Lbl.Left := ScaleX(36);
  Lbl.Top := (H - Lbl.Height) div 2;

  Track := TPanel.Create(WizardForm);
  Track.Parent := WizardForm;
  Track.BevelOuter := bvNone;
  Track.ParentBackground := False;
  Track.Color := $00303030;
  Track.SetBounds(W - ScaleX(130), (H - ScaleY(4)) div 2, ScaleX(110), ScaleY(4));

  Fill := TPanel.Create(WizardForm);
  Fill.Parent := Track;
  Fill.BevelOuter := bvNone;
  Fill.ParentBackground := False;
  Fill.Color := $00FF8A0A;  // accentBlue островка (#0A84FF) в порядке BGR
  Fill.SetBounds(0, 0, 0, Track.Height);

  SetWindowRgn(WizardForm.Handle, CreateRoundRectRgn(0, 0, W + 1, H + 1, H, H), True);
end;

// Inno сам центрирует окно и заново показывает кнопки при каждой странице — возвращаем капсулу
// наверх, а кнопки уводим за её край (спрятанную через Visible кнопку Inno не нажимает). Страницу
// «Готово к установке» Inno показывает, даже выключенную, если до неё не было ни одной страницы
// (снимки CI 19 нояб.: капсула висела и ждала щелчка), поэтому её пропускаем и сами жмём «Далее».
const
  BM_CLICK = $00F5;

function ShouldSkipPage(PageID: Integer): Boolean;
begin
  Result := PageID = wpReady;
end;

procedure CurPageChanged(CurPageID: Integer);
begin
  WizardForm.NextButton.Left := -1000;
  WizardForm.BackButton.Left := -1000;
  WizardForm.CancelButton.Left := -1000;
  if CurPageID = wpReady then
    PostMessage(WizardForm.NextButton.Handle, BM_CLICK, 0, 0);
  WizardForm.Left := (GetSystemMetrics(SM_CXSCREEN) - WizardForm.Width) div 2;
  WizardForm.Top := ScaleY(8);
end;

procedure CurInstallProgressChanged(CurProgress, MaxProgress: Integer);
begin
  if MaxProgress > 0 then
    Fill.Width := Track.Width * CurProgress div MaxProgress;
end;

