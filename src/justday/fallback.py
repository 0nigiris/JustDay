"""Куда идти, когда у Claude кончился лимит.

Сейчас при любом отказе мозга демон сваливался в скудный местный режим: четыре умения и честное
«облако недоступно». Для обрыва сети это правильно, а для исчерпанного лимита — нет: лимит кончается
предсказуемо, раз в несколько часов, и всё это время у человека есть бесплатные модели, которые
прекрасно откроют ему дискорд и ответят на вопрос.

Поэтому отказ сначала разбирается: сеть упала или именно лимит. Лимит — переходим к следующему
поставщику из списка и продолжаем работать. Сеть — местный режим, как и был.

Возврат наверх. Поставщики стоят лестницей: первый — тот, кем хочется думать всегда, дальше по
убыванию. Уйдя вниз, мы не остаёмся там навсегда и не гадаем, когда лимит вернётся: раз в
четверть часа мы просто **спрашиваем** верхнего — одним словом, не разговором. Ответил — значит
лимит вернулся, и мы поднимаемся обратно. Молчит — остаёмся работать там, где работаем, и
спросим ещё раз позже. Угадывание заменено проверкой, потому что угадывание стоит отказа в
середине разговора, а проверка — одного слова.
"""
from __future__ import annotations

import logging
import os
import re
import shutil
import subprocess

from . import providers

log = logging.getLogger("justday.fallback")

# Чем лимит отличается от обрыва связи — по тому, что говорит сам отказ. Список нарочно широкий:
# разные поставщики называют одно и то же по-разному, а ошибиться здесь в сторону «это лимит»
# безопаснее, чем в сторону «это сеть»: в худшем случае мы перейдём на запасного и будем работать.
_LIMIT = re.compile(
    r"(rate[_ ]?limit|usage limit|quota|credit|insufficient|billing|payment required|"
    r"429|529|overloaded|capacity|too many requests|limit reached|exhaust)", re.I)
# А это именно связь: тут запасной не поможет, он в том же интернете.
_NETWORK = re.compile(
    r"(connection refused|network is unreachable|name or service not known|timed out|"
    r"temporary failure in name resolution|no route to host|ssl)", re.I)


def looks_like_limit(error: str) -> bool:
    text = str(error or "")
    if _NETWORK.search(text):
        return False
    return bool(_LIMIT.search(text))


def usable(name: str) -> bool:
    """Можно ли на него перейти прямо сейчас: есть ключ или он вовсе не нужен."""
    p = providers.PROVIDERS.get(name)
    if p is None:
        return False
    if not p.get("secret"):
        return True
    return bool(providers.secret_get(p["secret"]))


def next_provider(cfg: dict) -> tuple[str, str] | None:
    """Следующий поставщик и модель к нему. None — переходить некуда.

    Порядок задаёт человек в настройках: он один знает, что у него оплачено, что бесплатно и чем он
    готов пользоваться. Мы только пропускаем тех, у кого нет ключа, — предлагать переход, который
    тут же упрётся в «нет ключа», значит тратить ещё одну попытку впустую.
    """
    from . import manage

    b = cfg["brain"]
    now = b.get("provider", "claude")
    chain = [str(x) for x in (b.get("fallbacks") or [])]
    try:
        start = chain.index(now) + 1
    except ValueError:
        start = 0
    for name in chain[start:]:
        if name == now or not usable(name):
            continue
        model = (b.get("fallback_models") or {}).get(name) or (manage.MODELS.get(name) or [""])[0]
        if not model:
            continue
        return name, model
    return None


def ladder(cfg: dict) -> list[str]:
    """Поставщики по убыванию предпочтения: сначала основной, потом запасные в порядке списка.

    Это и есть «приоритеты»: наверху тот, кем хочется думать всегда, ниже — те, кем можно, пока
    верхний недоступен. Человек задаёт порядок сам: он один знает, что у него оплачено и чем он
    готов пользоваться.
    """
    b = cfg["brain"]
    home = str(b.get("home_provider") or "claude")
    out = [home]
    for name in (b.get("fallbacks") or []):
        name = str(name)
        if name and name not in out:
            out.append(name)
    return out


def model_for(cfg: dict, name: str) -> str:
    """Какой моделью думать у этого поставщика."""
    from . import manage

    b = cfg["brain"]
    if name == str(b.get("home_provider") or "claude"):
        return str(b.get("light_model") or b.get("model") or "haiku")
    chosen = (b.get("fallback_models") or {}).get(name)
    return str(chosen or (manage.MODELS.get(name) or [""])[0] or "")


def better_than(cfg: dict, name: str = "") -> tuple[str, str] | None:
    """Кто стоит в лестнице выше текущего и годится прямо сейчас. None — выше никого нет."""
    b = cfg["brain"]
    now = name or str(b.get("provider", "claude"))
    chain = ladder(cfg)
    try:
        stop = chain.index(now)
    except ValueError:
        stop = len(chain)
    for better in chain[:stop]:
        if not usable(better):
            continue
        model = model_for(cfg, better)
        if model or better == "claude":
            return better, model
    return None


def probe(cfg: dict, name: str, model: str = "", timeout: float = 45.0) -> bool:
    """Отвечает ли поставщик прямо сейчас.

    Один крошечный вопрос отдельным процессом, а не переподключение мозга: переподключиться,
    чтобы выяснить, что лимит ещё не вернулся, значит остаться без мозга на те же полторы секунды
    и потом вернуться обратно — и так каждые пятнадцать минут.
    """
    b = dict(cfg["brain"])
    b["provider"] = name
    if model:
        b["model"] = model
    cli = shutil.which(str(b.get("claude_cli") or "claude")) or str(b.get("claude_cli") or "claude")
    if not shutil.which(cli) and not os.path.exists(cli):
        return False
    try:
        env = {**os.environ, **providers.env({**cfg, "brain": b})}
    except (ValueError, RuntimeError) as e:
        log.debug("не вышло собрать окружение для %s: %s", name, e)
        return False
    cmd = [cli, "-p", "ok", "--max-turns", "1"]
    if b.get("model"):
        cmd += ["--model", str(b["model"])]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout, env=env,
                           cwd=os.path.expanduser("~"))
    except (OSError, subprocess.SubprocessError) as e:
        log.debug("проверка %s не удалась: %s", name, type(e).__name__)
        return False
    said = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0 or looks_like_limit(said):
        log.debug("%s ещё не отвечает: %s", name, said.strip()[:120])
        return False
    return bool(said.strip())
