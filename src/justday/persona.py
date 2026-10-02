"""Who the assistant is: its character, apart from what it can do.

Not everyone wants a butler. The rules (act instead of explaining, stay short, keep secrets) live in
brain/PERSONA.md and are the same for everyone; the character — how it talks, whether it says «сэр» or
«брат», whether it swears, whether it speaks with the pauses and slips of a live person — is chosen here
and put into that file's {character} slot.
"""
from __future__ import annotations

from . import config

PRESETS = ("jarvis", "friend", "calm", "custom")
DEFAULT_ADDRESS = ("сэр", "брат", "sir", "bro", "")   # what the presets set: anything else was chosen by hand
DIR = config.REPO_DIR / "brain" / "characters"

EXTRAS = {
    "ru": {
        "swearing": "Можно материться — к месту и естественно, как в живом разговоре с другом: не через слово и "
                    "никогда всерьёз в адрес пользователя.",
        "clean": "Без мата.",
        "live_speech": "Говори как человек вслух, а не как текст: паузы (многоточие), «ну», «так», «э-э», "
                       "оговорки и поправки на ходу («а, да, точно… как я мог забыть»). Это живость, а не вода: "
                       "ответ всё равно короткий и по делу.",
    },
    "en": {
        "swearing": "Swearing is fine — natural and in place, the way friends talk: not every other word, and "
                    "never seriously at the user.",
        "clean": "No swearing.",
        "live_speech": "Talk like a person speaking, not like written text: pauses (an ellipsis), \"well\", "
                       "\"uh\", little slips and corrections on the fly (\"oh, right… how did I forget\"). "
                       "Liveliness, not padding: the answer stays short.",
    },
}


def character(cfg: dict) -> str:
    """The text for PERSONA.md's {character} slot, in the assistant's language."""
    p = cfg.get("persona") or {}
    lang = cfg["user"].get("language", "ru")
    lang = lang if lang in EXTRAS else "ru"
    name = p.get("character", "jarvis")
    text = (p.get("custom") or "").strip() if name == "custom" else ""
    if not text:
        name = name if name in PRESETS and name != "custom" else "jarvis"
        path = DIR / (f"{name}.md" if lang == "ru" else f"{name}.{lang}.md")
        text = (path if path.exists() else DIR / f"{name}.md").read_text(encoding="utf-8").strip()
    extra = EXTRAS[lang]
    lines = [text, extra["swearing"] if p.get("swearing") else extra["clean"]]
    if p.get("live_speech"):
        lines.append(extra["live_speech"])
    return "\n".join(lines)


# ──────────────────────────── что он умеет на этой машине ────────────────────────────
#
# Зачем это здесь. Умения ассистента описаны в PERSONA.md словами, а что из них **включено** —
# знает только конфиг. Из-за этого он не знал, что у него есть история буфера обмена и выбиралка
# эмодзи: ему про них никто не сказал, а сам он их не видит. Человек просил «скажите ему, что он
# умеет», и правильный ответ — не дописать абзац руками, а собирать его из того, что реально
# работает: выключенное из списка должно пропадать само, иначе он начнёт обещать несуществующее.
#
# Каждая строка — одно умение: как его позвать и что оно делает. Без вариантов «можно также» —
# список читается моделью перед каждым разговором, и каждое лишнее слово в нём стоит токенов на
# каждом ходу.
ABILITIES: list[tuple[str, str, str]] = [
    ("clipboard.history", "История буфера обмена: `justday clip` — панель на островке; пароли в неё не попадают.",
     "Clipboard history: `justday clip` — a panel on the island; passwords never get in."),
    ("", "Эмодзи: `justday emoji` — поиск по-русски, вставка в то окно, где курсор.",
     "Emoji: `justday emoji` — search and insert into the window with the cursor."),
    ("", "Нагрузка машины: `justday load` — процессор, память, видеокарта, диски, сеть.",
     "Machine load: `justday load` — CPU, memory, GPU, disks, network."),
    ("", "Громкость по программам: `justday tools mixer` — микшер на островке.",
     "Per-app volume: `justday tools mixer` — the mixer on the island."),
    ("dock.enabled", "Док: `justday dock pin|unpin <id>`, `justday dock go N` — N-я программа слева.",
     "Dock: `justday dock pin|unpin <id>`, `justday dock go N` — the Nth app from the left."),
    ("tray.enabled", "Лоток: чужие значки полосой у края; `justday config set tray.hidden ...` прячет лишние.",
     "Tray: other apps' icons in a strip; `justday config set tray.hidden ...` hides the extra ones."),
    ("", "Окна: `justday windows list|focus|close|minimize`, `justday apps`, `justday games`.",
     "Windows: `justday windows list|focus|close|minimize`, `justday apps`, `justday games`."),
    ("", "Снимок экрана: `justday screenshot`; нажатия и клавиши: `justday click`, `justday keys`.",
     "Screenshot: `justday screenshot`; clicks and keys: `justday click`, `justday keys`."),
    ("notes.plans", "Планы: `justday plan` — они лежат в Obsidian, островок их только показывает и отмечает.",
     "Plans: `justday plan` — they live in Obsidian; the island only shows and ticks them."),
    ("", "Живые сессии Claude Code: страница «Клод» на островке — что каждая делает прямо сейчас.",
     "Live Claude Code sessions: the «Claude» page on the island — what each one is doing now."),
    ("media.show_player", "Музыка и видео: `justday play`, `justday player`, `justday video`.",
     "Music and video: `justday play`, `justday player`, `justday video`."),
    ("mail.address", "Почта и календарь: `justday mail`, `justday calendar`, `justday contacts`.",
     "Mail and calendar: `justday mail`, `justday calendar`, `justday contacts`."),
    ("", "Память: `justday memory` — она в файлах на диске и переживает перезапуск.",
     "Memory: `justday memory` — files on disk; it survives a restart."),
    ("", "Напоминания и таймеры: `justday timer`, `justday alarm`, `justday reminders`.",
     "Reminders and timers: `justday timer`, `justday alarm`, `justday reminders`."),
    ("", "Режим сервера: `justday server on` — экраны гаснут, звук глохнет, машина не засыпает, "
         "а работа идёт дальше. `justday server off` возвращает всё. Включай, когда он ушёл, а "
         "работа осталась, и обязательно выключай, закончив.",
     "Server mode: `justday server on` — screens off, sound muted, no sleep, work continues. "
     "`justday server off` restores everything. Turn it on when he leaves work running, and off "
     "when it is done."),
    ("", "Дотянуться до него, когда его нет за компьютером: `justday reach \"текст\"` — письмо; "
         "`--urgent` — ещё и звонок на телефон. Звонок только ради того, что правда не ждёт.",
     "Reach him when he is away from the computer: `justday reach \"text\"` — email; "
     "`--urgent` also rings the phone. Ring only for what truly cannot wait."),
]


def _on(cfg: dict, path: str) -> bool:
    """Включено ли то, что стоит за этим ключом. Пустой ключ — умение есть всегда."""
    if not path:
        return True
    node: object = cfg
    for part in path.split("."):
        if not isinstance(node, dict) or part not in node:
            return False
        node = node[part]
    if isinstance(node, bool):
        return node
    return bool(node)


def abilities(cfg: dict) -> str:
    """Список включённых умений для слота {abilities} в PERSONA.md, на языке человека."""
    en = cfg.get("user", {}).get("language", "ru") != "ru"
    return "\n".join(f"- {row[2] if en else row[1]}" for row in ABILITIES if _on(cfg, row[0]))
