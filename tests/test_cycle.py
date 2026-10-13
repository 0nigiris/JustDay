"""Цикл ассистента: шаг «в 05:00» должен пройти раз в сутки, а не каждую минуту до утра, и не при нём,
если сказано «без него». И шаг, что обновляет JustDay, не должен умирать вместе с перезапуском демона."""
import time

from justday import cycle

NOW = time.mktime((2026, 10, 14, 6, 0, 0, 0, 0, -1))  # 06:00
FIVE = time.mktime((2026, 10, 14, 5, 0, 0, 0, 0, -1))


def test_daily_step_runs_once_after_its_hour():
    step = {"name": "Обновить", "run": "true", "at": "05:00"}
    assert cycle.due(step, 0, NOW, None)
    assert not cycle.due(step, FIVE + 60, NOW, None)               # сегодня уже был
    assert not cycle.due(step, 0, FIVE - 3600, None)               # ещё не время
    assert cycle.due(step, FIVE - 86400 + 60, NOW, None)           # вчерашний не в счёт


def test_away_step_waits_while_he_is_at_the_machine():
    step = {"name": "Обновить", "run": "true", "every_hours": 1, "away": True}
    assert not cycle.due(step, 0, NOW, True)
    assert not cycle.due(step, 0, NOW, None)  # островок молчит — человека не видно, но и «ушёл» не сказано
    assert cycle.due(step, 0, NOW, False)
    assert not cycle.due({**step, "on": False}, 0, NOW, False)


def test_failed_step_still_counts_and_lands_in_journal(monkeypatch, tmp_path):
    monkeypatch.setattr(cycle, "DIR", tmp_path)
    monkeypatch.setattr(cycle, "LAST", tmp_path / "last.json")
    monkeypatch.setattr(cycle, "steps", lambda cfg=None: [{"name": "Сломанный", "run": "echo беда; exit 3"}])
    monkeypatch.setattr(cycle.shutil, "which", lambda _: None)  # без notify-send
    assert cycle.run("Сломанный") == 3
    assert "Сломанный" in cycle.last()
    assert "ошибка 3" in cycle.journal() and "беда" in cycle.journal()
    assert cycle.next_due({"cycle": {"steps": cycle.steps()}}, None) is None


def test_step_runs_as_its_own_unit_not_as_daemon_child(monkeypatch):
    calls = []
    monkeypatch.setattr(cycle.shutil, "which", lambda _: "/usr/bin/systemd-run")
    monkeypatch.setattr(cycle.subprocess, "run", lambda cmd, **k: calls.append(cmd) or type("P", (), {"returncode": 0}))
    assert cycle.launch("Обновить JustDay")
    assert calls[-1][0] == "systemd-run" and f"--unit={cycle.UNIT}" in calls[-1]


def test_manual_run_refuses_while_another_step_holds_the_lock(monkeypatch, tmp_path):
    """Ручной запуск мимо службы не должен идти параллельно с шагом, который уже обновляет установку."""
    import fcntl

    monkeypatch.setattr(cycle, "DIR", tmp_path)
    monkeypatch.setattr(cycle, "LAST", tmp_path / "last.json")
    monkeypatch.setattr(cycle, "steps", lambda cfg=None: [{"name": "Обновить", "run": "echo шаг"}])
    with open(tmp_path / "run.lock", "w") as held:
        fcntl.flock(held, fcntl.LOCK_EX | fcntl.LOCK_NB)
        assert cycle.run("Обновить") == 75
        assert not (tmp_path / "last.json").exists()  # второй не отметился как сделанный
