"""Оперативная память читается в каждом разговоре и дорожает с каждой строкой. Старая домашка должна сама
уехать в долгую — а его правило «не называть брат» не должно уехать никогда, сколько бы его не трогали.
И ничто не теряется: строка переезжает, запись на месте, тронутое снова дело возвращается."""
import os
import time

from justday import manage, memory


def _note(base, name, kind, days, now):
    p = base / name
    p.write_text(f"---\nname: {name}\nmetadata:\n  type: {kind}\n---\n\nтекст\n", encoding="utf-8")
    os.utime(p, (now - days * 86400, now - days * 86400))
    return f"- [{name}]({name}) — {kind}"


def test_old_project_cools_rules_stay_and_touched_returns(monkeypatch, tmp_path):
    monkeypatch.setattr(memory, "folder", lambda: tmp_path)
    now = time.time()
    homework = _note(tmp_path, "project_homework.md", "project", 30, now)
    brat = _note(tmp_path, "feedback_no_brat.md", "feedback", 90, now)
    fresh = _note(tmp_path, "project_now.md", "project", 2, now)
    (tmp_path / memory.INDEX).write_text("\n".join([homework, brat, fresh]) + "\n", encoding="utf-8")

    r = memory.tidy(now)
    hot = (tmp_path / memory.INDEX).read_text(encoding="utf-8")
    assert r["moved_out"] == [homework]
    assert homework not in hot and brat in hot and fresh in hot
    assert memory.LONG_LINK in hot  # мозг знает, где искать уехавшее
    assert homework in (tmp_path / memory.LONG).read_text(encoding="utf-8")
    assert (tmp_path / "project_homework.md").exists()
    assert memory.tidy(now)["moved_out"] == []  # второй проход ничего не двигает

    os.utime(tmp_path / "project_homework.md", (now, now))  # мозг снова поправил запись
    assert memory.tidy(now)["moved_in"] == [homework]
    hot = (tmp_path / memory.INDEX).read_text(encoding="utf-8")
    assert homework in hot and memory.LONG_LINK not in hot


def test_forget_drops_line_that_moved_to_long_memory(monkeypatch, tmp_path):
    now = time.time()
    line = _note(tmp_path, "project_old.md", "project", 30, now)
    (tmp_path / memory.INDEX).write_text("", encoding="utf-8")
    (tmp_path / memory.LONG).write_text(line + "\n", encoding="utf-8")
    monkeypatch.setattr(manage, "trash", lambda p: {"ok": True, "error": ""})
    manage.forget_memory(tmp_path / "project_old.md")
    assert "project_old.md" not in (tmp_path / memory.LONG).read_text(encoding="utf-8")


def test_memory_warning_follows_his_threshold_and_zero_means_silence(monkeypatch, tmp_path):
    """Порог «память разрослась» был зашит числом 40: ни увидеть, сколько строк сейчас, ни заглушить
    напоминание. Теперь порог из настроек, 0 — молчать, а страница памяти показывает текущее число."""
    monkeypatch.setattr(memory, "folder", lambda: tmp_path)
    monkeypatch.setattr("justday.cli.memory_dir", lambda: tmp_path)
    (tmp_path / memory.INDEX).write_text("".join(f"- [n{i}](n{i}.md) — дело\n" for i in range(12)), encoding="utf-8")

    assert memory.state(10)["busy"] is True
    assert memory.state(20)["busy"] is False
    assert memory.state(0)["busy"] is False, "0 — не предупреждать, а не «всегда много»"
    assert manage.memory_files()["index_lines"] == 12
