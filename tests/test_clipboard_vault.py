"""Скопировал ключ API, потом ещё что-то — ключ должен остаться под рукой, но не на диске."""
from justday import clipboard


def test_secret_is_kept_in_memory_only_and_can_be_pasted_back(tmp_path, monkeypatch):
    monkeypatch.setattr(clipboard, "STORE", tmp_path / "h.json")
    clipboard._vault.clear()
    key = "sk-" + "a1B2c3D4" * 4
    clipboard.store(key)
    clipboard.store("обычный текст")
    assert key not in (tmp_path / "h.json").read_text()
    top = clipboard.items()
    secret = next(i for i in top if i["kind"] == "secret")
    assert key not in secret["preview"] and "•" in secret["preview"]
    assert clipboard.get(secret["id"])["text"] == key
    clipboard._vault.clear()   # память процесса общая для всех тестов: чужие проверки списка не должны видеть наш ключ
