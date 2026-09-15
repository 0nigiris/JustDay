"""`justday setup` — the first-run wizard: name, model, voice, microphone, button, mail, weather.

Plain terminal prompts (no extra dependencies). Every step can be skipped with Enter and redone later
in the Settings panel of the Dynamic Island.
"""
from __future__ import annotations

import getpass
import json
import shutil
import subprocess
import sys

from . import config, manage, providers

B, D, G, Y, C, R = "\033[1m", "\033[2m", "\033[32m", "\033[33m", "\033[36m", "\033[0m"

WIZ_EN = {
    "введите число от 1 до {n}": "enter a number from 1 to {n}", " (Д/н)": " (Y/n)", " (д/Н)": " (y/N)",
    "Знакомство": "Getting to know you", "Как зовут ассистента": "Assistant name",
    "Другие имена (через запятую)": "Other names (comma-separated)", "Как ему обращаться к вам": "How it should address you",
    "Ваше имя (для подписи в письмах)": "Your name (to sign emails)", "Модель — кто будет думать": "Model — who does the thinking",
    "Claude по подписке Pro/Max — лучшее качество": "Claude with a Pro/Max subscription — best quality",
    "(вход выполнен)": "(signed in)", "Локальная модель на видеокарте — бесплатно и приватно": "Local model on your GPU — free and private",
    "(нужно ≥10 ГБ видеопамяти)": "(needs ≥10 GB VRAM)", "OpenRouter — есть бесплатные модели, нужен ключ": "OpenRouter — free models available, needs a key",
    "DeepSeek — дёшево, нужен ключ": "DeepSeek — cheap, needs a key", "Выберите": "Choose",
    "Сейчас откроется Claude Code: выполните {a}, затем {b}.": "Claude Code will open now: run {a}, then {b}.", "Открыть": "Open",
    "Ставлю Ollama и модель Qwen 3.5 9B (~8 ГБ)…": "Installing Ollama and the Qwen 3.5 9B model (~8 GB)…",
    "Ключ создаётся здесь: {url}": "Create a key here: {url}", "  Вставьте ключ (ввод скрыт): ": "  Paste the key (hidden): ",
    "модель: {m}": "model: {m}", "Голос": "Voice", "Какой голос": "Which voice",
    "Нейросетевой, живой (Qwen3-TTS, загрузка ~4 ГБ)": "Neural, natural (Qwen3-TTS, ~4 GB download)",
    "Простой и быстрый (Silero, звучит роботизированно)": "Simple and fast (Silero, Russian only, sounds robotic)",
    "Для нейросетевого голоса нужна видеокарта NVIDIA с 8 ГБ — ставлю простой голос.": "The neural voice needs an 8 GB NVIDIA GPU — using the simple voice.",
    "Джарвис — спокойный баритон, манера дворецкого": "Jarvis — calm baritone, butler manner",
    "Пятница — тёплый живой женский голос": "Friday — warm, lively female voice", "Микрофон": "Microphone",
    "Микрофоны не найдены — будет использован системный по умолчанию.": "No microphones found — the system default will be used.",
    "Системный по умолчанию": "System default", "Какой микрофон": "Which microphone", "Кнопка": "Button",
    "Сочетание, чтобы говорить": "Shortcut to talk",
    "Кнопка на мыши: игровые мыши Logitech можно перепрошить на F19 (см. руководство, раздел «Установка»).": "Mouse button: Logitech gaming mice can be remapped to F19 (see the manual, “Installation”).",
    "Вторая клавиша «говорить» (например F19, пусто — нет)": "Second talk key (e.g. F19, empty — none)",
    "Сочетание «отменить всё»": "Shortcut to cancel everything", "сочетания зарегистрированы": "shortcuts registered",
    "не получилось: {e}": "failed: {e}",
    "Нажмите — слушает до паузы; зажмите — пока держите; нажмите дважды — отмена.": "Press — listens until you pause; hold — while held; double press — cancel.",
    "Почта (по желанию)": "Mail (optional)",
    "Письма читает локальная модель, в облако ничего не уходит. Нужен пароль приложения Google.": "Emails are read by a local model, nothing goes to the cloud. Needs a Google app password.",
    "Подключить Gmail сейчас": "Connect Gmail now", "Для почты нужна локальная модель — ставлю…": "Mail needs the local model — installing…",
    "Погода на острове": "Weather on the island", "Ваш город (пусто — без погоды)": "Your city (empty — no weather)",
    "JustDay — первая настройка": "JustDay — first setup",
    "(Enter — оставить как есть; всё меняется потом в настройках острова)": "(Enter keeps the value; everything can be changed later in the island settings)",
    "пропущено": "skipped", "Перезапускаю JustDay…": "Restarting JustDay…", "Готово!": "Done!",
    "Говорить:   {name} слушает по вашей кнопке — попробуйте «{name}, какая погода?»": "Talk:       {name} listens on your button — try “{name}, what's the weather?”",
    "Настройки:  клик по острову сверху экрана → шестерёнка": "Settings:   click the island at the top of the screen → gear",
    "Если что-то не так: {doctor}, руководство — {manual}": "If something is wrong: {doctor}, manual — {manual}",
    "Настройка прервана. Продолжить: justday setup": "Setup interrupted. Continue with: justday setup",
}


def W(text: str, **kw) -> str:
    out = WIZ_EN.get(text, text) if config.load()["user"].get("language", "ru") == "en" else text
    return out.format(**kw) if kw else out


def title(n: int, text: str) -> None:
    print(f"\n{C}{B}[{n}/7] {text}{R}")


def ask(prompt: str, default: str = "") -> str:
    suffix = f" {D}[{default}]{R}" if default else ""
    try:
        value = input(f"  {prompt}{suffix}: ").strip()
    except EOFError:
        value = ""
    return value or default


def choose(prompt: str, options: list[tuple[str, str]], default: int = 1) -> str:
    for i, (_, label) in enumerate(options, 1):
        print(f"   {B}{i}{R}. {label}")
    while True:
        raw = ask(prompt, str(default))
        if raw.isdigit() and 1 <= int(raw) <= len(options):
            return options[int(raw) - 1][0]
        print(f"  {Y}" + W("введите число от 1 до {n}", n=len(options)) + R)


def yes(prompt: str, default: bool = True) -> bool:
    raw = ask(prompt + (W(" (Д/н)") if default else W(" (д/Н)")), "").lower()
    return default if not raw else raw.startswith(("д", "y"))


def sh(cmd: list[str]) -> bool:
    return subprocess.run(cmd).returncode == 0


def vram_mb() -> int:
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.total", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=5).stdout
        return int(out.split()[0])
    except (OSError, ValueError, IndexError, subprocess.TimeoutExpired):
        return 0


def step_names() -> None:
    title(1, W("Знакомство"))
    u = config.load()["user"]
    name = ask(W("Как зовут ассистента"), u["assistant_name"])
    aliases = ask(W("Другие имена (через запятую)"), ", ".join(u.get("assistant_aliases", [])))
    config.set_value("user", "assistant_name", name)
    config.set_value("user", "assistant_aliases", [a.strip() for a in aliases.split(",") if a.strip()])
    config.set_value("user", "address_as", ask(W("Как ему обращаться к вам"), u["address_as"]))
    config.set_value("user", "name", ask(W("Ваше имя (для подписи в письмах)"), u.get("name", "")))


def step_model() -> None:
    title(2, W("Модель — кто будет думать"))
    status = {}
    if shutil.which("claude"):
        try:
            status = json.loads(subprocess.run(["claude", "auth", "status"], capture_output=True, text=True, timeout=20).stdout or "{}")
        except (json.JSONDecodeError, subprocess.TimeoutExpired):
            status = {}
    big_gpu = vram_mb() >= 10000
    options = [
        ("claude", W("Claude по подписке Pro/Max — лучшее качество") + (f" {G}" + W("(вход выполнен)") + R if status.get("loggedIn") else "")),
        ("ollama", W("Локальная модель на видеокарте — бесплатно и приватно") + ("" if big_gpu else f" {Y}" + W("(нужно ≥10 ГБ видеопамяти)") + R)),
        ("openrouter", W("OpenRouter — есть бесплатные модели, нужен ключ")),
        ("deepseek", W("DeepSeek — дёшево, нужен ключ")),
    ]
    provider = choose(W("Выберите"), options, 1)
    if provider == "claude":
        config.set_value("brain", "provider", "claude")
        config.set_value("brain", "model", "sonnet")
        if not status.get("loggedIn"):
            print("  " + W("Сейчас откроется Claude Code: выполните {a}, затем {b}.", a=f"{B}/login{R}", b=f"{B}/exit{R}"))
            if yes(W("Открыть")):
                sh(["claude"])
    elif provider == "ollama":
        if not manage.local_models():
            print("  " + W("Ставлю Ollama и модель Qwen 3.5 9B (~8 ГБ)…"))
            sh([str(config.REPO_DIR / "scripts" / "setup-local-llm.sh")])
        config.set_value("brain", "provider", "ollama")
        config.set_value("brain", "model", (manage.local_models() or ["qwen3.5:9b"])[0])
    else:
        url = {"openrouter": "https://openrouter.ai/keys", "deepseek": "https://platform.deepseek.com/api_keys"}[provider]
        print("  " + W("Ключ создаётся здесь: {url}", url=f"{B}{url}{R}"))
        key = getpass.getpass(W("  Вставьте ключ (ввод скрыт): ")).strip()
        if key:
            providers.secret_set(provider, key)
        config.set_value("brain", "provider", provider)
        config.set_value("brain", "model", manage.MODELS[provider][0])
    print(f"  {G}✓{R} " + W("модель: {m}", m=f"{config.load()['brain']['provider']} / {config.load()['brain']['model']}"))


def step_voice() -> None:
    title(3, W("Голос"))
    if vram_mb() >= 8000:
        engine = choose(W("Какой голос"), [("qwen", W("Нейросетевой, живой (Qwen3-TTS, загрузка ~4 ГБ)")),
                                            ("silero", W("Простой и быстрый (Silero, звучит роботизированно)"))], 1)
    else:
        print(f"  {D}" + W("Для нейросетевого голоса нужна видеокарта NVIDIA с 8 ГБ — ставлю простой голос.") + R)
        engine = "silero"
    if engine == "qwen":
        installed = manage.voices()["neural_available"] or sh([str(config.REPO_DIR / "scripts" / "setup-voice.sh")])
        if installed:
            voice = choose(W("Голос"), [("jarvis", W("Джарвис — спокойный баритон, манера дворецкого")),
                                        ("friday", W("Пятница — тёплый живой женский голос"))], 1)
            config.set_value("tts", "voice", voice)
        else:
            engine = "silero"
    config.set_value("tts", "engine", engine)


def step_mic() -> None:
    title(4, W("Микрофон"))
    sources = manage.audio_devices()["sources"]
    if not sources:
        print(f"  {Y}" + W("Микрофоны не найдены — будет использован системный по умолчанию.") + R)
        return
    options = [("", W("Системный по умолчанию"))] + [(s["name"], s["description"]) for s in sources]
    current = config.load()["audio"]["input"]
    default = next((i for i, (name, _) in enumerate(options, 1) if current and current.lower() in name.lower()), 1)
    config.set_value("audio", "input", choose(W("Какой микрофон"), options, default))


def step_button() -> None:
    title(5, W("Кнопка"))
    talk = ask(W("Сочетание, чтобы говорить"), "Meta+J")
    print(f"  {D}" + W("Кнопка на мыши: игровые мыши Logitech можно перепрошить на F19 (см. руководство, раздел «Установка»).") + R)
    extra = ask(W("Вторая клавиша «говорить» (например F19, пусто — нет)"), "F19")
    cancel = ask(W("Сочетание «отменить всё»"), "Meta+Shift+J")
    r = manage.set_hotkeys(talk, extra, cancel)
    print(f"  {G}✓{R} " + (W("сочетания зарегистрированы") if r["ok"] else Y + W("не получилось: {e}", e=r["output"]) + R))
    print(f"  {D}" + W("Нажмите — слушает до паузы; зажмите — пока держите; нажмите дважды — отмена.") + R)


def step_mail() -> None:
    title(6, W("Почта (по желанию)"))
    print(f"  {D}" + W("Письма читает локальная модель, в облако ничего не уходит. Нужен пароль приложения Google.") + R)
    if not yes(W("Подключить Gmail сейчас"), False):
        return
    if not manage.local_models():
        print(f"  {Y}" + W("Для почты нужна локальная модель — ставлю…") + R)
        sh([str(config.REPO_DIR / "scripts" / "setup-local-llm.sh")])
    sh([sys.executable, "-m", "justday.cli", "mail", "setup"])


def step_weather() -> None:
    title(7, W("Погода на острове"))
    city = ask(W("Ваш город (пусто — без погоды)"), config.load()["island"].get("city", ""))
    config.set_value("island", "city", city)


def run_wizard() -> None:
    print("\nLanguage / Язык:  1. Русский   2. English")
    choice = ask("1/2", "2" if config.load()["user"].get("language") == "en" else "1")
    lang = "en" if choice.strip() == "2" else "ru"
    config.set_value("user", "language", lang)
    config.set_value("stt", "language", lang)
    if lang == "en" and config.load()["user"]["address_as"] == "сэр":
        config.set_value("user", "address_as", "sir")
    print(f"\n{B}" + W("JustDay — первая настройка") + f"{R}  {D}" + W("(Enter — оставить как есть; всё меняется потом в настройках острова)") + R)
    for step in (step_names, step_model, step_voice, step_mic, step_button, step_mail, step_weather):
        try:
            step()
        except KeyboardInterrupt:
            print(f"\n  {Y}" + W("пропущено") + R)
    print(f"\n{C}" + W("Перезапускаю JustDay…") + R)
    subprocess.run(["systemctl", "--user", "restart", "justday.service"], capture_output=True)
    for unit in ("justday-island.service", "justday-voice.service"):
        subprocess.run(["systemctl", "--user", "try-restart", unit], capture_output=True)
    name = config.load()["user"]["assistant_name"]
    print(f"\n{G}{B}" + W("Готово!") + R)
    print("  " + W("Говорить:   {name} слушает по вашей кнопке — попробуйте «{name}, какая погода?»", name=name))
    print("  " + W("Настройки:  клик по острову сверху экрана → шестерёнка"))
    print("  " + W("Если что-то не так: {doctor}, руководство — {manual}", doctor=f"{B}justday doctor{R}",
                   manual=config.REPO_DIR / "docs" / "MANUAL.md") + "\n")


def run() -> None:
    try:
        run_wizard()
    except KeyboardInterrupt:
        print("\n" + W("Настройка прервана. Продолжить: justday setup"))
