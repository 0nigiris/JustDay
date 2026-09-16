# JustDay

Голосовой ИИ-ассистент для Linux (KDE Plasma 6, Wayland). Нажимаешь кнопку на мыши, говоришь — и он делает: открывает приложения и сайты, управляет окнами, мышью и клавиатурой, ищет файлы, запускает игры и играет в них, читает и пишет почту, отвечает про календарь, раздаёт задачи Claude Code и проверяет их работу. Отвечает живым нейросетевым голосом, а сверху экрана живёт **Dynamic Island** с меню и настройками.

- **Любая модель.** Подписка Claude, локальная Ollama (бесплатно, ничего не уходит в сеть), OpenRouter, DeepSeek или свой адрес. Память, навыки и записная книжка общие для всех.
- **Учится.** Запоминает людей («Илья — тот, что в Польше, звонить через Discord»), привычки и места файлов; спрашивает, только когда не знает.
- **Приватно.** Речь, голос, мгновенные команды и почта обрабатываются только на вашем компьютере; телеметрия выключена.
- **Быстро.** Простые команды выполняются без ИИ за доли секунды; действия в окнах — пачками с точными метками кнопок.
- **Живой голос.** Qwen3-TTS на вашей видеокарте: встроенные «Джарвис» и «Пятница», голос по описанию или из записи.
- **Под ваш голос.** Как у Siri: минута контрольных фраз — и он узнаёт ваш тембр и темп, а чужие голоса может игнорировать.
- **Русский и English.** Интерфейс, голос и ответы на выбранном языке.

## Установка

```bash
curl -fsSL https://raw.githubusercontent.com/0nigiris/JustDay/main/install.sh | bash
```

Нужны KDE Plasma 6 на Wayland и PipeWire; видеокарта NVIDIA желательна (для живого голоса и локальной модели — обязательна). Установщик поставит всё сам и запустит **мастер настройки**: язык, имя, модель (поможет войти в Claude или ввести ключ), голос, микрофон, кнопку, почту и погоду.

## Как пользоваться

| Действие | |
|---|---|
| G6 на мыши / Meta+J | говорить (нажать или зажать) |
| двойное нажатие / Meta+Shift+J / «стоп» | отменить всё |
| навести курсор на верх экрана | время, погода, ближайшее событие, последний ответ |
| клик по острову → шестерёнка | меню и настройки |

```bash
justday ask "открой дискорд"     # текстом
justday setup                    # мастер настройки заново
justday doctor                   # проверка
justday update                   # обновиться (остров сам подскажет, когда есть новое)
justday logs -f                  # что он слышит и делает
```

📖 **[Полное руководство](docs/MANUAL.md)** — как устроено, что уходит в облако, модели, голос, память, почта и календарь, игры, безопасность, настройки, зависимости, решение проблем.
✅ **[Что умеет сейчас](CAPABILITIES.md)**

## English

JustDay is a voice AI assistant for Linux (KDE Plasma 6, Wayland). Press a mouse button or just say “Jarvis, …”, speak, and it acts: opens apps and sites, controls windows, mouse and keyboard, finds files, launches and plays games, reads and writes mail, answers about your calendar, delegates coding to Claude Code and reviews the result. It talks back in a neural voice and lives in a **Dynamic Island** at the top of the screen.

- **Any model:** Claude subscription, local Ollama (free, nothing leaves the computer), OpenRouter, DeepSeek or any Anthropic-compatible endpoint. Memory, skills and the address book are shared across models.
- **Private by design:** speech recognition, voice, instant commands, mail and calendar run locally; Claude Code telemetry is off; secrets live in the system keyring.
- **English UI and voice:** choose English in the setup wizard (or Settings → General).

```bash
curl -fsSL https://raw.githubusercontent.com/0nigiris/JustDay/main/install.sh | bash
```

The full manual is in Russian ([docs/MANUAL.md](docs/MANUAL.md)); the code, comments and commit history are in English.

## Лицензия

JustDay © 2026 [0nigiris](https://github.com/0nigiris). Распространяется по **GNU GPL v3 или новее** ([LICENSE](LICENSE)): код можно менять и распространять, но при этом нужно сохранять указание авторства и выпускать свои версии тоже с открытым исходным кодом под GPL.

Сторонние части: иконки [Lucide](https://lucide.dev) (ISC), встроенные голоса созданы моделью Qwen3-TTS (Apache 2.0).
