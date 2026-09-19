"""User-facing phrases of the backend (spoken lines, island details, notifications) in the chosen language.

Source strings are Russian; `t("…", name=value)` returns the translation for `[user] language = "en"` and fills
`{placeholders}`. Messages meant only for the brain stay Russian — the model understands any language.
"""
from __future__ import annotations

from . import config

EN = {
    # daemon
    "Клод взялся за задачу": "Claude took on the task",
    "Почта недоступна": "Mail unavailable",
    "Ошибка мозга": "Brain error",
    "Голос не узнан": "Voice not recognized",
    "Не получилось открыть календарь.": "Couldn't open the calendar.",
    "Слишком тихо — говорите ближе к микрофону": "Too quiet — speak closer to the microphone",
    "Почта · локально": "Mail · local",
    "Локальная модель для почты не отвечает.": "The local mail model is not responding.",
    "Отменено": "Cancelled",
    "картинка": "picture", "видео": "video", "звук": "audio", "озвучка": "voice-over", "3D-модель": "3D model",
    "субтитры": "subtitles",
    "Не получилось связаться с мозгом. Подробности в логе.": "Couldn't reach the brain. Details are in the log.",
    "Нужно подтверждение. Разрешить?": "Confirmation needed. Allow?",
    "{to}: «{text}». Отправить?": "{to}: “{text}”. Send it?",
    "{a} или {b}?": "{a} or {b}?",
    "Разрешить": "Allow",
    "Отклонить": "Deny",
    "JustDay просит подтверждение": "JustDay needs confirmation",
    "Сказать, о чём?": "Shall I tell you what it's about?",
    # tool labels on the island
    "Смотрю на экран": "Looking at the screen",
    "Печатаю «{text}»": "Typing “{text}”",
    "Перетаскиваю": "Dragging",
    "Нажимаю в окне": "Clicking in the window",
    "Нажимаю клавиши": "Pressing keys",
    "Действую в окне": "Working in the window",
    "Браузер: {what}": "Browser: {what}",
    "Смотрю, какие окна открыты": "Checking open windows",
    "Переключаю окно": "Switching windows",
    "Ищу кнопку": "Looking for a button",
    "Изучаю окно": "Inspecting the window",
    "Управляю рабочим столом": "Controlling the desktop",
    "Ищу в интернете: {q}": "Searching the web: {q}",
    "Читаю {what}": "Reading {what}",
    "Правлю {what}": "Editing {what}",
    "Пишу {what}": "Writing {what}",
    "Ищу в файлах": "Searching files",
    "Навык: {name}": "Skill: {name}",
    "Думаю глубже: {what}": "Thinking harder: {what}",
    "субагент": "subagent",
    # weather
    "Ясно": "Clear", "Малооблачно": "Mostly clear", "Переменная облачность": "Partly cloudy", "Пасмурно": "Overcast",
    "Туман": "Fog", "Морось": "Drizzle", "Дождь": "Rain", "Ливень": "Showers", "Снег": "Snow", "Снегопад": "Heavy snow",
    "Гроза": "Thunderstorm",
    # calendar
    "{when} в календаре ничего нет.": "Nothing in the calendar {when}.",
    "весь день — {title}": "all day — {title}",
    "в {time} — {title}": "at {time} — {title}",
    " И ещё {n}.": " And {n} more.",
    "{when} {n} {word}: ": "{when}: {n} {word}: ",
    "сегодня": "today", "завтра": "tomorrow", "на этой неделе": "this week",
    "событие": "event", "события": "events", "событий": "events",
    "Без названия": "Untitled",
    # instant commands
    "пауза": "paused", "воспроизведение": "playing", "следующий трек": "next track", "предыдущий трек": "previous track",
    "громкость +10%": "volume +10%", "громкость −10%": "volume −10%", "звук выключен": "muted", "звук включён": "unmuted",
    "экран заблокирован": "screen locked", "громкость {n}%": "volume {n}%", "открыл {what}": "opened {what}",
    "запустил {what}": "launched {what}", "закрыл {what}": "closed {what}", "свернул {what}": "minimized {what}",
    "переключил на {what}": "switched to {what}",
    # player
    "играет {what}": "playing {what}", "музыка продолжается": "music resumed", "музыка выключена": "music stopped",
    "сначала": "from the start", "перемотал": "skipped to the spot", "видео закрыто": "video closed",
    "Не нашёл «{q}»": "Couldn't find “{q}”", "Не получилось включить: {e}": "Couldn't play it: {e}",
    "Ищу видео: {q}": "Looking for a video: {q}", "Где включить видео?": "Where should the video play?",
    "В острове": "In the island", "прямо здесь, поверх окон": "right here, above the windows",
    "В окне": "In a window", "отдельный плеер, есть весь экран": "a separate player, can go fullscreen",
    "в браузере, с комментариями": "in the browser, with comments",
    "Где включить: в острове, в окне или на ютубе?": "Where should I play it: in the island, in a window or on YouTube?",
    "видео в острове": "video in the island", "видео в окне": "video in a window", "видео на YouTube": "video on YouTube",
    # mail
    "Отправил.": "Sent.",
    "Хорошо, не отправляю.": "Okay, not sending.",
    "Сначала скажите «проверь почту».": "Say “check my mail” first.",
    "На какое письмо ответить?": "Which email should I reply to?",
    "Не нашёл адрес для «{who}». Скажите адрес или имя, как в переписке.": "I couldn't find an address for “{who}”. Tell me the address or the name as in your mail.",
    "получателя": "the recipient",
    "Почта не настроена: {e}.": "Mail is not set up: {e}.",
    "Не получилось связаться с почтой.": "Couldn't reach the mail server.",
    " Ещё {n} в рекламе и соцсетях, их не читал.": " {n} more in promotions and social, not read.",
    "Новых важных писем нет.": "No new important emails.",
    "Кому: {to}. Текст: «{body}». Отправить?": "To: {to}. Text: “{body}”. Send it?",
    "Новое письмо от {who}.": "New email from {who}.",
    "{n} новых письма: {who}.": "{n} new emails: {who}.",
}


def lang() -> str:
    return config.load()["user"].get("language", "ru")


def t(_source: str, **kw) -> str:
    out = EN.get(_source, _source) if lang() == "en" else _source
    return out.format(**kw) if kw else out


def reply_language_hint() -> str:
    """Appended to local-model prompts so letters and summaries come out in the user's language."""
    return "\nОтвечай на английском языке (answer in English)." if lang() == "en" else ""
