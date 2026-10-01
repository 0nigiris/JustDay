"""Configuration: built-in defaults overlaid with ~/.config/justday/config.toml."""
from __future__ import annotations

import copy
import json
import os
import re
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
    """An API key from the environment, or from ~/.config/justday/secrets.env (KEY=value, mode 600).

    Keys are never written to config.toml, never logged and never handed to the model."""
    got = os.environ.get(name, "")
    if got:
        return got.strip()
    try:
        for line in SECRETS_FILE.read_text(encoding="utf-8").splitlines():
            key, _, value = line.partition("=")
            if key.strip() == name:
                return value.strip().strip("'\"")
    except OSError:
        pass
    return _mcp_secret(name)


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
    """Store a key in secrets.env with owner-only permissions (or drop it when value is empty)."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    lines = []
    try:
        lines = [ln for ln in SECRETS_FILE.read_text(encoding="utf-8").splitlines() if not ln.startswith(f"{name}=")]
    except OSError:
        pass
    if value:
        lines.append(f"{name}={value}")
    SECRETS_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    SECRETS_FILE.chmod(0o600)


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
        "max_utterance_seconds": 40,
        "silence_seconds": 1.0,
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
        # ElevenLabs (engine = "elevenlabs"): the key lives in ~/.config/justday/secrets.env, never here.
        "eleven_voice": "JBFqnCBsd6RMkjVDRZzb",  # `justday voice eleven` lists the voices on your account
        "eleven_model": "eleven_flash_v2_5",  # flash = fastest; eleven_multilingual_v2 = richer, slower
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
    "wakeword": {"enabled": False, "names": True, "wake_names": [], "model": "hey_jarvis",
                 "threshold": 0.5, "threshold_while_playing": 0.7},
    "brain": {
        # claude | ollama | openrouter | deepseek | custom — see `justday model list`
        "provider": "claude",
        "base_url": "",  # only for provider = "custom"
        "context_tokens": 0,  # model context window for non-Claude providers (0 = provider default)
        "model": "sonnet",
        "effort": "low",
        "permission_mode": "auto",
        "chrome": True,
        # Схемы инструментов в контексте: on — подгружаются по мере надобности (стартовый контекст
        # втрое меньше, а значит и счёт), auto — решает Claude Code, off — все схемы сразу.
        "tool_search": "on",
        # Потолок разговора в токенах: дойдя до него, Claude Code сжимает историю и продолжает.
        # 200 000 — окно, за которым начинается вдвое более дорогой тариф; 0 = как решит Claude Code.
        "context_window": 200000,
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
    "ui": {"notifications": True, "face": "auto"},
    # «Я ушёл» closes the open applications and remembers them; «я вернулся» opens them again.
    # keep: what is never closed (a substring of the window class or the application name).
    # История буфера обмена для панели на островке. Пароли в неё не попадают: то, что программа
    # пометила как секрет, и то, что похоже на ключ, не запоминается вовсе — см. clipboard.py.
    # history = false выключает её целиком, и наблюдатель за буфером даже не запускается.
    "clipboard": {"history": True},
    "session": {"keep": ["kitty"]},
    "updates": {"check": True, "interval_hours": 6},
    # personal voice profile (Settings → Голос и звук → «Настроить под мой голос»)
    "voiceprint": {"mode": "off"},  # off | wake (only wake word / follow-ups must be you) | always
    # Dynamic Island look & feel (applied live)
    "island": {
        "animations": "spring",  # spring (Apple-like bounce) | smooth | off
        "hover_reveal": True,  # hover the top edge to show the island
        "show_weather": True,
        "show_events": True,  # last answer / new mail / Claude status in the hover view
        "show_notifications": True,  # mirror desktop notifications on the island (they never leave the computer)
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
    # значок меню в начале. position: bottom | top; reserve — отнимать место у развёрнутых окон.
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
        # Отнимать место у окон плазма понимает буквально: обои тоже сжимаются, и под доком
        # остаётся чёрная полоса. Поэтому по умолчанию док просто лежит поверх — как на макоси.
        "reserve": False,
        "show_running": True,   # открытые окна незакреплённых программ
        "show_trash": True,
        # Подписи: off — нет совсем, hover — под курсором, always — имя под каждым значком.
        # true и false тоже понимаются: это прежние «под курсором» и «нет».
        "labels": "hover",
        # Чем отмечено открытое: dot (точка), line (чёрточка), bar (полоса), glow (свечение за
        # значком), none (ничем).
        "indicator": "dot",
        # Окно во весь экран прячет док, даже если прятаться его не просили: игра и кино на то и
        # полный экран. Позвать обратно — кромкой, как любой прячущийся док.
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
             "magnify": True, "magnify_scale": 60, "magnify_spread": 160},
    # Accessibility bus on: Qt/GTK apps expose their buttons, so `look` can mark them for exact clicks.
    "desktop": {"accessibility": True},
    # Local model for private data (mail). Ollama listens on localhost only.
    "local_llm": {"url": "http://127.0.0.1:11434", "model": "qwen3.5:9b", "num_ctx": 16384, "keep_alive": "10m"},
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
    cfg = DEFAULTS
    if CONFIG_FILE.exists():
        with CONFIG_FILE.open("rb") as f:
            cfg = _merge(DEFAULTS, tomllib.load(f))
    return cfg


def _toml_value(v) -> str:
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, (int, float)):
        return str(v)
    if isinstance(v, (list, tuple)):
        return "[" + ", ".join(_toml_value(x) for x in v) + "]"
    return json.dumps(str(v), ensure_ascii=False)


def set_value(section: str, key: str, value) -> None:
    """Set one key in config.toml, keeping the user's comments and layout."""
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    lines = CONFIG_FILE.read_text(encoding="utf-8").splitlines() if CONFIG_FILE.exists() else []
    line = f"{key} = {_toml_value(value)}"
    header = f"[{section}]"
    try:
        start = next(i for i, l in enumerate(lines) if l.strip() == header)
    except StopIteration:
        lines += ["", header, line]
    else:
        end = next((i for i in range(start + 1, len(lines)) if lines[i].lstrip().startswith("[")), len(lines))
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
