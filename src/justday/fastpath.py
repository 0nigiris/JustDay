"""Instant path: trivial desktop commands handled without an LLM (<0.5 s).

Only unambiguous, whole-utterance commands are handled here ("открой дискорд", "громче", "пауза").
Anything else — or any doubt about the target — returns None and goes to Claude as usual.
The result is reported to the brain as context, so "закрой его" afterwards still works.
"""
from __future__ import annotations

import re
import subprocess

from . import config, desktop
from .i18n import t as _t
from .tts import LEXICON

RU_NAMES = {ru: en for en, ru in LEXICON.items()}
RU_NAMES.update({"телега": "telegram", "вскод": "code", "вс код": "code", "вижуал студио": "code", "дельфин": "dolphin",
                 "кити": "kitty", "спотифай": "spotify", "роблокс": "sober", "обс": "obs", "настройки": "systemsettings",
                 "эквибоп": "equibop", "дискорд": "discord", "стим": "steam", "хироик": "heroic"})

FILLER = re.compile(
    r"\b(джарвис|justday|пожалуйста|плиз|please|быстро|быстренько|давай|ка|ну|мне|теперь|а|приложение|программу|"
    r"сейчас|срочно|сэр|hey|jarvis|could you|can you|would you|sir|the|app|now|quickly)\b", re.I)
REJECT = re.compile(
    r"\b(проект\w*|файл\w*|папк\w*|видео\w*|музык\w*|песн\w*|трек\w*|фильм\w*|вкладк\w*|терминал\w*|в|во|на|про|из|с|"
    r"и|где|что|как|все|всё|последн\w*|вчерашн\w*|там|его|её|ее|их|это|этот|эту|"
    r"projects?|files?|folders?|videos?|music|songs?|tracks?|movies?|tabs?|terminal|in|on|about|from|with|and|where|what|how|"
    r"last|yesterday|there|it|this|that)\b", re.I)

SITES = {
    "ютуб": "https://www.youtube.com", "youtube": "https://www.youtube.com",
    "гитхаб": "https://github.com", "github": "https://github.com",
    "почту": "https://mail.google.com", "почта": "https://mail.google.com", "gmail": "https://mail.google.com",
    "гугл": "https://www.google.com", "google": "https://www.google.com",
    "твич": "https://www.twitch.tv", "twitch": "https://www.twitch.tv",
    "реддит": "https://www.reddit.com", "reddit": "https://www.reddit.com",
    "чатгпт": "https://chatgpt.com", "claude ai": "https://claude.ai", "клод ai": "https://claude.ai",
    "mail": "https://mail.google.com", "my mail": "https://mail.google.com", "chatgpt": "https://chatgpt.com",
}

_TR = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
               ["a", "b", "v", "g", "d", "e", "e", "zh", "z", "i", "y", "k", "l", "m", "n", "o", "p", "r", "s", "t", "u",
                "f", "h", "ts", "ch", "sh", "sch", "", "y", "", "e", "yu", "ya"]))


def _translit(s: str) -> str:
    return "".join(_TR.get(c, c) for c in s.lower())


def _clean(text: str) -> str:
    t = re.sub(r"[^\w\s+-]", " ", text.lower().replace("ё", "е"))
    t = FILLER.sub(" ", t)
    return re.sub(r"\s+", " ", t).strip()


def _run(*cmd: str) -> bool:
    return subprocess.run(cmd, capture_output=True, timeout=5).returncode == 0


def _app(target: str) -> dict | None:
    """Confident app match only: exact name, or a clear winner above 0.8."""
    if not target or len(target.split()) > 3 or REJECT.search(target):
        return None
    aliases = {k.lower(): v for k, v in config.load()["apps"]["aliases"].items()}
    for key in (target, RU_NAMES.get(target, ""), _translit(target)):
        if key in aliases:
            hit = next((a for a in desktop.list_apps() if a["id"] == aliases[key]), None)
            if hit:
                return {**hit, "score": 1.0}
    best: list[dict] = []
    tr = _translit(target)
    for q in {target, RU_NAMES.get(target, target), tr, tr.replace("k", "c"), tr.replace("ks", "x")}:
        best += desktop.find_apps(q, 3)
    best.sort(key=lambda a: -a["score"])
    if not best or best[0]["score"] < 0.8:
        return None
    runner_up = next((a for a in best[1:] if a["id"] != best[0]["id"]), None)
    if best[0]["score"] < 1.0 and runner_up and best[0]["score"] - runner_up["score"] < 0.1:
        return None
    return best[0]


MEDIA = [
    (re.compile(r"^(поставь на паузу|пауза|на паузу|останови (музыку|видео))$"), ("playerctl", "pause"), "пауза"),
    (re.compile(r"^(продолжи|продолжай|играй|сними с паузы|плей)( музыку| видео)?$"), ("playerctl", "play"), "воспроизведение"),
    (re.compile(r"^(следующ\w+|некст|дальше)( трек| песн\w+| видео)?$"), ("playerctl", "next"), "следующий трек"),
    (re.compile(r"^(предыдущ\w+)( трек| песн\w+| видео)?$"), ("playerctl", "previous"), "предыдущий трек"),
    (re.compile(r"^(сделай )?(по)?громче$|^прибавь( звук| громкость)?$"),
     ("wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", "10%+"), "громкость +10%"),
    (re.compile(r"^(сделай )?(по)?тише$|^убавь( звук| громкость)?$"),
     ("wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "10%-"), "громкость −10%"),
    (re.compile(r"^(выключи|отключи|убери) звук$|^без звука$|^замьють$"),
     ("wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1"), "звук выключен"),
    (re.compile(r"^(включи|верни) звук$"), ("wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0"), "звук включён"),
    (re.compile(r"^заблокируй (экран|компьютер|комп|пк)$"), ("loginctl", "lock-session"), "экран заблокирован"),
    # English
    (re.compile(r"^(pause|pause (the )?(music|video)|stop (the )?(music|video))$"), ("playerctl", "pause"), "paused"),
    (re.compile(r"^(play|resume|unpause|continue)( (the )?(music|video))?$"), ("playerctl", "play"), "playing"),
    (re.compile(r"^(next|skip)( (track|song|video))?$"), ("playerctl", "next"), "next track"),
    (re.compile(r"^previous( (track|song|video))?$"), ("playerctl", "previous"), "previous track"),
    (re.compile(r"^(louder|volume up|turn (it )?up)$"), ("wpctl", "set-volume", "-l", "1.0", "@DEFAULT_AUDIO_SINK@", "10%+"), "volume +10%"),
    (re.compile(r"^(quieter|volume down|turn (it )?down)$"), ("wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", "10%-"), "volume −10%"),
    (re.compile(r"^(mute|mute (the )?sound)$"), ("wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "1"), "muted"),
    (re.compile(r"^unmute$"), ("wpctl", "set-mute", "@DEFAULT_AUDIO_SINK@", "0"), "unmuted"),
    (re.compile(r"^lock (the )?(screen|computer|pc)$"), ("loginctl", "lock-session"), "screen locked"),
]


# The assistant's own voice, not the system volume — the daemon owns that switch, so it handles these itself.
VOICE_OFF = re.compile(r"^(выключи|отключи|убери) голос$|^(не говори|молчи|только текст\w*)$|"
                       r"^(voice off|be quiet|stop talking|text only)$")
VOICE_ON = re.compile(r"^(включи|верни) голос$|^говори$|^(voice on|speak up|talk to me)$")


# «Я ушёл» — close the day's windows and remember them; «я вернулся» — open them again.
AWAY = re.compile(r"^(я (ушел|ухожу|убежал|пошел)|"
                  r"закрой (все|всё|лишн\w+|ненужн\w+)( лишн\w+| ненужн\w+)?( программы| приложения| окна)?|"
                  r"i('?m| am) (leaving|off|away)|close (everything|all apps))$")
BACK = re.compile(r"^(я (вернулся|вернулась|тут|на месте|дома)|"
                  r"верни (все|всё)?( как было| приложения| окна| программы)|открой что было|"
                  r"i('?m| am) back|restore (everything|my apps|windows))$")


def session_switch(text: str) -> str | None:
    """"close" for «я ушёл», "restore" for «я вернулся», None when the phrase is about something else."""
    t = _clean(text)
    if AWAY.match(t):
        return "close"
    return "restore" if BACK.match(t) else None


# «Начни заново» — разговор с чистого листа: предыдущий контекст больше не перечитывается
# на каждом шаге, а значит следующая просьба обойдётся в разы дешевле.
# Голое «заново» сюда не входит: это часто «переделай то же самое», а не «забудь всё».
FRESH = re.compile(r"^((начни|начнем|начнём|поговорим)( разговор)? (заново|с нуля|по новой)|с нуля|по новой|"
                   r"нов(ый|ая) (разговор|сессия|тема)|начни новый разговор|"
                   r"забудь (весь )?(разговор|этот разговор|о чем мы говорили|о чём мы говорили)|"
                   r"сбрось (контекст|разговор|сессию)|"
                   r"start (over|fresh|a new (chat|conversation|session))|new (chat|conversation|session)|"
                   r"forget (this|our) (chat|conversation|talk))$")


def wants_fresh_session(text: str) -> bool:
    """«Начни заново», «сбрось контекст» — разговор начинается с чистого листа."""
    return bool(FRESH.match(_clean(text)))


def voice_switch(text: str) -> bool | None:
    """True for «говори», False for «молчи», None when the phrase is not about the voice at all."""
    t = _clean(text)
    if VOICE_OFF.match(t):
        return False
    return True if VOICE_ON.match(t) else None


last_icon = ""  # freedesktop icon of the last handled command (shown by the Dynamic Island)


def try_handle(text: str) -> str | None:
    """Execute the command if it is trivial. Returns a short description of what was done, else None."""
    global last_icon
    last_icon = "audio-volume-high"
    t = _clean(text)
    if not t or len(t) > 60:
        return None
    for rx, cmd, desc in MEDIA:
        if rx.match(t):
            return _t(desc) if _run(*cmd) else None
    m = re.match(r"^(громкость|звук|volume|set volume to|volume to) (на )?(\d{1,3})( процент\w*| percent)?$", t)
    if m:
        return _t("громкость {n}%", n=m.group(3)) if _run("wpctl", "set-volume", "@DEFAULT_AUDIO_SINK@", f"{min(100, int(m.group(3)))}%") else None

    m = re.match(r"^(открой|открыть|запусти|запустить|включи|вруби|open|launch|start|run) (.+)$", t)
    if m:
        target = m.group(2).strip()
        if target in SITES:
            last_icon = "internet-web-browser"
            return _t("открыл {what}", what=SITES[target]) if _run("xdg-open", SITES[target]) else None
        app = _app(target)
        if app:
            last_icon = app.get("icon") or app["id"]
            desktop.launch_app_id(app["id"])
            return _t("запустил {what}", what=app["name"])
        return None

    m = re.match(r"^(закрой|закрыть|выключи|выруби|сверни|свернуть|разверни|переключись на|покажи|close|quit|exit|minimize|"
                 r"switch to|show|focus) (.+)$", t)
    if m:
        verb, target = m.group(1), m.group(2).strip()
        app = _app(target)
        if not app:
            return None
        last_icon = app.get("icon") or app["id"]
        action = {"сверни": "minimize", "свернуть": "minimize", "разверни": "focus", "переключись на": "focus",
                  "покажи": "focus", "minimize": "minimize", "switch to": "focus", "show": "focus", "focus": "focus"}.get(verb, "close")
        for term in (app["name"], app["id"].rsplit(".", 1)[-1], target):
            if desktop.windows(action, term):
                return _t({"close": "закрыл {what}", "minimize": "свернул {what}", "focus": "переключил на {what}"}[action], what=app["name"])
        return None
    return None
