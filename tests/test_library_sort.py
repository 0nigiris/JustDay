from justday import media


def test_titles_with_signs_and_digits_go_after_letters():
    """В медиатеке «(Remix)» и «2 Phut Hon» лежали первыми и закрывали весь алфавит."""
    names = ["Zebra", "(Remix)", "Abba", "2 Phut", "Яблоко"]
    assert sorted(names, key=media._abc) == ["Abba", "Zebra", "Яблоко", "(Remix)", "2 Phut"]


def test_added_and_length_sorts(monkeypatch, tmp_path):
    """Скачанная давно, но игранная вчера песня была только в «Недавних» — по дате добавления её не найти;
    трек без известной длины (0) стоял первым в сортировке по длине."""
    import os

    files = {}
    for name, mtime in (("old", 100), ("new", 300)):
        f = tmp_path / f"{name}.opus"
        f.write_bytes(b"x")
        os.utime(f, (mtime, mtime))
        files[name] = f
    recs = [{"file": str(files["old"]), "title": "old", "played": 1000, "duration": 0},
            {"file": str(files["new"]), "title": "new", "played": 0, "duration": 200}]
    monkeypatch.setattr(media, "library", lambda kind="music": recs)
    assert [r["title"] for r in media.library_view("recent")] == ["old", "new"]
    assert [r["title"] for r in media.library_view("downloaded")] == ["new", "old"]
    assert [r["title"] for r in media.library_view("duration")] == ["new", "old"]
