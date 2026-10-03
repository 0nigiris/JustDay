"""Необязательные части: что считается установленным и какая команда это меняет."""
from justday import parts


def test_every_part_has_a_size_and_a_reason():
    for name, part in parts.PARTS.items():
        assert part.name == name
        assert part.size.startswith("~")
        assert part.what and part.without


def test_have_checks_the_module_not_the_settings(monkeypatch):
    monkeypatch.setattr(parts.importlib.util, "find_spec", lambda mod: object() if mod == "torch" else None)
    assert parts.have("voice")
    assert not parts.have("speech")
    assert not parts.have("нет такой части")


def test_suggested_asks_for_cuda_only_with_an_nvidia_card(monkeypatch):
    monkeypatch.setattr(parts, "gpu", lambda: False)
    assert parts.suggested() == ["speech", "voice"]
    monkeypatch.setattr(parts, "gpu", lambda: True)
    assert parts.suggested() == ["speech", "voice", "cuda"]


def test_add_keeps_what_is_already_there(monkeypatch):
    monkeypatch.setattr(parts, "installed", lambda: ["speech"])
    ok, cmd = parts.sync(add=("voice",), dry=True)
    assert ok and cmd.endswith("--extra speech --extra voice")   # порядок как в PARTS, а не как в аргументах


def test_remove_drops_only_the_named_part(monkeypatch):
    monkeypatch.setattr(parts, "installed", lambda: ["speech", "voice", "cuda"])
    ok, cmd = parts.sync(drop=("cuda",), dry=True)
    assert ok and "--extra cuda" not in cmd and "--extra speech" in cmd and "--extra voice" in cmd


def test_unknown_part_is_refused_before_anything_runs(monkeypatch):
    monkeypatch.setattr(parts, "installed", lambda: [])
    ok, why = parts.sync(add=("gpu",))
    assert not ok and "gpu" in why


def test_missing_note_tells_the_command(monkeypatch):
    assert "justday parts add speech" in parts.missing_note("speech")


def test_the_usb_stick_was_built_without_anything_to_run() -> None:
    """Флешка собиралась и не запускалась: окружения на ней не было вовсе.

    Запускалка звала `app/.venv/bin/justday`, а сборка его не делала — и на чужом компьютере
    скрипт умирал первой же строкой. Собрать venv прямо на флешке тоже нельзя: он заводит ссылку
    lib64 → lib, а флешки обычно в exfat, где ссылок не бывает («Operation not permitted»).
    Поэтому нужное ставится в обычную папку рядом.
    """
    from justday import portable

    assert ".venv" not in portable.SCRIPT, "запускалка снова зовёт окружение, которого нет"
    assert "--target" in portable.SCRIPT, "нужное ставится не в папку — на exfat это не заведётся"
    assert "PYTHONPATH" in portable.SCRIPT, "поставленное некуда подключить"
    assert "PIP_CACHE_DIR" in portable.SCRIPT, "кэш установки остался бы на чужой машине следом"
