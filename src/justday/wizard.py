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
        print(f"  {Y}введите число от 1 до {len(options)}{R}")


def yes(prompt: str, default: bool = True) -> bool:
    raw = ask(prompt + (" (Д/н)" if default else " (д/Н)"), "").lower()
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
    title(1, "Знакомство")
    u = config.load()["user"]
    name = ask("Как зовут ассистента", u["assistant_name"])
    aliases = ask("Другие имена (через запятую)", ", ".join(u.get("assistant_aliases", [])))
    config.set_value("user", "assistant_name", name)
    config.set_value("user", "assistant_aliases", [a.strip() for a in aliases.split(",") if a.strip()])
    config.set_value("user", "address_as", ask("Как ему обращаться к вам", u["address_as"]))
    config.set_value("user", "name", ask("Ваше имя (для подписи в письмах)", u.get("name", "")))


def step_model() -> None:
    title(2, "Модель — кто будет думать")
    status = {}
    if shutil.which("claude"):
        try:
            status = json.loads(subprocess.run(["claude", "auth", "status"], capture_output=True, text=True, timeout=20).stdout or "{}")
        except (json.JSONDecodeError, subprocess.TimeoutExpired):
            status = {}
    big_gpu = vram_mb() >= 10000
    options = [
        ("claude", "Claude по подписке Pro/Max — лучшее качество" + (f" {G}(вход выполнен){R}" if status.get("loggedIn") else "")),
        ("ollama", "Локальная модель на видеокарте — бесплатно и приватно" + ("" if big_gpu else f" {Y}(нужно ≥10 ГБ видеопамяти){R}")),
        ("openrouter", "OpenRouter — есть бесплатные модели, нужен ключ"),
        ("deepseek", "DeepSeek — дёшево, нужен ключ"),
    ]
    provider = choose("Выберите", options, 1)
    if provider == "claude":
        config.set_value("brain", "provider", "claude")
        config.set_value("brain", "model", "sonnet")
        if not status.get("loggedIn"):
            print(f"  Сейчас откроется Claude Code: выполните {B}/login{R}, затем {B}/exit{R}.")
            if yes("Открыть"):
                sh(["claude"])
    elif provider == "ollama":
        if not manage.local_models():
            print("  Ставлю Ollama и модель Qwen 3.5 9B (~8 ГБ)…")
            sh([str(config.REPO_DIR / "scripts" / "setup-local-llm.sh")])
        config.set_value("brain", "provider", "ollama")
        config.set_value("brain", "model", (manage.local_models() or ["qwen3.5:9b"])[0])
    else:
        url = {"openrouter": "https://openrouter.ai/keys", "deepseek": "https://platform.deepseek.com/api_keys"}[provider]
        print(f"  Ключ создаётся здесь: {B}{url}{R}")
        key = getpass.getpass("  Вставьте ключ (ввод скрыт): ").strip()
        if key:
            providers.secret_set(provider, key)
        config.set_value("brain", "provider", provider)
        config.set_value("brain", "model", manage.MODELS[provider][0])
    print(f"  {G}✓{R} модель: {config.load()['brain']['provider']} / {config.load()['brain']['model']}")


def step_voice() -> None:
    title(3, "Голос")
    if vram_mb() >= 8000:
        engine = choose("Какой голос", [("qwen", "Нейросетевой, живой (Qwen3-TTS, загрузка ~4 ГБ)"),
                                         ("silero", "Простой и быстрый (Silero, звучит роботизированно)")], 1)
    else:
        print(f"  {D}Для нейросетевого голоса нужна видеокарта NVIDIA с 8 ГБ — ставлю простой голос.{R}")
        engine = "silero"
    if engine == "qwen":
        installed = manage.voices()["neural_available"] or sh([str(config.REPO_DIR / "scripts" / "setup-voice.sh")])
        if installed:
            voice = choose("Голос", [("jarvis", "Джарвис — спокойный баритон, манера дворецкого"),
                                     ("friday", "Пятница — тёплый живой женский голос")], 1)
            config.set_value("tts", "voice", voice)
        else:
            engine = "silero"
    config.set_value("tts", "engine", engine)


def step_mic() -> None:
    title(4, "Микрофон")
    sources = manage.audio_devices()["sources"]
    if not sources:
        print(f"  {Y}Микрофоны не найдены — будет использован системный по умолчанию.{R}")
        return
    options = [("", "Системный по умолчанию")] + [(s["name"], s["description"]) for s in sources]
    current = config.load()["audio"]["input"]
    default = next((i for i, (name, _) in enumerate(options, 1) if current and current.lower() in name.lower()), 1)
    config.set_value("audio", "input", choose("Какой микрофон", options, default))


def step_button() -> None:
    title(5, "Кнопка")
    talk = ask("Сочетание, чтобы говорить", "Meta+J")
    print(f"  {D}Кнопка на мыши: игровые мыши Logitech можно перепрошить на F19 (см. руководство, раздел «Установка»).{R}")
    extra = ask("Вторая клавиша «говорить» (например F19, пусто — нет)", "F19")
    cancel = ask("Сочетание «отменить всё»", "Meta+Shift+J")
    r = manage.set_hotkeys(talk, extra, cancel)
    print(f"  {G}✓{R} " + ("сочетания зарегистрированы" if r["ok"] else f"{Y}не получилось: {r['output']}{R}"))
    print(f"  {D}Нажмите — слушает до паузы; зажмите — пока держите; нажмите дважды — отмена.{R}")


def step_mail() -> None:
    title(6, "Почта (по желанию)")
    print(f"  {D}Письма читает локальная модель, в облако ничего не уходит. Нужен пароль приложения Google.{R}")
    if not yes("Подключить Gmail сейчас", False):
        return
    if not manage.local_models():
        print(f"  {Y}Для почты нужна локальная модель — ставлю…{R}")
        sh([str(config.REPO_DIR / "scripts" / "setup-local-llm.sh")])
    sh([sys.executable, "-m", "justday.cli", "mail", "setup"])


def step_weather() -> None:
    title(7, "Погода на острове")
    city = ask("Ваш город (пусто — без погоды)", config.load()["island"].get("city", ""))
    config.set_value("island", "city", city)


def run_wizard() -> None:
    print(f"\n{B}JustDay — первая настройка{R}  {D}(Enter — оставить как есть; всё меняется потом в настройках острова){R}")
    for step in (step_names, step_model, step_voice, step_mic, step_button, step_mail, step_weather):
        try:
            step()
        except KeyboardInterrupt:
            print(f"\n  {Y}пропущено{R}")
    print(f"\n{C}Перезапускаю JustDay…{R}")
    subprocess.run(["systemctl", "--user", "restart", "justday.service"], capture_output=True)
    for unit in ("justday-island.service", "justday-voice.service"):
        subprocess.run(["systemctl", "--user", "try-restart", unit], capture_output=True)
    name = config.load()["user"]["assistant_name"]
    print(f"""
{G}{B}Готово!{R}
  Говорить:   {B}{config.load()['user']['assistant_name']}{R} слушает по вашей кнопке — попробуйте «{name}, какая погода?»
  Настройки:  клик по острову сверху экрана → шестерёнка
  Если что-то не так: {B}justday doctor{R}, руководство — {config.REPO_DIR / 'docs' / 'MANUAL.md'}
""")


def run() -> None:
    try:
        run_wizard()
    except KeyboardInterrupt:
        print("\nНастройка прервана. Продолжить: justday setup")
