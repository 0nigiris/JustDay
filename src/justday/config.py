"""Configuration: built-in defaults overlaid with ~/.config/justday/config.toml."""
from __future__ import annotations

import copy
import json
import os
import re
import subprocess
import tomllib
from pathlib import Path

HOME = Path.home()
CONFIG_DIR = Path(os.environ.get("XDG_CONFIG_HOME", HOME / ".config")) / "justday"
DATA_DIR = Path(os.environ.get("XDG_DATA_HOME", HOME / ".local/share")) / "justday"
STATE_DIR = Path(os.environ.get("XDG_STATE_HOME", HOME / ".local/state")) / "justday"
RUNTIME_DIR = Path(os.environ.get("XDG_RUNTIME_DIR", f"/run/user/{os.getuid()}"))
SOCKET_PATH = RUNTIME_DIR / "justday.sock"
CONFIG_FILE = CONFIG_DIR / "config.toml"
MODELS_DIR = DATA_DIR / "models"  # wake word, voice activity, Silero TTS: downloaded once, kept across reinstalls
EVENTS_FILE = STATE_DIR / "events.jsonl"
STATE_FILE = STATE_DIR / "state.json"
# The repository this package was installed from (editable install) — holds persona + plugin.
REPO_DIR = Path(__file__).resolve().parents[2]

SECRETS_FILE = CONFIG_DIR / "secrets.env"


def secret(name: str) -> str:
    """An API key: the environment, then the desktop keyring, then the legacy ~/.config/justday/secrets.env.

    Keys are never written to config.toml, never logged and never handed to the model. The keyring is the
    home of every key (AGENTS.md); the file is only read so an install made before that rule keeps working."""
    got = os.environ.get(name, "")
    if got:
        return got.strip()
    got = _keyring_get(name)
    if got:
        return got
    try:
        for line in SECRETS_FILE.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == name:
                return value.strip().strip("'\"")
    except OSError:
        pass
    return _mcp_secret(name)


_KEYRING_CACHE: dict[str, str] = {}


def _keyring_name(name: str) -> str:
    """ELEVENLABS_API_KEY → elevenlabs: the keyring names keys the way `justday secret` does."""
    return re.sub(r"_API_KEY$", "", name).lower()


def _keyring_get(name: str) -> str:
    """One `secret-tool` call per key per process: a hung keyring must not stall the event loop on every
    sentence (Р-32), and an empty answer is not remembered, so a key stored later is found."""
    if name in _KEYRING_CACHE:
        return _KEYRING_CACHE[name]
    try:
        r = subprocess.run(["secret-tool", "lookup", "service", "justday", "key", _keyring_name(name)],
                           capture_output=True, text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return ""
    got = r.stdout.strip() if r.returncode == 0 else ""
    if got:
        _KEYRING_CACHE[name] = got
    return got


def _mcp_secret(name: str) -> str:
    """A key an MCP server in ~/.claude.json already holds — no reason to ask for the same key twice."""
    import json as jsonlib

    try:
        servers = jsonlib.loads((HOME / ".claude.json").read_text(encoding="utf-8")).get("mcpServers") or {}
    except (OSError, ValueError):
        return ""
    for server in servers.values():
        got = ((server or {}).get("env") or {}).get(name)
        if got:
            return str(got).strip()
    return ""


def set_secret(name: str, value: str) -> None:
    """Put a key into the desktop keyring (or drop it when value is empty), and out of secrets.env."""
    _KEYRING_CACHE.pop(name, None)
    base = ["service", "justday", "key", _keyring_name(name)]
    if value:
        subprocess.run(["secret-tool", "store", "--label", f"JustDay: {_keyring_name(name)}", *base],
                       input=value, text=True, check=True, timeout=10)
    else:
        subprocess.run(["secret-tool", "clear", *base], check=False, timeout=10)
    _drop_from_file(name)


def _drop_from_file(name: str) -> None:
    try:
        lines = SECRETS_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return
    keep = [ln for ln in lines if ln.partition("=")[0].strip() != name]
    if keep != lines:
        SECRETS_FILE.write_text("".join(ln + "\n" for ln in keep), encoding="utf-8")


def migrate_secrets_file() -> list[str]:
    """Move every key from the legacy secrets.env into the keyring and empty the file (it is kept, not
    deleted). Returns the names moved; values never leave this function."""
    try:
        lines = SECRETS_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return []
    moved = []
    for line in lines:
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if key and value:
            set_secret(key, value)  # also removes the line from the file
            moved.append(key)
    return moved


DEFAULTS: dict = {
    # assistant_name: how the assistant calls itself and what you call it (also a hint for speech recognition)
    "user": {"name": "", "address_as": "сэр", "assistant_name": "Джарвис", "assistant_aliases": ["JustDay"],
             "language": "ru"},  # ru | en — assistant replies, voice lines and the island
    "audio": {
        # Substring of a PipeWire source node name; empty = system default source.
        "microphone": True,  # false = keyboard only: no mic, no wake word, speech recognition never loads
        "input": "",
        "output": "",
        # How loud JustDay itself is — its voice and its signals, 0–100% of the system volume.
        # The system volume stays where the user left it; this is the assistant's own knob.
        "volume": 100,
        "earcons": True,
        # Срок, после которого ждём ближайшей паузы и заканчиваем. Не жёсткий: оборвать человека
        # по секундомеру посреди слова хуже, чем дослушать лишние пять секунд.
        "max_utterance_seconds": 90,
        # Пауза, после которой просьба считается законченной. Для короткой команды — первая,
        # для долгой речи (дольше long_speech_seconds) — вторая: человек, надиктовывающий беду,
        # думает вслух и молчит по секунде, а обрыв на полуслове отправлял огрызок в работу.
        "silence_seconds": 1.0,
        "silence_long_seconds": 2.2,
        "long_speech_seconds": 5.0,
        "no_speech_timeout_seconds": 7,
        # After JustDay asks a question, listen again automatically for this long (0 = off).
        "followup_seconds": 6,
        # two presses of the talk key within this time = cancel everything (0 = off)
        "double_tap_seconds": 0.35,
    },
    # who the assistant is: jarvis (a butler), friend (casual, «ты»), calm (no act), custom (persona.custom);
    # swearing and live_speech (pauses, «ну», slips) go with any of them
    "persona": {"character": "jarvis", "swearing": False, "live_speech": False, "custom": ""},
    "stt": {
        "model": "large-v3-turbo",
        "device": "cuda",
        # Столько же для распознавания речи (~1,1 ГБ видеопамяти). Возврат около трёх секунд и
        # прячется за нажатием «говорить»: модель поднимается, пока фразу ещё договаривают.
        "idle_unload_minutes": 15,
        "compute_type": "int8_float16",
        "language": "ru",
        "initial_prompt": "Джарвис, JustDay, Claude Code, YouTube, Discord, Steam, Proton, GitHub, KDE, Helium, VS Code.",
    },
    "tts": {
        "engine": "silero",  # qwen (neural, justday-voice service) | elevenlabs | silero | espeak | none
        "voice": "jarvis",  # neural voice id: the built-in jarvis, or one you designed/cloned
        "neural_quality": "fast",  # fast (0.6B, ~2.5 GB VRAM) | best (1.7B, ~4.5 GB VRAM)
        "silero_model_url": "https://models.silero.ai/models/tts/ru/v5_5_ru.pt",
        "speaker": "eugene",
        "sample_rate": 48000,
        "speed": 1.15,  # 1.0 = as the model speaks; 1.1–1.3 sounds like a person in a hurry
        # Манера речи словами — нейроголос понимает её сам («спокойно, деловито»).
        # Темп из speed превращается в такую же просьбу, вместо растяжения готовой речи.
        "style": "",
        "latin": "auto",  # auto = spell English the Russian way only for voices that cannot read it (silero, espeak)
        "numbers": True,  # say figures as words: «7:05» → «семь ноль пять», «3,5 ГБ» → «три с половиной гигабайта»
        # ElevenLabs (engine = "elevenlabs"): the key lives in the desktop keyring (`justday secret set elevenlabs`), never here.
        "eleven_voice": "JBFqnCBsd6RMkjVDRZzb",  # `justday voice eleven` lists the voices on your account
        "eleven_model": "eleven_flash_v2_5",  # flash = fastest; eleven_multilingual_v2 = richer, slower
        # Нейроголос отказал (не влез в видеопамять) — столько минут к нему не стучаться. Иначе
        # каждая фраза начинается с ожидания отказа, и человек слышит это как «голос лагает».
        "retry_minutes": 10,
        "previous_engine": "",  # remembered when voice replies are switched off
        "muted": False,  # answers are shown on the island but not spoken («отключи голос»)
        # Сколько минут молчания держать нейроголос в видеопамяти (~2,5 ГБ у 0.6B, ~4,5 ГБ у 1.7B).
        # 0 — держать всегда. Возврат стоит около десяти секунд, и он прячется за раздумьем ассистента.
        "idle_unload_minutes": 15,
        # А через сколько минут голосовой службе выйти совсем: отпущенная модель возвращает
        # видеопамять, но ~2 ГБ обычной держит torch, и отдать их можно только выходом. Служба
        # поднята через гнездо systemd, поэтому следующая просьба разбудит её сама. 0 — не выходить.
        "quit_after_minutes": 40,
        "mute_in_games": True,  # and it falls silent by itself while a game is running: the GPU is the game's
    },
    # names = also wake on the assistant's names («Джарвис», «JustDay»), read by Whisper on the start of each phrase
    # wake_names: which names wake it (empty = the assistant name only)
    # threshold_while_playing: пока из колонок идёт звук, микрофон слышит и его —
    # «Джарвис», сказанный в ролике, будил ассистента наравне с хозяином.
    # Тишина по расписанию: список {name, days, from, to} — см. focus.py. Пусто = всегда можно говорить.
    "focus": {"schedule": []},
    # name_candidate: имя в речи ищет Whisper, но только в отрывке, где openWakeWord хоть раз дал этот балл;
    # иначе он гонялся на всякую речь в комнате и не отпускал видеопамять (Р-30). 0 = на любую речь.
    # Если «Джарвис» перестал будить — смотри в журнале «name heard … (openWakeWord N)» и опусти планку.
    "wakeword": {"enabled": False, "names": True, "wake_names": [], "model": "hey_jarvis",
                 "threshold": 0.5, "threshold_while_playing": 0.7, "name_candidate": 0.05},
    "brain": {
        # claude | ollama | openrouter | deepseek | custom — see `justday model list`
        "provider": "claude",
        "base_url": "",  # only for provider = "custom"
        "context_tokens": 0,  # model context window for non-Claude providers (0 = provider default)
        "model": "haiku",
        # Модель под задачу. Лёгкая справляется с девятью просьбами из десяти — «открой дискорд»,
        # «сделай тише», «какая погода», — и держать на них сильную значит остаться без лимитов к
        # обеду. Решает не список слов, а местная модель на той же видеокарте: она стоит ноль и
        # отвечает за полсекунды. Повышение происходит до работы, понижение — после неё, чтобы
        # человек не ждал смены модели ради того, что и так будет быстрым.
        "auto_model": True,
        "light_model": "haiku",
        # Кто решает, кем отвечать. «never» — ход сразу идёт на лёгкой модели, без судьи: он
        # съедал секунду и шесть гигабайт карты ради ответа «light» в 99% случаев. Если задача
        # не по силам, лёгкая сама отвечает «НУЖНА: sonnet», и демон повторяет вопрос выше.
        # «always» — как было: местный судья перед каждым ходом.
        "ask_judge": "never",
        "strong_model": "sonnet",
        # Четвёртая ступень — за настоящую работу, а не за задачу на один присест: спроектировать
        # или написать с нуля, переписать проект, разобраться в большом чужом коде. Пусто — такой
        # работы не бывает, обходимся сильной.
        "huge_model": "opus",
        # Усилие тоже выбирается под задачу, а не настройкой: «который час» от высокого усилия не
        # становится точнее, а разбор чужой ошибки без него кончается правдоподобной догадкой.
        # false — держать то, что стоит в `effort`.
        "auto_effort": True,
        # Куда идти, когда у Claude кончился лимит. По порядку, пропуская тех, у кого нет ключа.
        # Лимит кончается предсказуемо, раз в несколько часов, и всё это время бесплатные модели
        # прекрасно откроют дискорд и ответят на вопрос — сидеть в скудном местном режиме незачем.
        # Пустой список — никуда не переходить, честно сказать и ждать.
        "fallbacks": ["openrouter", "ollama"],
        "fallback_models": {},   # поставщик → модель, если не хочется первой из предложенных
        # Наверху лестницы — тот, кем хочется думать всегда. Уйдя вниз, мы туда и возвращаемся.
        "home_provider": "claude",
        # Через сколько часов начать проверять, вернулся ли лимит. 0 — не возвращаться самому.
        "fallback_back_after_hours": 5,
        # Как часто после этого спрашивать верхнего: «ты уже отвечаешь?» Один крошечный вопрос, не
        # разговор. Угадывать, когда лимит вернётся, нечем — Claude этого не говорит, — а проверка
        # стоит одного слова и возвращает нас наверх в тот же час, а не через сутки.
        "fallback_check_minutes": 15,
        # Совсем мелкие просьбы — «который час», «громче», «как дела» — не стоят даже лёгкой
        # облачной модели. Если здесь стоит имя местной модели (например qwen3:0.6b), такие
        # просьбы уходят ей: она на вашей видеокарте, стоит ноль и отвечает мгновенно. Пусто —
        # не использовать. Инструменты ей почти не даются, поэтому и берётся она только на то,
        # где делать ничего не надо.
        "tiny_model": "",
        "tiny_provider": "ollama",
        "effort": "low",
        "permission_mode": "auto",
        "chrome": True,
        # Схемы инструментов в контексте: on — подгружаются по мере надобности (стартовый контекст
        # втрое меньше, а значит и счёт), auto — решает Claude Code, off — все схемы сразу.
        "tool_search": "on",
        # Потолок разговора в токенах: дойдя до него, Claude Code сжимает историю и продолжает.
        # 80 000, а не 200 000: голосовой разговор идёт с паузами, кэш промпта за 5 минут стынет, и
        # каждый ход после паузы заново платит запись всей истории — медиана 124 тыс. токенов на ход,
        # среднее 237 тыс. (Р-25). Голосу хватает свежего; 0 = как решит Claude Code.
        "context_window": 80000,
        # Resume the previous conversation if it was active within this many hours.
        "resume_within_hours": 12,
        "claude_cli": "claude",
    },
    "workers": {
        "model": "",  # empty = user's Claude Code default
        "permission_mode": "auto",
        "poll_seconds": 15,
        "auto_review": True,
    },
    # Сценарии: «я сел работать» — несколько привычных действий одной фразой, без модели.
    # [[scenes]] name / phrases / open / close / run / music / silent / say — см. config.example.toml.
    "scenes": [],
    # Планы и заметки пишутся в хранилище Obsidian: vault "" = найти открытое самому.
    # diary_hour: во сколько сама записывается страница дня (0 = не записывать).
    "notes": {"vault": "", "plans": "Планы.md", "diary": "Дневник", "diary_hour": 23},
    # face: что показывать на экране — auto (по сеансу: остров на Wayland, полоска на X11),
    # island или panel. Решается при каждом входе, а не один раз при установке.
    "ui": {
        # Раз во сколько дней напоминать перезагрузиться. Машина, не выключавшаяся месяцами, копит
        # обновления ядра и утёкшую память драйверов — это не катастрофа, но однажды становится ею,
        # и всегда не вовремя. Напоминаем, а не перезагружаем: за компьютером может идти работа,
        # которой ассистент не видит. 0 — не напоминать.
        "reboot_reminder_days": 7,"notifications": True, "face": "auto"},
    # «Я ушёл» closes the open applications and remembers them; «я вернулся» opens them again.
    # keep: what is never closed (a substring of the window class or the application name).
    # История буфера обмена для панели на островке. Пароли в неё не попадают: то, что программа
    # пометила как секрет, и то, что похоже на ключ, не запоминается вовсе — см. clipboard.py.
    # history = false выключает её целиком, и наблюдатель за буфером даже не запускается.
    "clipboard": {"history": True},
    "session": {
        "keep": ["kitty"],
        # Режим сервера: машина выключена для человека и работает для ассистента. Ввод мы не
        # отключаем нарочно (`server.py`): машина без мыши и клавиатуры, до которой почему-то не
        # дотянуться с телефона, — кирпич. `hours` — через сколько сторож сам вернёт её человеку:
        # забытый режим это машина, которая не спит неделю.
        # own_desktop — ассистенту свой рабочий стол: экраны погашены, но стол под ними его, с
        # окнами, разложенными как он их оставил, и работа перекопала бы его к утру. Это его
        # «свой монитор, а не мои», только без виртуальных выходов, которые на NVIDIA ненадёжны.
        "server_mode": {"screens_off": True, "mute": True, "pause_players": True, "hours": 10,
                        "own_desktop": True, "desktop_name": "JustDay",
                        # Подсветка железа (память, плата, клавиатура, мышь) через OpenRGB.
                        # Тёмный экран при полыхающей радугой клавиатуре — это не «компьютер
                        # выключен»: комната всё равно светится, ночью сильнее монитора.
                        "leds_off": True,
                        # Замок: подошедший к машине человек видит запрос пароля, а не чужую
                        # работу. Цена честная — пока сеанс заперт, ассистент не водит мышью по
                        # чужим окнам; всё остальное (код, проверки, коммиты, сеть) идёт как шло.
                        "lock": True},
    },
    "updates": {"check": True, "interval_hours": 6},
    # personal voice profile (Settings → Голос и звук → «Настроить под мой голос»)
    "voiceprint": {"mode": "off"},  # off | wake (only wake word / follow-ups must be you) | always
    # Dynamic Island look & feel (applied live)
    "island": {
        "animations": "spring",  # spring (Apple-like bounce) | smooth | off
        "hover_reveal": True,  # hover the top edge to show the island
        "show_weather": True,
        "weather_peek": True,      # погода в полоске при наведении на верхний край
        "weather_expanded": True,  # …и в раскрытом островке
        "events_peek": True,
        "events_expanded": True,
        "show_events": True,  # last answer / new mail / Claude status in the hover view
        # Что играет — показывать или нет, и где именно. Полоска (peek) и раскрытая карточка
        # нужны не всем одинаково: один хочет видеть трек всегда, другому он мешает в свёрнутом
        # виде и нужен только в раскрытом. Раньше выбора не было вовсе, а источником был жёстко
        # вписанный Spotify — у всех, кто слушает не его, полоска пустовала.
        #
        # prefer — кого показывать первым, если играет несколько сразу (куски имени MPRIS или
        # desktop entry, в нижнем регистре). ignore — кого не показывать никогда: браузер,
        # играющий рекламу в соседней вкладке, сюда и просится.
        "player_peek": True,       # трек в свёрнутой полоске
        "player_expanded": True,   # карточка плеера в раскрытом островке
        "player_prefer": ["spotify"],
        "player_ignore": [],
        # Островок сам показывает уведомления, забирая место сервера на шине, если оно свободно.
        # Уведомления на фридесктопе показывает тот, кто занял это место первым, и оно одно на всю
        # систему: убрав панель плазмы, мы оставили его пустым, и его занимал чужой демон. false —
        # не занимать (тогда показывать их будет кто-то другой, со своим видом).
        # Пока ассистент работает, островок показывает только значок; строка и подробности — по
        # нажатию. Работа идёт почти всегда, и полоса в шестьсот точек с текстом, которого никто не
        # просил, висела бы почти всегда. false — показывать строку сразу, как было раньше.
        # Вид верхней полосы: island — капсула под краем, bar — сплошная полоса во всю ширину,
        # notch — вырез, прижатый к краю и скруглённый только снизу. Капсула посреди верхнего края
        # перекрывает вкладки браузера, и это не вкусовщина, а причина иметь выбор.
        # bar сидит вплотную к краю и красится той же заливкой, что и меню из неё.
        # bar_autohide — уезжает, пока не подвести курсор; иначе висит всегда.
        # Полноэкранное окно прячет полосу само, отдельно от bar_autohide.
        "style": "island",
        "bar_autohide": False,
        "bar_height": 44,  # толщина сплошной полосы в точках; карточка растёт вниз от неё
        "enabled": True,  # сам верхний островок; False убирает его совсем
        "above": True,    # держать верхнюю полосу над обычными окнами
        "cat": False,     # бегущая кошка на верхней полосе, отдельно от dock.cat
        "cat_place": "clock",  # где она на сплошной полосе: clock — у часов, tray — среди значков трея
        "work_quiet": True,
        "notification_server": True,
        "show_notifications": True,  # mirror desktop notifications on the island (they never leave the computer)
        # Where toast/shade notifications appear (Telegram-style), independent of the island pill:
        # screen: "" = same monitor as the island; "primary" | "secondary" | output name (HDMI-A-1, DP-2…)
        # position: top-left | top-center | top-right | bottom-left | bottom-center | bottom-right
        # (empty position = follow island.position)
        "notification_screen": "secondary",
        "notification_position": "top-right",
        # Transient system HUD (volume / layout / brightness) — Noctalia-style OSD.
        # Separate from Telegram-style app toasts (notification_*). Empty position = near island.
        "show_osd": True,
        "osd_screen": "island",  # primary | secondary | island | output name
        "osd_position": "top-center",  # top|bottom + -left|-center|-right; empty = follow island
        "city": "",  # weather location; empty = no weather requests at all
        "screen": "",  # monitor name (e.g. DP-2); empty = the one at the top-left
        # Где висит сам остров и где открывается меню приложений:
        # top-left | top-center | top-right | bottom-left | bottom-center | bottom-right
        "position": "top-center",
        # dock = меню вырастает из значка в доке (и садится к нему), иначе — угол экрана
        "menu_position": "dock",
        # How much room to leave above the island: a panel along the top edge stays reachable
        "top_margin": 8,
        # Размер меню приложений. Он не считается по содержимому нарочно: тогда карточка меняла
        # высоту на каждом разделе, и лента разделов уезжала из-под курсора. Меняется углом самой
        # карточки, сюда записывается сам.
        # Существо в островке вместо кольца. Пока выключено: нарисованный кодом зверь сделан, но
        # до уровня остального островка не дотягивает, и ставить недоделанное по умолчанию нельзя.
        # Включается одним переключателем, когда захочется посмотреть.
        "buddy": False,
        # Скин маскота: имя папки из ~/.local/share/justday/mascots или из data/mascots. Пусто —
        # рисуем своего, кодом. Список: `justday mascots`.
        "mascot": "",
        "mascot_size": 100,     # насколько крупно показывать зверя, в процентах
        "menu_width": 760,
        "menu_height": 620,
        "video_width": 640,  # the island video frame, in points — dragged by its corner, remembered here
        "video_volume": 1.0,  # how loud that frame is, 0–1 (the wheel over it)
        # Как Qt крутит анимации. basic (его Qt выбирает сам) — таймером, шестьдесят шагов в
        # секунду при любой развёртке: движение идёт ступеньками. threaded — по развёртке, плавнее
        # на глаз, но оболочка рисуется в два-три раза чаще, и на занятой видеокарте это заметно
        # сильнее, чем ступеньки. Поэтому по умолчанию решает Qt, а выбор — за человеком.
        "render_loop": "auto",
        # Размытие под доком, полосой лотка и меню. Красиво, но это самый дорогой эффект композитора
        # из всех: он пересчитывает многопроходное размытие каждый раз, когда под ним что-то
        # меняется. На занятой видеокарте выключение даёт больше, чем всё остальное вместе.
        "blur": True,
        # Уведомления и так приходят на остров. Плазма при этом показывает свою всплывашку — одно и
        # то же дважды, вторым разом в чужом оформлении. false выключает её «не беспокоить»-ом:
        # история остаётся, программы как звали Notify, так и зовут, остров всё слышит.
        "system_popups": False,
    },
    # Док: полоса программ у края экрана. Закреплённое и открытое, увеличение под курсором,
    # значок меню в начале. position: bottom | top; reserve — exclusiveZone-магнит (по умолч. выкл.).
    "dock": {
        "enabled": True,
        "position": "bottom",
        "icon_size": 44,
        "spacing": 20,          # расстояние между значками, в точках
        "magnify": True,
        # На сколько процентов значок вырастает под курсором и насколько широкой волной это идёт
        # по соседям (в процентах от ячейки). Стиль движения: spring — с отскоком, как у макоси,
        # smooth — плавно и без отскока, instant — волна просто следует за курсором.
        # На сколько процентов вырастает ближний к курсору значок и какой ширины волна идёт по
        # соседям (в процентах от ячейки). 80% — это ×1,8, как у макоси.
        "magnify_scale": 80,
        "magnify_spread": 200,
        "animation": "spring",
        # Пружина: жёсткость (быстрее доезжает до размера) и затухание (меньше — сильнее отскок).
        # Затухание 1 — без отскока вовсе, это и есть стиль «плавно».
        "spring": 180,
        "damping": 0.8,
        "autohide": False,
        # exclusiveZone / strut (магнит): развёрнутые окна останавливаются над доком.
        # По умолчанию выкл.: окна могут наезжать на полосу дока, а hide_on_fullscreen тогда
        # прячет док по геометрии (перекрытие нижней/верхней полосы или полный экран). Позвать
        # обратно — наведением на край, как у островка/лотка. true = Plasma-панель + чёрная
        # полоса под обоями как цена магнита.
        "reserve": False,
        "show_running": True,   # открытые окна незакреплённых программ
        # Кнопка в доке, которая показывает и прячет полосу лотка. Для тех, кому полоса сбоку не
        # нужна постоянно: значки чужих программ лежат за одной кнопкой и не занимают край экрана.
        # По умолчанию выключена — это добавка, а не то, что надо всем.
        "tray_button": False,
        "show_trash": True,
        # Подписи: off — нет совсем, hover — под курсором, always — имя под каждым значком.
        # true и false тоже понимаются: это прежние «под курсором» и «нет».
        "labels": "hover",
        # Чем отмечено открытое: dot (точка), line (чёрточка), bar (полоса), glow (свечение за
        # значком), none (ничем).
        "indicator": "dot",
        # Прятать док, когда окно наезжает на его полосу или уходит в полный экран — даже без
        # autohide. Позвать обратно наведением на край (как островок/лоток).
        "hide_on_fullscreen": True,
        # Как прячущийся док зовут обратно. Зона у края широкая, но входа в неё мало: док выезжает
        # на взмах — на быстрое движение к краю. Так широкая зона не мешает: мимо ходят медленно, к
        # доку — быстро. Медленный путь остался один: упереться в самый край экрана.
        # На каких экранах быть доку: primary — только там, где живёт островок; all — на каждом.
        # Главным всё равно остаётся один: он рассказывает островку, где лежит карточка и откуда
        # растить меню, и будь таких рассказов два, они бы спорили.
        "screens": "primary",
        "reveal_zone": 28,      # высота зоны вызова в точках
        "reveal_flick": 900,    # нужная скорость в точках в секунду; 0 — звать любым наведением
        # Заголовки открытых окон под подписью. Картинок-предпросмотров тут нет и быть не может:
        # снимать чужие окна на KWin умеет только композитор, обычным клиентам он этого не даёт.
        "preview": True,
        # Порядок значков — перетаскиванием. Порог у захвата свой, поэтому обычное нажатие
        # остаётся нажатием; false — если док трогают случайно и порядок «уезжает» сам.
        "reorder": True,
        # «Колесо»: под непрерывным увеличением появляются защёлки, как у переключателя. Выбор
        # меняется не на середине между значками, а при заходе в соседа достаточно глубоко, —
        # поэтому он не дрожит, когда рука стоит на границе. Переход даёт короткий щелчок.
        "wheel": False,
        "detent": 90,           # сила щелчка в процентах; 0 — защёлки без толчка
        # Значок, из которого достаётся меню: apple = «start-here» из темы значков (в макосных
        # темах это яблоко), grid = своя сетка точек, или прямо имя значка из темы.
        "launcher": "apple",
        "cat": True,            # бегущая кошка: чем сильнее занят процессор, тем быстрее бежит
        "cat_sleep_below": 0,   # ниже этого процента кошка ложится спать (0 — не спит никогда)
        "clock": False,         # часы в доке (сверху они уже есть)
        # Состав полосы, слева направо. Слова: launcher (значок меню), pinned (закреплённое),
        # running (открытое, но не закреплённое), trash, cat, clock, sep (черта), space (промежуток).
        # Порядок в списке и есть порядок на экране: «часы слева» — это не новая настройка, а другой
        # порядок слов. Пустой список — тот, что ниже.
        "layout": ["launcher", "sep", "pinned", "running", "sep", "trash", "sep", "cat", "clock"],
        "separator_room": 0,      # место под черту в точках; 0 — как получится из расстояния
        "separator_width": 1,     # толщина самой черты
        "separator_height": 62,   # её высота, в процентах от значка
        "separator_opacity": 16,  # насколько она заметна, в процентах
        # Палитра поверх значков дока: original | light | clear | tinted | mono
        "icon_style": "original", "icon_tint": "#7AC8FF",
    },
    # Трей: чужие значки (те, что кладут в системный лоток) отдельной полосой у бокового края.
    # position: left | right; align: center | start | end.
    # hidden — идентификаторы значков, которых в полосе быть не должно. Мост xwayland кладёт в
    # лоток служебное окно, которое человеку не нужно никогда.
    "tray": {"enabled": True, "position": "left", "align": "center", "icon_size": 22, "reserve": False,
             "autohide": False, "hidden": ["xwayland video bridge"],
             # Увеличение под курсором — то же, что у дока, только повёрнутое на бок. Полоса лотка
             # такая же сплошная поверхность, и отвечать на курсор должна так же: два разных
             # поведения у двух соседних полос — верный способ получить оболочку, которая ведёт
             # себя по настроению. Лоток растёт скромнее дока: значки там чужие и мельче.
             # Пружина и затухание общие с доком — это не вкус полосы, а нрав всей оболочки.
             "magnify": True, "magnify_scale": 60, "magnify_spread": 160,
             # Раскладка клавиатуры первой ячейкой полосы: две буквы, нажатие переключает.
             "layout": True,
             # Наведение обводит значок рамкой, а не подкладывает под него пузырь: пузырь больше
             # значка и читается как второй, сломанный значок под первым. false — не рисовать и
             # рамку: остаются одни значки.
             "hover_frame": True,
             # Палитра значков: original | auto | light | clear | tinted | mono
             "icon_style": "original", "icon_tint": "#7AC8FF"},
    # Accessibility bus on: Qt/GTK apps expose their buttons, so `look` can mark them for exact clicks.
    "desktop": {"accessibility": True},
    # Настоящий звонок (`src/justday/telnyx.py`). Ключ живёт только в связке ключей под именем
    # telnyx — здесь его нет и быть не должно: конфиг уезжает в репозиторий, связка нет.
    # from — купленный номер, app_id — приложение Call Control из портала. Пусто — звонков нет.
    "phone": {"telnyx": {"from": "", "app_id": "", "voice": "female", "language": "ru-RU"}},
    # Оболочка в терминале (`justday terminal`): один терминал, лестница движков.
    #
    # Порядок — это и есть приоритет: «сначала Клод, потом ChatGPT, потом что осталось». Ступень
    # пишется как «движок:модель»; делится по первому двоеточию, потому что в имени местной модели
    # двоеточие тоже есть. Ступени, куда нечем войти, пропускаются — иначе каждая задача начиналась
    # бы с провала: поставщик без ключа отвечает ошибкой, а ошибку лестница понимает как лимит.
    "terminal": {
        # Одна лестница на весь проект: плагин OpenCode берёт ступени отсюда (`shell.ensure`).
        # Бесплатные модели OpenCode (`opencode/*-free`) здесь нарочно нет: их логи не наши, и команды
        # с правами им отдавать нельзя (Р-60). NVIDIA NIM — бесплатные кредиты аккаунта, стоит выше
        # платной openrouter: когда подписка кончилась, работа должна идти даром, а не на его кредитах.
        # Замерено 3 октября (`opencode run`, короткий вопрос): nemotron-3-ultra-550b — 29 с.
        "ladder": ["claude:opus", "claude:sonnet", "opencode:openai/gpt-6-luna",
                   "opencode:nvidia/nvidia/nemotron-3-ultra-550b-a55b",
                   "opencode:openrouter/qwen/qwen3-coder", "opencode:ollama/qwen3.5:9b"],
        "effort": "",          # low | medium | high; пусто — как решит сам Claude Code
        # Сколько ждать первого слова от ступени. Ступень с просроченным входом не отказывает —
        # она висит молча и бесконечно, и работа висит вместе с ней. Дальше первого слова ждём
        # сколько надо: думать десять минут над настоящей задачей нормально.
        "first_word_seconds": 90,
        # Выбирать модель и усилие по самой задаче: «который час» не стоит ни высокого усилия, ни
        # самой сильной модели, а переписать половину проекта стоит и того и другого. Решает та же
        # местная модель-судья, что и у голосового Джарвиса (`dispatch`).
        "auto": True,
        # Кем брать задачу на ступени Claude Code — под саму задачу, а не настройкой. Снизу вверх:
        # ответить словом, сделать одно дело, написать и починить код, спроектировать большое.
        # Решает та же местная модель-судья, что и у голосового Джарвиса (`dispatch`), а если она
        # ошиблась в сторону лёгкой — лёгкая передаёт задачу выше сама (`terminal.hand_up`).
        "models": {"tiny": "haiku", "light": "haiku", "strong": "sonnet", "big": "opus"},
        "hand_up": True,           # разрешить лёгкой модели сказать «это серьёзнее меня»
        # Пока мы внизу, раз в столько минут у верхнего спрашивают одним словом: «уже отвечаешь?»
        # Спрашивают между задачами, а не посреди: забрать работу у того, кто её делает, значит
        # её потерять.
        "probe_minutes": 15,
        # Сколько раз ночью подтолкнуть, если ход кончился вопросом к человеку. Половина таких
        # вопросов — «какой из двух путей», и выбрать можно самому. Бесконечно толкать нельзя:
        # если без человека правда нельзя, он должен найти это утром словами.
        "night_nudges": 2,
        # Сжатие по своей воле. Разговор упирается в стену «кончился контекст» всегда посреди
        # дела: ход прерывается там, где его застало. Поэтому место считаем сами и просим сжать
        # **между задачами**, когда свободного осталось меньше `compact_at` от окна.
        "compact_at": 0.2,
        "context_window": 200000,   # сколько токенов держит разговор; 0 — не считать место вовсе
        # Уходя на ночь из окна (`/night`), заодно включать режим сервера: он сказал это прямо —
        # «включить и лечь спать». Экран гаснет, музыка встаёт на паузу, машина не засыпает.
        "night_server": True,
        # Claudex-петля: после задачи, которая что-то изменила в репозитории, Codex (ChatGPT, read-only,
        # без сети) читает изменения и пишет замечания, Claude исправляет обоснованные. Не больше двух
        # кругов: третий — это две нейросети, спорящие о вкусе. Codex нет или он не вошёл — шаг молча
        # пропускается. false — не ревьюить вовсе.
        "review": True,
        "review_rounds": 2,
        "review_timeout": 300,      # секунд на один круг ревью
    },
    # Наблюдатель (`observer.py`): Джарвис пишет первым, но только о встрече, до которой осталось не больше
    # lead_minutes, и один раз. Канал — уведомление, Telegram (бесплатно) и голос, если он за компьютером.
    # Звонка нет: он стоит денег. Нужен подключённый календарь (`justday calendar setup`).
    "observer": {"enabled": True, "lead_minutes": 20, "telegram": True},
    # Local model for private data (mail). Ollama listens on localhost only.
    "local_llm": {"url": "http://127.0.0.1:11434", "model": "qwen3.5:9b", "num_ctx": 16384,
                  "keep_alive": "10m",
                  # Судья («лёгкая это задача или сильная») отвечает одним словом, и держать
                  # ради него на карте шесть гигабайт нельзя: нейронному голосу тогда некуда
                  # грузиться. Пусто — тот же model; маленькая модель здесь лучше (например
                  # `ollama pull qwen3:0.6b`).
                  "judge_model": "", "judge_keep_alive": "20s"},
    "mail": {
        "address": "",
        "imap_host": "imap.gmail.com",
        "smtp_host": "smtp.gmail.com",
        # Gmail search syntax: Primary = what a person wrote; the rest is only counted
        "query": "category:primary is:unread newer_than:7d",
        "other_query": "is:unread newer_than:7d -category:primary",
        "max_letters": 8,
        "announce": True,  # say "новое письмо от …" when important mail arrives
        "poll_seconds": 180,
    },
    # Local creative studio (justday studio): ComfyUI is found automatically; empty = auto
    "studio": {"comfy_dir": "", "python": "", "url": "", "rmbg_dir": "", "free_after": True},
    # Own player: music from YouTube is downloaded to ~/Music/JustDay/YouTube and plays in a background mpv.
    # video_where: ask | island | window | browser — where "включи видео …" plays
    # duck: the music gets quieter while the assistant listens or speaks
    # color: theme = the island takes the colour the music is about (a character's theme, a game's palette),
    # asked of the model once per track and kept in ~/.local/state/justday/colors.json; cover = the old way,
    # the brightest pixel of the artwork. color_web: let that question use web search for tracks the model
    # does not know. Track titles (never the audio) leave the machine for this, like any other request.
    # video_where_strict: keep the chosen place even when the request names another one
    # ("включи в островке" is honoured by default, whatever video_where says)
    "media": {"video_where": "ask", "video_where_strict": False, "volume": 70, "duck": True, "show_player": True,
              "color": "theme", "color_web": True},
    # Spoken name → desktop id, checked first by the instant path (e.g. "дискорд" = "org.equicord.equibop").
    "apps": {"aliases": {}},
}


def _merge(base: dict, over: dict) -> dict:
    out = copy.deepcopy(base)
    for k, v in over.items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _merge(out[k], v)
        else:
            out[k] = v
    return out


def load() -> dict:
    # Копия, а не сами DEFAULTS: без config.toml выбор модели, громкость и язык голоса правили
    # умолчания всего процесса, а reload_settings сравнивал объект сам с собой и не видел ничего (Р-18).
    cfg = copy.deepcopy(DEFAULTS)
    if CONFIG_FILE.exists():
        try:
            with CONFIG_FILE.open("rb") as f:
                cfg = _merge(DEFAULTS, tomllib.load(f))
        except tomllib.TOMLDecodeError as e:
            # Settings UI writing `[island] # comment` used to miss the header and append a
            # second `[island]` — tomllib then refuses the file and Settings never opens.
            if "twice" in str(e).lower() and heal_duplicate_tables():
                with CONFIG_FILE.open("rb") as f:
                    cfg = _merge(DEFAULTS, tomllib.load(f))
            else:
                raise
    return cfg


def _toml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    return json.dumps(str(v), ensure_ascii=False)


def _section_header_index(lines: list[str], section: str) -> int | None:
    """Index of `[section]` — trailing comments allowed (`[island]  # …`).

    Must not match a longer table name: `[island.extra]` is not `[island]`.
    """
    head = f"[{section}]"
    for i, raw in enumerate(lines):
        s = raw.strip()
        if s == head:
            return i
        if not s.startswith(head):
            continue
        rest = s[len(head):]
        if not rest or rest.lstrip().startswith("#"):
            return i
    return None


def _header_name(line: str) -> str | None:
    m = re.match(r"^\[([A-Za-z0-9_.-]+)\]\s*(#.*)?$", line.strip())
    return m.group(1) if m else None


def heal_duplicate_tables() -> bool:
    """Merge later duplicate `[table]` blocks into the first (last key wins). Returns True if rewritten."""
    if not CONFIG_FILE.exists():
        return False
    lines = CONFIG_FILE.read_text(encoding="utf-8").splitlines()
    by: dict[str, list[int]] = {}
    for i, raw in enumerate(lines):
        name = _header_name(raw)
        if name:
            by.setdefault(name, []).append(i)
    dupes = {n: idxs for n, idxs in by.items() if len(idxs) > 1}
    if not dupes:
        return False

    # Rebuild: keep first occurrence of each table; fold keys from later ones over it.
    out: list[str] = []
    i = 0
    seen: set[str] = set()
    pending_keys: dict[str, dict[str, str]] = {n: {} for n in dupes}  # name -> key -> full line
    # First pass: collect key overrides from duplicate blocks (later wins)
    for name, idxs in dupes.items():
        for start in idxs[1:]:
            end = next((j for j in range(start + 1, len(lines)) if _header_name(lines[j])), len(lines))
            for j in range(start + 1, end):
                m = re.match(r"\s*([A-Za-z0-9_]+)\s*=", lines[j])
                if m and not lines[j].lstrip().startswith("#"):
                    pending_keys[name][m.group(1)] = lines[j]

    while i < len(lines):
        name = _header_name(lines[i])
        if name and name in dupes and name in seen:
            # skip this duplicate block entirely
            i = next((j for j in range(i + 1, len(lines)) if _header_name(lines[j])), len(lines))
            continue
        if name and name in dupes:
            seen.add(name)
            start = i
            end = next((j for j in range(start + 1, len(lines)) if _header_name(lines[j])), len(lines))
            block = lines[start:end]
            # apply overrides into the first block
            overrides = pending_keys.get(name) or {}
            present: set[str] = set()
            new_block = [block[0]]
            for raw in block[1:]:
                m = re.match(r"\s*([A-Za-z0-9_]+)\s*=", raw)
                if m and m.group(1) in overrides:
                    new_block.append(overrides[m.group(1)])
                    present.add(m.group(1))
                else:
                    new_block.append(raw)
                    if m:
                        present.add(m.group(1))
            for key, raw in overrides.items():
                if key not in present:
                    new_block.insert(1, raw)
            out.extend(new_block)
            i = end
            continue
        out.append(lines[i])
        i += 1

    CONFIG_FILE.write_text("\n".join(out) + "\n", encoding="utf-8")
    return True


def set_value(section: str, key: str, value) -> None:
    """Set one key in config.toml, keeping the user's comments and layout."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    if CONFIG_FILE.exists():
        heal_duplicate_tables()
    lines = CONFIG_FILE.read_text(encoding="utf-8").splitlines() if CONFIG_FILE.exists() else []
    line = f"{key} = {_toml_value(value)}"
    header = f"[{section}]"
    start = _section_header_index(lines, section)
    if start is None:
        lines += ["", header, line]
    else:
        end = next((i for i in range(start + 1, len(lines)) if _header_name(lines[i])), len(lines))
        for i in range(start + 1, end):
            if re.match(rf"\s*{re.escape(key)}\s*=", lines[i]):
                lines[i] = line
                break
        else:
            lines.insert(start + 1, line)
    CONFIG_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")


def ensure_dirs() -> None:
    for d in (CONFIG_DIR, DATA_DIR, STATE_DIR):
        d.mkdir(parents=True, exist_ok=True)
