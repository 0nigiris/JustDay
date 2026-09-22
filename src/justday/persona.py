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
