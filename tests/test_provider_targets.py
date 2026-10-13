"""13 октября в выбор провайдера добавили Groq, Cerebras, Gemini, Mistral и Cohere «через LiteLLM на
порту 4000», но LiteLLM никто не ставил и не запускал: выбравший такой пункт оставался без мозга.
Локальный адрес у провайдера допустим только тот, где действительно работает наша служба."""
from urllib.parse import urlparse

from justday import manage, providers

OURS = {11434}  # ollama — её ставит и запускает установщик


def test_every_local_provider_points_at_a_service_we_run():
    for name, p in providers.PROVIDERS.items():
        u = urlparse(p.get("base_url", ""))
        if u.hostname in ("127.0.0.1", "localhost"):
            assert u.port in OURS, f"{name} смотрит в {p['base_url']}, а там никого нет"


def test_suggested_models_only_for_known_providers():
    assert set(manage.MODELS) <= set(providers.PROVIDERS) | {"claude"}
