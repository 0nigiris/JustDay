from pathlib import Path

ROOT = Path(__file__).parent.parent


def test_переводчик_не_смотрит_наружу_и_не_хранит_ключей():
    """LiteLLM держит ключи NVIDIA и Cloudflare: на 0.0.0.0 им пользовался бы любой в сети, а ключ в
    конфиге ушёл бы в публичный репозиторий."""
    sh = (ROOT / "scripts/litellm.sh").read_text(encoding="utf-8")
    assert "--host 127.0.0.1" in sh
    cfg = (ROOT / "shell/litellm/config.yaml").read_text(encoding="utf-8")
    keys = [ln for ln in cfg.splitlines() if "api_key:" in ln or "master_key:" in ln]
    assert keys and all("os.environ/" in ln for ln in keys)
    # 13 октября порт 4000 уже обещали без службы; теперь установщик кладёт её сам
    assert "justday-litellm.service" in (ROOT / "install.sh").read_text(encoding="utf-8")
