"""Куда идти, когда у Claude кончился лимит.

Сейчас при любом отказе мозга демон сваливался в скудный местный режим: четыре умения и честное
«облако недоступно». Для обрыва сети это правильно, а для исчерпанного лимита — нет: лимит кончается
предсказуемо, раз в несколько часов, и всё это время у человека есть бесплатные модели, которые
прекрасно откроют ему дискорд и ответят на вопрос.

Поэтому отказ сначала разбирается: сеть упала или именно лимит. Лимит — переходим к следующему
поставщику из списка и продолжаем работать. Сеть — местный режим, как и был.

Чего здесь нет: попыток угадать, когда лимит восстановится. Claude не говорит этого внятно, а
гадать и возвращаться раньше времени значит получить второй отказ в середине разговора. Возврат
делается по времени, которое человек задал сам, и вручную.
"""
from __future__ import annotations

import logging
import re

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
