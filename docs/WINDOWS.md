# Порт на Windows: что мешает и чем заменить

Задача (пункт 45 плана): на Windows едет **только островок** вместе с Джарвисом. Дока, трея и меню
там не будет. Код порта пока не трогаем. Здесь опись того, что держит островок на Linux, и замена
для каждого куска, чтобы, когда начнём, не искать заново.

Опись снята 12 ноября 2026 с ветки `main`.

## Главная преграда: Quickshell

Quickshell работает только на Linux (Wayland) и, возможно, BSD. Официальной сборки под Windows нет.
Значит, островок нельзя «просто собрать» под Windows: ему нужен другой хозяин окна.

Что от Quickshell берёт островок (77 файлов QML):

| Импорт | Файлов | Что даёт | Замена на Windows |
| --- | --- | --- | --- |
| `Quickshell` | 52 | `ShellRoot`, `Variants`, `Process`, `Scope` | Чистый Qt Quick: `Window`, `Instantiator`; процессы через демон |
| `Quickshell.Wayland` | 18 | `PanelWindow`, слои, исключительные зоны | Безрамочное окно поверх всех: `Qt.FramelessWindowHint \| Qt.WindowStaysOnTopHint \| Qt.Tool` |
| `Quickshell.Services.Pipewire` | 12 | громкость, микшер, уровни | Демон через `pycaw` (WASAPI), островок получает числа по сокету |
| `Quickshell.Io` | 10 | `Socket`, `FileView`, `Process` | `QtNetwork` (`QTcpSocket`/`QLocalSocket`) или мост из Python |
| `Quickshell.Widgets` | 8 | `ClippingRectangle`, `IconImage` | `Rectangle` + `layer.effect` / `OpacityMask`, обычный `Image` |
| `Quickshell.Services.SystemTray` | 6 | значки лотка | Не нужно: трея на Windows нет |
| `Quickshell.Services.Mpris` | 2 | что играет, кнопки плеера | Демон через SMTC (`winrt` `GlobalSystemMediaTransportControlsSessionManager`) |
| `Quickshell.Services.Notifications` | 2 | свои уведомления | Не нужно на первом шаге: у Windows свои |
| `QtMultimedia`, `Qt.labs.folderlistmodel` | — | звук, списки файлов | Есть в Qt под Windows как есть |

Окна, которые держатся на `PanelWindow`/`WlrLayershell`: `shell.qml`, `OsdWindow.qml`,
`NotifToastWindow.qml`, `GenieWindow.qml`, `AppMenuWindow.qml`, `DockWindows.qml`,
`TrayWindows.qml`, `TrayView.qml`, `TrayMenuWindow.qml`. Для порта нужны только первые два
(островок и всплывашка громкости). Док, трей и меню остаются на Linux.

## Хозяин окна: два пути

1. **PySide6 + тот же QML.** Демон уже на Python, Qt для Python ставится одним `pip`. Окно
   островка открывает `QQmlApplicationEngine`, а то, что давал Quickshell (`Process`, `Socket`,
   громкость, плеер), отдаёт объект из Python через `setContextProperty`. Плюс: один процесс
   вместо двух, один установщик. Минус: QML придётся отвязать от `Quickshell.*` (см. таблицу).
2. **`qml.exe` / своё маленькое приложение на C++.** Быстрее старт, но второй язык и вторая
   сборка. Не берём, пока первый путь не упрётся.

Рекомендация: путь 1. Он же закрывает пункт 32 «уйти от Quickshell» и на Linux: один и тот же
хозяин окна на обеих системах, а Quickshell остаётся только для дока и трея.

Порядок отвязки: сначала в `JD.qml` спрятать всё платформенное за несколько свойств и функций
(`JD.volume`, `JD.player`, `JD.run(cmd)`), потом подменить их реализацию. Вьюхи островка
(`ExpandedView`, `PeekView`, `MixerView`) тогда не меняются.

## Связь островка с демоном

Сейчас: unix-сокет. `daemon.py:1108` — `asyncio.start_unix_server`, `JD.qml:1686` — путь из
`$JUSTDAY_SOCKET` или `$XDG_RUNTIME_DIR/justday.sock`. Так же устроены `media.py:982` и
`tts.py:272`.

На Windows `start_unix_server` в asyncio недоступен. Замена:

- **TCP только на `127.0.0.1`** (правило: наши порты наружу не смотрят) + одноразовый токен в
  файле профиля пользователя, который островок шлёт первой строкой. Без токена любой процесс
  машины мог бы командовать Джарвисом.
- Именованный канал (`\\.\pipe\justday`) — тоже вариант, он сам ограничен пользователем, но в
  asyncio на Windows он есть только у Proactor-цикла и неудобен в QML. Берём TCP.

Протокол (строки JSON) не меняется.

## Демон: Linux-утилиты, которые он зовёт

Число — сколько раз встречается в `src/justday/`.

| Утилита | Раз | Зачем | Windows |
| --- | --- | --- | --- |
| `systemctl`, `systemd-run`, `journalctl`, `loginctl` | 32, 7, 3, 6 | службы, перезапуск, журнал, сессия | Автозапуск через `HKCU\...\Run` или Планировщик; журнал в файл |
| `xdg-open`, `gio` | 10, 5 | открыть файл/ссылку | `os.startfile`, `webbrowser` |
| `wl-paste`, `wl-copy` | 10, 3 | буфер обмена | `win32clipboard` или Qt `QClipboard` |
| `secret-tool` | 7 | ключи | `keyring` (Credential Manager) |
| `notify-send` | 5 | уведомления | Тост Windows (`winrt` или `win11toast`) |
| `pactl`, `wpctl`, `pw-record`, `pw-play` | 4, 1, 1, 1 | звук, запись | `pycaw`, `sounddevice` |
| `qdbus`, `gdbus`, `busctl`, dbus в 8 модулях | 3, 1, 1 | KDE, окна, сессия | Нет аналога; каждое место решать отдельно или выключить |
| `kwriteconfig6` | 3 | настройки KDE | Не нужно |
| `ydotool`, `wtype` | 1, 1 | нажать клавиши | `pywinauto` / `SendInput` |
| `systemd-inhibit` | 1 | не спать | `SetThreadExecutionState` |
| `flatpak` | 1 | приложения | Не нужно |

Правило для порта: всё платформенное собрать в один модуль (`platform/linux.py` и
`platform/windows.py`) с одинаковыми функциями, а не разбрасывать `if sys.platform` по 30 файлам.

Модули с dbus (`aio`, `phone`, `session`, `notifications`, `desktop`, `watchers`, `server`,
`manage`) на первом шаге под Windows просто не грузятся: островок и Джарвис без них работают.

## Что едет на первом шаге, а что нет

Едет: островок (время, плеер, громкость, ответы Джарвиса, настройки), голос Джарвиса, роутер
моделей, вход в Claude из настроек.

Не едет: док, трей, меню «Пуск», Spotlight, режим сервера, телефон, управление окнами KDE.

## Установка

Пункт 31 «установка из островка» на Windows становится главным путём: человек ставит один
установщик (Python в комплекте), открывается островок, и всё необязательное (голос, модели) он
ставит оттуда. Набросок экрана установки показываем ему до кода (план, «Вместе»).

## Порядок, когда начнём

1. `JD.qml`: спрятать `Quickshell.*` за свойства `JD` (на Linux ничего не меняется, проверяем
   глазами и тестами).
2. Сокет: TCP на 127.0.0.1 с токеном рядом с unix-сокетом, на Linux остаётся unix.
3. `platform/` в демоне: буфер, открыть, ключи, звук, плеер, уведомления.
4. Хозяин окна на PySide6, сначала на Linux рядом с Quickshell.
5. Сборка под Windows и первый запуск на живой машине.
