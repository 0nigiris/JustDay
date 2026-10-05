"""Р-37: журнал демона разросся до 11 МБ без ротации. Рядом лежит накопленное — оно не должно пропасть при
включении ротации, а новая запись не должна расти бесконечно."""
import logging

from justday.daemon import log_file_handler


def _write(handler: logging.Handler, n: int) -> None:
    for i in range(n):
        handler.emit(logging.LogRecord("t", logging.INFO, "", 0, f"строка {i} " + "x" * 80, None, None))


def test_an_oversized_old_log_is_kept_as_a_backup_not_lost(tmp_path) -> None:
    path = tmp_path / "justday.log"
    path.write_text("СТАРЫЙ ЖУРНАЛ\n" * 500, encoding="utf-8")        # уже больше предела
    handler = log_file_handler(path, max_bytes=1000)
    _write(handler, 1)
    handler.close()
    assert (tmp_path / "justday.log.1").read_text(encoding="utf-8").startswith("СТАРЫЙ ЖУРНАЛ")
    assert path.stat().st_size < 1000


def test_the_log_stays_bounded_and_keeps_three_backups(tmp_path) -> None:
    path = tmp_path / "justday.log"
    handler = log_file_handler(path, max_bytes=1000)
    _write(handler, 200)
    handler.close()
    names = sorted(p.name for p in tmp_path.iterdir() if p.name.startswith("justday.log"))
    assert names == ["justday.log", "justday.log.1", "justday.log.2", "justday.log.3"]
    assert all(p.stat().st_size < 1200 for p in tmp_path.glob("justday.log*"))
