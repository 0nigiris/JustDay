"""qs падал и сам поднимался: systemd сбоя не видел, отчёта не было, человек видел мигнувший экран."""
import os

from justday import crashlog


def test_сбой_qs_становится_отчётом_с_временем_сбоя(tmp_path, monkeypatch):
    qs = tmp_path / "crashes" / "abc"
    qs.mkdir(parents=True)
    (qs / "report.txt").write_text("===== Version Information =====\nQuickshell: 0.3.1\n")
    os.utime(qs, (1_000_000, 1_000_000))
    monkeypatch.setattr(crashlog, "QS_CRASHES", tmp_path / "crashes")
    monkeypatch.setattr(crashlog, "DIR", tmp_path / "out")
    crashlog.adopt_quickshell()
    crashlog.adopt_quickshell()  # второй вызов не плодит копий
    logs = list((tmp_path / "out").glob("*.log"))
    assert len(logs) == 1 and "Quickshell: 0.3.1" in logs[0].read_text()
    assert int(logs[0].stat().st_mtime) == 1_000_000
