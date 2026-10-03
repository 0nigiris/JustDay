"""История разговоров: найти длинную задачу, не показав чужих писем и паролей."""
from __future__ import annotations

from justday import events, history


def _ev(kind, ts, **kw):
    return {"kind": kind, "ts": f"2026-10-03T10:{ts}:00", **kw}


def test_the_long_task_he_said_can_be_found_but_mail_read_aloud_and_passwords_cannot(monkeypatch) -> None:
    """«Наговорил длинную задачу и не нашёл её нигде». Находится по слову; письмо и пароль — нет."""
    log = [
        _ev("heard", "01", text="сделай очередь задач в окне оболочки"),
        _ev("say", "02", text="Сделаю очередь."),
        _ev("heard", "03", text="что в почте?"),
        _ev("tool", "04", name="Bash", desc="justday mail inbox", input="{}"),
        _ev("say", "05", text="Письмо от банка: ваш код 4411."),
        _ev("heard", "06", text="мой пароль sk-ant-api03-abcdefghijklmnopqrstuvwxyz0123456789"),
    ]
    monkeypatch.setattr(events, "read", lambda day="": log)
    got = history.items()
    texts = [g["text"] for g in got]
    assert texts[0] == "что в почте?" and "Письмо от банка" not in " ".join(texts)
    assert not any("sk-ant" in t for t in texts)
    assert [g["text"] for g in history.items("очередь ОКНЕ")] == ["сделай очередь задач в окне оболочки"]
