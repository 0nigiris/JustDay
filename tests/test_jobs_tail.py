"""Список задач перечитывал журнал каждой целиком — у ffmpeg это сотни мегабайт на каждый запрос."""
from justday.jobs import Jobs


def test_the_last_lines_of_a_huge_log_come_from_its_tail(tmp_path, monkeypatch):
    log = tmp_path / "j.log"
    log.write_bytes(b"x" * 300 + b"\n" + b"line\n" * 2_000_000 + b"10%\r50%\r100%\nready\n")
    jobs = Jobs(lambda: None, lambda j: None)
    jobs.items["a"] = {"log": str(log)}
    read = []
    real_open = open

    def spy(path, mode="r", *a, **k):
        fh = real_open(path, mode, *a, **k)
        orig = fh.read
        fh.read = lambda *x: read.append(r := orig(*x)) or r
        return fh

    monkeypatch.setattr("builtins.open", spy)
    assert jobs.tail("a", 2) == "100%\nready"
    assert sum(map(len, read)) <= 65536
