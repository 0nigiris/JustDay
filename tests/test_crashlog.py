"""Служба упала и перезапустилась молча — следов не оставалось (Р2-45)."""
from justday import crashlog


def test_clean_exit_leaves_no_report_but_a_crash_does(tmp_path, monkeypatch):
    monkeypatch.setattr(crashlog, "DIR", tmp_path / "crashes")
    monkeypatch.setattr(crashlog, "_run", lambda cmd, timeout=15: "строка журнала")
    assert crashlog.save("justday.service", "success") is None
    path = crashlog.save("justday-ui.service", "signal")
    assert path and "строка журнала" in path.read_text(encoding="utf-8") and crashlog.count() >= 0


def test_only_the_last_reports_are_kept(tmp_path, monkeypatch):
    monkeypatch.setattr(crashlog, "DIR", tmp_path / "crashes")
    monkeypatch.setattr(crashlog, "_run", lambda cmd, timeout=15: "")
    monkeypatch.setattr(crashlog, "KEEP", 3)
    (tmp_path / "crashes").mkdir()
    for i in range(6):
        (tmp_path / "crashes" / f"2020010{i}-x.log").write_text("x")
    crashlog.save("justday.service", "exit-code")
    assert len(list((tmp_path / "crashes").glob("*.log"))) == 3


def test_home_directory_is_scrubbed_from_reports(monkeypatch):
    from pathlib import Path
    assert str(Path.home()) not in crashlog.scrub(f"{Path.home()}/x.py")
