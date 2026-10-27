"""Большая задача («дз по технологии») живёт неделю, закреплённая вечно, а старая не пропадает навсегда, а уезжает в архив."""
import time

from justday import chats, config


def test_old_goes_to_archive_pinned_stays(tmp_path, monkeypatch):
    monkeypatch.setattr(config, "DATA_DIR", tmp_path)
    old, pinned, fresh = chats.create("старая"), chats.create("закреплённая"), chats.create("свежая")
    for cid in (old, pinned, fresh):
        chats.append(cid, "user", "привет")
    chats.set_meta(pinned, pinned=True)
    for cid in (old, pinned):
        p = chats._path(cid)
        rows = chats._read(p)
        for r in rows:
            if not r.get("meta"):
                r["ts"] = time.time() - 30 * 86400
        p.write_text("".join(__import__("json").dumps(r) + "\n" for r in rows))
    assert chats.sweep(7) == 1
    assert {c["id"] for c in chats.listing()} == {pinned, fresh}
    assert (tmp_path / "chats" / "архив" / f"{old}.jsonl").exists()
    assert chats.sweep(0) == 0
